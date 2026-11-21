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

Every action a person takes locks the survey row first (``lock_open``), so
two people pressing at once are taken one after the other: the second sees
what the first did, and the message is queued once.

**The "we tried to call you" message** (``send_tried_to_call``) goes once per
round: as a chat message if her 24 hours are open when it is sent, otherwise
as the approved template ``feedback_tried_to_call``. It is claimed for the
round in a committed transaction of its own before WhatsApp is asked, and no
row lock is held while WhatsApp is asked. WhatsApp not answering is tried
again by the job, until its last try. If it cannot go, the history says so
and tells the team to write to her themselves; if the run was interrupted
after the claim, the sweep says it may have gone out
(``recover_interrupted_tried``). Neither is tried again on its own.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.core.businesstime import utcnow
from app.modules.inbox.models import (
    FeedbackFollowUp,
    FeedbackSettings,
    FeedbackSurvey,
    InboxConversation,
    InboxMessage,
)
from app.modules.inbox.services import feedback, feedback_messages, outbound, sending
from app.modules.inbox.services.events import _conversation
from app.modules.inbox.services.meta import MetaClient, MetaError
from app.modules.inbox.services.outbound import NotSent, send_text
from app.shared.models.identity import UserAccount
from app.shared.models.integration import BackgroundJob
from app.shared.services.audit import record_audit
from app.shared.services.jobs import MAX_ATTEMPTS, JobKind, JobStatus, PermanentFailure, enqueue
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


