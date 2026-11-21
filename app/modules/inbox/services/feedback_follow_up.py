"""What a person does to follow up an unhappy answer, kept as a record
(ADR 0087, amending ADR 0083 decisions 4 and 6).

A follow-up is **open** while the answer is *Not happy* and the survey waits
for a person (step ``support``). While it is open a person can press
*Resolved* (``feedback_replies.resolve``, which needs a note), *No answer*
(``no_answer``) or *Add note* (``add_note``). Each adds a line to the
survey's history, ``feedback_follow_up``, which is **never edited or
deleted**: it is what happened, and a mistake is put right by a new note.

**Rounds.** A round starts when she answers *Not happy* (round 0), when she
says *No, not solved*, and when she writes back after *Couldn't reach*
(``start_round``). The no-answer count and the "we tried to call you"
message are per round, so a second round can send the message once more.

- The **2nd** call with no answer in a round queues the message.
- From the **3rd**, the follow-up can be closed as *Couldn't reach*: she is
  not asked *Was your issue solved?* and gets no code.
- A message she **types** within **14 days** of that close opens it again
  (``reopen_if_unreached``). A button tap is not her writing back.

Every action locks the survey row first (``lock_open``), so two people
pressing at once are taken one after the other: the second sees what the
first did, and the message is queued once.

**The "we tried to call you" message** (``send_tried_to_call``) goes once per
round: as a chat message if her 24 hours are open when it is sent, otherwise
as the approved template ``feedback_tried_to_call``. If it cannot go, the
history says so and tells the team to write to her themselves; it is not
tried again on its own.
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.modules.inbox.models import (
    FeedbackFollowUp,
    FeedbackSurvey,
    InboxConversation,
    InboxMessage,
)
from app.modules.inbox.services import feedback, feedback_messages, outbound, sending
from app.modules.inbox.services.events import _conversation
from app.modules.inbox.services.meta import MetaClient, MetaError
from app.modules.inbox.services.outbound import NotSent, send_text
from app.shared.services.audit import record_audit
from app.shared.services.jobs import JobKind, PermanentFailure, enqueue
from app.worker import register_handler

#: The longest a note may be, once trimmed.
NOTE_MAX = 1000
#: The call with no answer after which she is messaged on WhatsApp.
MESSAGE_AFTER_CALLS = 2
#: The call with no answer from which the follow-up can be closed as
#: *Couldn't reach*.
CLOSE_FROM_CALLS = 3
#: How long after *Couldn't reach* a message she types opens it again.
REOPEN_WITHIN = timedelta(days=14)

TOO_LONG = "A note can be at most 1,000 characters."
NOT_OPEN = "Only a follow-up that is still open can be updated."
TOO_EARLY = "It can be closed as couldn't reach from the third call with no answer."
#: What the history says when the message could not go.
COULD_NOT_SEND = "Couldn't send the WhatsApp message: {why} Write to her yourself."


def clean_note(note: str | None, *, required: bool, missing: str) -> str | None:
    """The note as it will be kept: trimmed, and None when there is nothing
    in it. Refused in words when it is required and empty, or too long.
    What she typed is otherwise kept as it is, newlines and all."""
    from app.modules.inbox.services.chats import Refused

    words = (note or "").strip()
    if not words:
        if required:
            raise Refused(missing)
        return None
    if len(words) > NOTE_MAX:
        raise Refused(TOO_LONG)
    return words


def add_entry(
    db: Session,
    survey: FeedbackSurvey,
    kind: str,
    *,
    note: str | None = None,
    actor_id: int | None = None,
    at: datetime | None = None,
) -> FeedbackFollowUp:
    """Add one line to the survey's history, in its current round. The time
    is set here rather than by the database, so lines written in one
    transaction keep the order they happened in."""
    entry = FeedbackFollowUp(
        survey_id=survey.id,
        round=survey.follow_up_round,
        kind=kind,
        note=note,
        actor_id=actor_id,
        at=at or utcnow(),
    )
    db.add(entry)
    db.flush()
    return entry


def _count(db: Session, survey: FeedbackSurvey, kind: str) -> int:
    return db.scalar(
        select(func.count())
        .select_from(FeedbackFollowUp)
        .where(
            FeedbackFollowUp.survey_id == survey.id,
            FeedbackFollowUp.round == survey.follow_up_round,
            FeedbackFollowUp.kind == kind,
        )
    ) or 0


def no_answer_count(db: Session, survey: FeedbackSurvey) -> int:
    """Calls with no answer in the current round."""
    return _count(db, survey, "no_answer")


def message_sent(db: Session, survey: FeedbackSurvey) -> bool:
    """Whether the "we tried to call you" message went in the current round."""
    return _count(db, survey, "message_sent") > 0


def start_round(survey: FeedbackSurvey, at: datetime) -> None:
    """A new round: her calls are counted again, the message may go again,
    and the waiting clock starts again from ``at``."""
    survey.follow_up_round += 1
    survey.round_started_at = at


def is_open(survey: FeedbackSurvey) -> bool:
    return survey.rating == "unhappy" and survey.step == "support"


def lock_open(db: Session, survey_id: int) -> FeedbackSurvey:
    """The survey, locked for this transaction, if its follow-up is still
    open. Refused in words otherwise: someone else resolved it a second ago,
    or the page is out of date."""
    # Imported here: chats builds on the services this module is part of.
    from app.modules.inbox.services.chats import NotFound, Refused

    survey = db.scalar(
        select(FeedbackSurvey).where(FeedbackSurvey.id == survey_id).with_for_update()
    )
    if survey is None:
        raise NotFound("No such feedback.")
    if not is_open(survey):
        raise Refused(NOT_OPEN)
    return survey


def _audit(db: Session, action: str, survey: FeedbackSurvey, user: Any, before: dict, after: dict) -> None:
    record_audit(
        db,
        action=action,
        subject=f"feedback:{survey.id}",
        actor_id=user.id,
        actor_email=getattr(user, "email", None),
        before=before,
        after={**after, "order": survey.order_name, "round": survey.follow_up_round},
    )
    db.flush()


def no_answer(
    db: Session,
    survey_id: int,
    user: Any,
    note: str | None,
    close: bool = False,
    now: datetime | None = None,
) -> FeedbackSurvey:
    """A person called her and she did not answer. The follow-up stays open
    and nothing is sent - except on the 2nd call of a round, when the "we
    tried to call you" message is queued (once per round).

    With ``close``, from the 3rd call, it is closed as *Couldn't reach*
    instead: she is not asked whether it was solved. Asked for earlier, it is
    refused and nothing is written.
    """
    from app.modules.inbox.services.chats import Refused

    survey = lock_open(db, survey_id)
    note = clean_note(note, required=False, missing="")
    now = now or utcnow()
    count = no_answer_count(db, survey) + 1
    if close and count < CLOSE_FROM_CALLS:
        raise Refused(TOO_EARLY)

    before = {"step": survey.step, "count": count - 1}
    add_entry(db, survey, "no_answer", note=note, actor_id=user.id, at=now)
    if count == MESSAGE_AFTER_CALLS and not message_sent(db, survey):
        kind = JobKind.INBOX_FEEDBACK_TRIED_TO_CALL
        enqueue(
            db,
            kind,
            {"survey_id": survey.id},
            run_after=now,
            # One per survey and round, however often it is pressed.
            dedupe_key=f"{kind}:{survey.id}:{survey.follow_up_round}",
        )
    if close:
        add_entry(db, survey, "unreached", actor_id=user.id, at=now)
        survey.step = "done"
        survey.unreached_at = now
        survey.unreached_by = user.id
    survey.updated_at = now
    db.flush()
    _audit(
        db, "inbox.feedback_no_answer", survey, user, before,
        {"step": survey.step, "count": count, "closed": close},
    )
    return survey


def add_note(
    db: Session, survey_id: int, user: Any, note: str, now: datetime | None = None
) -> FeedbackSurvey:
    """A note on an open follow-up ("spoke to her, waiting on finance"). It
    stays open and nothing is sent."""
    survey = lock_open(db, survey_id)
    words = clean_note(note, required=True, missing="Write the note first.")
    now = now or utcnow()
    add_entry(db, survey, "note", note=words, actor_id=user.id, at=now)
    survey.updated_at = now
    db.flush()
    _audit(db, "inbox.feedback_note", survey, user, {"step": survey.step}, {"step": survey.step})
    return survey


def reopen_if_unreached(db: Session, phone: str, at: datetime) -> bool:
    """She typed a message: a follow-up closed as *Couldn't reach* in the 14
    days before it opens again, as a new round. Only her most recent such
    survey, a real one before a test. Nothing is sent to her; the chat is
    already unread. Returns whether one was opened.

    Called only for typed text: a tap is not her writing back.
    """
    survey = db.scalar(
        select(FeedbackSurvey)
        .where(
            FeedbackSurvey.phone == phone,
            FeedbackSurvey.rating == "unhappy",
            FeedbackSurvey.step == "done",
            FeedbackSurvey.unreached_at.is_not(None),
            FeedbackSurvey.unreached_at <= at,
            FeedbackSurvey.unreached_at >= at - REOPEN_WITHIN,
        )
        .order_by(FeedbackSurvey.is_test, FeedbackSurvey.unreached_at.desc())
        .limit(1)
        .with_for_update()
    )
    if survey is None:
        return False
    survey.step = "support"
    survey.unreached_at = None
    survey.unreached_by = None
    start_round(survey, at)
    survey.updated_at = utcnow()
    add_entry(db, survey, "wrote_back", at=at)
    return True


# ── "We tried to call you" ────────────────────────────────────────────────────


def _reference(survey: FeedbackSurvey) -> str:
    """One per survey and round: what finds the message in the chat."""
    return f"fbt:{survey.id}:{survey.follow_up_round}"


def _settled(db: Session, survey: FeedbackSurvey) -> bool:
    """Whether this round's message is already accounted for: sent, or
    failed and told to the team (a failure is not tried again)."""
    return message_sent(db, survey) or _count(db, survey, "message_failed") > 0


def _failed(db: Session, survey: FeedbackSurvey, why: str, now: datetime) -> None:
    add_entry(db, survey, "message_failed", note=COULD_NOT_SEND.format(why=why)[:NOTE_MAX], at=now)


def send_tried_to_call(
    db: Session,
    survey_id: int,
    *,
    client: MetaClient | None = None,
    now: datetime | None = None,
) -> FeedbackSurvey | None:
    """Tell her we tried to call, once this round: as a chat message if her
    24 hours are open now, otherwise as the approved template.

    Does nothing unless the follow-up is still open (someone may have reached
    her, or closed it, since the job was queued) and the message is not yet
    accounted for. **Sent at most once a round**: the survey row is locked,
    and a message already in the chat under this round's reference only gets
    its missing line in the history.

    - A *retryable* Meta error (WhatsApp did not answer) is raised, so the job
      is tried again; nothing is written.
    - Anything else that stops it - sending is off, this server may not
      message her, WhatsApp refused it for good (a template not approved yet,
      say) - is written in the history, telling the team to write to her.
    """
    survey = db.scalar(
        select(FeedbackSurvey).where(FeedbackSurvey.id == survey_id).with_for_update()
    )
    if survey is None or not is_open(survey) or not survey.phone or _settled(db, survey):
        return survey
    now = now or utcnow()
    reference = _reference(survey)
    already = db.scalar(
        select(InboxMessage).where(InboxMessage.source_ref == reference).limit(1)
    )
    if already is not None:
        # Sent already; only the history's line of it was lost.
        if already.status == "failed":
            _failed(db, survey, already.error or "WhatsApp refused it.", now)
        else:
            add_entry(db, survey, "message_sent", note=already.body, at=now)
        return survey
    if (why := sending.refusal(db, survey.phone)) is not None:
        _failed(db, survey, why, now)
        return survey

    conversation = (
        db.get(InboxConversation, survey.conversation_id) if survey.conversation_id else None
    ) or _conversation(db, survey.phone, None)
    order = survey.order_name or survey.shopify_order_id
    try:
        # Her 24 hours are looked at now, not when the call was recorded.
        if outbound.window_open(conversation, now):
            words = feedback_messages.text(
                feedback.get_settings(db), "tried_to_call",
                name=feedback_messages.first_name(survey), order=order,
            )
            message = send_text(
                db, conversation, words, origin="automatic", source_ref=reference, client=client
            )
        else:
            message = _send_tried_template(db, survey, conversation, reference, client)
    except NotSent as exc:
        _failed(db, survey, str(exc), now)
        return survey
    if message.status == "failed":
        _failed(db, survey, message.error or "WhatsApp refused it.", now)
    else:
        add_entry(db, survey, "message_sent", note=message.body, at=now)
    survey.updated_at = now
    return survey


def _send_tried_template(
    db: Session,
    survey: FeedbackSurvey,
    conversation: InboxConversation,
    reference: str,
    client: MetaClient | None,
) -> InboxMessage:
    """The third approved message, for a customer whose 24 hours have closed.
    Returns the message as recorded in the chat (``failed`` if WhatsApp refused
    it for good); a refusal worth retrying is raised."""
    components = [
        {"type": "body", "parameters": [{"type": "text", "text": survey.order_name or ""}]}
    ]
    owned = client is None
    client = client or outbound._client(db)
    try:
        wa_message_id = client.send_template(
            conversation.phone, feedback.TRIED_TEMPLATE, feedback.TRIED_LANGUAGE, components
        )
        status, error = "sent", None
    except MetaError as exc:
        if exc.retryable:
            raise
        wa_message_id, status, error = None, "failed", str(exc)
    finally:
        if owned:
            client.close()
    return outbound.record_outbound(
        db,
        conversation,
        kind="template",
        body=feedback.TRIED_CHAT.format(order=survey.order_name or survey.shopify_order_id),
        origin="automatic",
        status=status,
        wa_message_id=wa_message_id,
        error=error,
        template_name=feedback.TRIED_TEMPLATE,
        order_id=survey.shopify_order_id,
        source_ref=reference,
    )


@register_handler(JobKind.INBOX_FEEDBACK_TRIED_TO_CALL)
def _handle_tried_to_call(db: Session, payload: dict) -> None:
    survey_id = payload.get("survey_id")
    if not isinstance(survey_id, int):
        raise PermanentFailure(
            f"{JobKind.INBOX_FEEDBACK_TRIED_TO_CALL} requires a survey_id; got payload keys "
            f"{sorted(payload)!r}"
        )
    if not feedback.enabled() and not feedback.is_test_survey(db, survey_id):
        # Nothing is sent with the feature off (a test aside), and the team
        # is told, so nobody waits for a message that never went.
        survey = db.scalar(
            select(FeedbackSurvey).where(FeedbackSurvey.id == survey_id).with_for_update()
        )
        if survey is not None and is_open(survey) and not _settled(db, survey):
            _failed(db, survey, "feedback is switched off.", utcnow())
        return
    send_tried_to_call(db, survey_id)