def _user_names(db: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    return {
        user_id: name or email
        for user_id, name, email in db.execute(
            select(UserAccount.id, UserAccount.display_name, UserAccount.email).where(
                UserAccount.id.in_(ids)
            )
        )
    }


def _words_owed(
    db: Session, surveys: list[FeedbackSurvey], entries: dict[int, list[FeedbackFollowUp]]
) -> dict[int, str]:
    """The words of the "we tried to call you" message each open follow-up
    would get if it went now, for the pop-up to quote: the chat message while
    her 24 hours are open, the approved message's once they have closed. Only
    where this round's message is not yet accounted for or taken. At most two
    queries however many there are: the wording, then the chats."""
    owed = [
        survey
        for survey in surveys
        if is_open(survey)
        and survey.tried_claimed_round != survey.follow_up_round
        and not any(
            entry.round == survey.follow_up_round
            and entry.kind in ("message_sent", "message_failed")
            for entry in entries[survey.id]
        )
    ]
    if not owed:
        return {}
    cfg = db.get(FeedbackSettings, 1)
    chat_ids = {survey.conversation_id for survey in owed if survey.conversation_id}
    chats = (
        {c.id: c for c in db.scalars(select(InboxConversation).where(InboxConversation.id.in_(chat_ids)))}
        if chat_ids
        else {}
    )
    now = utcnow()
    found: dict[int, str] = {}
    for survey in owed:
        chat = chats.get(survey.conversation_id)
        if chat is not None and outbound.window_open(chat, now):
            found[survey.id] = tried_to_call_words(cfg, survey)
        else:
            found[survey.id] = feedback.TRIED_CHAT.format(
                order=survey.order_name or survey.shopify_order_id
            )
    return found


def describe_many(db: Session, surveys: list[FeedbackSurvey]) -> dict[int, dict]:
    """What the follow-up looks like for each survey, in a fixed number of
    queries however many there are: every history line, every name on them,
    and for open ones the wording and their chats (``_words_owed``).

    Per survey id: the ``history`` (oldest first), the current round's
    ``no_answer_count`` and ``message_sent``, ``waiting_since``, when and by
    whom it was closed as couldn't reach, the round, and
    ``tried_to_call_text`` (null unless the message is still to go).
    """
    if not surveys:
        return {}
    ids = [survey.id for survey in surveys]
    entries: dict[int, list[FeedbackFollowUp]] = {survey_id: [] for survey_id in ids}
    for entry in db.scalars(
        select(FeedbackFollowUp)
        .where(FeedbackFollowUp.survey_id.in_(ids))
        .order_by(FeedbackFollowUp.at, FeedbackFollowUp.id)
    ):
        entries[entry.survey_id].append(entry)
    people = {entry.actor_id for lines in entries.values() for entry in lines if entry.actor_id}
    people |= {survey.unreached_by for survey in surveys if survey.unreached_by}
    names = _user_names(db, people)
    words = _words_owed(db, surveys, entries)
    found: dict[int, dict] = {}
    for survey in surveys:
        lines = entries[survey.id]
        current = [entry for entry in lines if entry.round == survey.follow_up_round]
        waiting = survey.round_started_at or survey.rated_at
        found[survey.id] = {
            "history": [
                {
                    "id": entry.id,
                    "round": entry.round,
                    "kind": entry.kind,
                    "note": entry.note,
                    "at": entry.at.isoformat(),
                    "by_name": names.get(entry.actor_id) if entry.actor_id else None,
                }
                for entry in lines
            ],
            "no_answer_count": sum(1 for entry in current if entry.kind == "no_answer"),
            "message_sent": any(entry.kind == "message_sent" for entry in current),
            "waiting_since": waiting.isoformat() if waiting else None,
            "unreached_at": survey.unreached_at.isoformat() if survey.unreached_at else None,
            "unreached_by_name": names.get(survey.unreached_by) if survey.unreached_by else None,
            "follow_up_round": survey.follow_up_round,
            "tried_to_call_text": words.get(survey.id),
        }
    return found


def describe_one(db: Session, survey: FeedbackSurvey) -> dict:
    """One survey as the sheet lists it, with its follow-up."""
    resolved_by = feedback._names(db, [survey]).get(survey.resolved_by)
    return feedback.describe(survey, resolved_by, describe_many(db, [survey])[survey.id])


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

#: What the history says when the message may or may not have gone out.
INTERRUPTED_TRIED = (
    "Interrupted while sending the WhatsApp message that we tried to call her: "
    "it may have gone out. Check the chat in WhatsApp before writing to her."
)


def _reference(survey: FeedbackSurvey) -> str:
    """One per survey and round: what finds the message in the chat."""
    return f"fbt:{survey.id}:{survey.follow_up_round}"


def _settled(db: Session, survey: FeedbackSurvey) -> bool:
    """Whether this round's message is already accounted for: sent, or
    failed and told to the team (a failure is not tried again)."""
    return message_sent(db, survey) or _count(db, survey, "message_failed") > 0


def _failed(db: Session, survey: FeedbackSurvey, why: str, now: datetime) -> None:
    add_entry(db, survey, "message_failed", note=COULD_NOT_SEND.format(why=why)[:NOTE_MAX], at=now)


def _claim_tried(survey_id: int, round_: int) -> bool:
    """Take this round's message for sending, in a transaction of its own.

    Committed before WhatsApp is asked: whatever happens next - a crash after
    WhatsApp accepted it, a lost lease, a second worker - the message counts
    as taken and nobody sends it a second time. Only while the follow-up is
    open and still in that round.
    """
    from app.db import SessionLocal

    with SessionLocal() as own:
        claimed = own.execute(
            update(FeedbackSurvey)
            .where(
                FeedbackSurvey.id == survey_id,
                FeedbackSurvey.rating == "unhappy",
                FeedbackSurvey.step == "support",
                FeedbackSurvey.follow_up_round == round_,
                or_(
                    FeedbackSurvey.tried_claimed_round.is_(None),
                    FeedbackSurvey.tried_claimed_round != round_,
                ),
            )
            .values(tried_claimed_round=round_, tried_claimed_at=utcnow())
        ).rowcount
        own.commit()
    return claimed == 1


def _release_tried(survey_id: int, round_: int) -> None:
    """Give the claim back, in a transaction of its own, because nothing went
    out and the job is to be tried again."""
    from app.db import SessionLocal

    with SessionLocal() as own:
        own.execute(
            update(FeedbackSurvey)
            .where(FeedbackSurvey.id == survey_id, FeedbackSurvey.tried_claimed_round == round_)
            .values(tried_claimed_round=None, tried_claimed_at=None)
        )
        own.commit()


def _set_claim(survey: FeedbackSurvey, round_: int | None, at: datetime | None) -> None:
    """What a claim committed elsewhere did, as this session sees it."""
    set_committed_value(survey, "tried_claimed_round", round_)
    set_committed_value(survey, "tried_claimed_at", at)


def send_tried_to_call(
    db: Session,
    survey_id: int,
    *,
    client: MetaClient | None = None,
    now: datetime | None = None,
    final_attempt: bool = False,
    claim: Callable[[int, int], bool] | None = None,
    release: Callable[[int, int], None] | None = None,
) -> FeedbackSurvey | None:
    """Tell her we tried to call, once this round: as a chat message if her
    24 hours are open now, otherwise as the approved template.

    Does nothing unless the follow-up is still open (someone may have reached
    her, or closed it, since the job was queued) and the message is not yet
    accounted for. A message already in the chat under this round's
    reference only gets its missing line in the history.

    **Claimed before WhatsApp is asked** (``tried_claimed_round`` and
    ``tried_claimed_at``, committed in a session of its own), so it is **sent
    at most once a round**, even if this run dies after WhatsApp took it. The
    survey row is not locked while WhatsApp is asked: the claim is what keeps
    a second run out.

    - A *retryable* Meta error (WhatsApp did not answer): the claim is given
      back and the error raised, so the job is tried again - unless this is
      the job's ``final_attempt``, when it is written in the history like any
      other failure, telling the team to write to her.
    - Anything else that stops it - sending is off, this server may not
      message her, WhatsApp refused it for good (a template not approved yet,
      say) - is written in the history, telling the team to write to her.
    - A crash: the claim stands and no message is in the chat; the sweep
      writes in the history that it may have gone out
      (``recover_interrupted_tried``). It is not sent again on its own.
    """
    claim = claim or _claim_tried
    release = release or _release_tried
    survey = db.get(FeedbackSurvey, survey_id)
    if survey is None or not is_open(survey) or not survey.phone or _settled(db, survey):
        return survey
    now = now or utcnow()
    round_ = survey.follow_up_round
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
    if survey.tried_claimed_round == round_:
        # Taken by another run: still sending, or gone with nothing to show
        # for it, which the sweep reports. Never sent twice.
        return survey
    if (why := sending.refusal(db, survey.phone)) is not None:
        _failed(db, survey, why, now)
        return survey

    conversation = (
        db.get(InboxConversation, survey.conversation_id) if survey.conversation_id else None
    ) or _conversation(db, survey.phone, None)
    # Her 24 hours are looked at now, not when the call was recorded.
    words = (
        tried_to_call_words(feedback.get_settings(db), survey)
        if outbound.window_open(conversation, now)
        else None
    )
    if not claim(survey.id, round_):
        return survey
    _set_claim(survey, round_, now)
    try:
        if words is not None:
            message = send_text(
                db, conversation, words, origin="automatic", source_ref=reference, client=client
            )
        else:
            message = _send_tried_template(db, survey, conversation, reference, client)
    except MetaError as exc:
        if final_attempt:
            # Nobody is coming back to try again: the claim stands, and the
            # line settles the round.
            _failed(db, survey, str(exc), now)
            survey.updated_at = now
            return survey
        release(survey.id, round_)
        _set_claim(survey, None, None)
        raise
    except NotSent as exc:
        _failed(db, survey, str(exc), now)
        return survey
    if message.status == "failed":
        _failed(db, survey, message.error or "WhatsApp refused it.", now)
    else:
        add_entry(db, survey, "message_sent", note=message.body, at=now)
    survey.updated_at = now
    return survey


def tried_to_call_words(cfg: FeedbackSettings | None, survey: FeedbackSurvey) -> str:
    """The chat message's words for her, filled in: what goes while her 24
    hours are open."""
    return feedback_messages.text(
        cfg, "tried_to_call",
        name=feedback_messages.first_name(survey),
        order=survey.order_name or survey.shopify_order_id,
    )


def recover_interrupted_tried(db: Session, now: datetime | None = None) -> int:
    """Messages claimed with nothing in the chat to show for it ten minutes
    later: the history says it may have gone out and to check the chat. Never
    sent again on its own, because the platform cannot know whether it went.
    Returns how many were reported."""
    now = now or utcnow()
    S, F = FeedbackSurvey, FeedbackFollowUp
    reference = func.concat("fbt:", S.id, ":", S.tried_claimed_round)
    stuck = list(
        db.scalars(
            select(S).where(
                S.tried_claimed_round.is_not(None),
                S.tried_claimed_at < now - outbound.INTERRUPTED_AFTER,
                ~exists().where(InboxMessage.source_ref == reference),
                ~exists().where(
                    F.survey_id == S.id,
                    F.round == S.tried_claimed_round,
                    F.kind.in_(("message_sent", "message_failed")),
                ),
            )
        )
    )
    for survey in stuck:
        # In the round it was claimed for, which may not be the current one.
        db.add(
            FeedbackFollowUp(
                survey_id=survey.id,
                round=survey.tried_claimed_round,
                kind="message_failed",
                note=INTERRUPTED_TRIED,
                at=now,
            )
        )
    db.flush()
    return len(stuck)


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


def _final_attempt(db: Session, survey_id: int) -> bool:
    """Whether this is the job's last try at the message.

    The job's own count of failed tries is the only thing that survives a
    failed run (the run's own writes are rolled back), so it is read from the
    job's row, found by its key (survey, then round). Not found (run by hand,
    in a test) is the last try: nobody is coming back to try again.
    """
    kind = JobKind.INBOX_FEEDBACK_TRIED_TO_CALL
    failed = db.scalar(
        select(BackgroundJob.attempts)
        .where(
            BackgroundJob.kind == kind,
            BackgroundJob.dedupe_key.startswith(f"{kind}:{survey_id}:", autoescape=True),
            BackgroundJob.status == JobStatus.RUNNING,
        )
        .order_by(BackgroundJob.id.desc())
        .limit(1)
    )
    return failed is None or failed + 1 >= MAX_ATTEMPTS


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
    send_tried_to_call(db, survey_id, final_attempt=_final_attempt(db, survey_id))
