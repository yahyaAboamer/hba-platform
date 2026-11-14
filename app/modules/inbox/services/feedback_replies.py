"""What follows the first feedback question (ADR 0083): her taps, the next
question after each, her comment, the person who follows up an unhappy
answer, and the question a day after *Resolved*.

**A tap counts only if it is hers and it is expected.** The id in a tap is
whatever the sender's phone sent, so a tap is accepted only when the sender's
number is the survey's own and the survey is on the step that tap answers
(``accepted``). Anything else is stored in the chat like any unmatched tap and
changes nothing. A repeated tap finds the survey on its next step and so is
that kind of tap: a no-op, and no second message.

**The survey's ``step`` is what the chat is waiting for**:

    rating -> reason -> comment -> done            (loved, okay)
    rating -> reason -> support -> solved -> reorder -> done   (unhappy)
                          ^________ (She says no: back to support) ___|

She is told when she says no (``not_solved``): a person will write to her
again.

What a tap *changes* is done when it is applied (``record_tap``); what is
*sent* because of it is queued as a job of its own (``reply``), once per tap,
under that tap's own id - so WhatsApp being down never loses her answer and a
job run twice cannot answer twice. These replies are free messages and so
need her 24 hours open; unlike the automatic reply to a confirmation's tap
they are **not** dropped for being late: she answered, and the next question
is still the right one.

Wording lives in ``feedback_messages``, where an admin can change it.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections.abc import Callable
from typing import Any

from sqlalchemy import BigInteger, cast, exists, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.core.businesstime import utcnow
from app.modules.inbox.models import (
    FeedbackSettings,
    FeedbackSurvey,
    InboxConversation,
    InboxMessage,
)
from app.modules.inbox.services import (
    feedback,
    feedback_codes,
    feedback_messages,
    outbound,
    sending,
)
from app.modules.inbox.services.events import _conversation, _phone
from app.modules.inbox.services.meta import MetaClient, MetaError
from app.modules.inbox.services.outbound import NotSent, send_buttons, send_list, send_text
from app.shared.services.audit import record_audit
from app.shared.models.integration import BackgroundJob
from app.shared.services.jobs import JobKind, JobStatus, PermanentFailure, enqueue
from app.worker import register_handler

logger = logging.getLogger(__name__)

#: Her words count as her comment this long after she gave her reason.
COMMENT_WINDOW = timedelta(hours=24)
#: A person presses *Resolved*; she is asked whether it was this long after.
ASK_SOLVED_AFTER = timedelta(hours=24)
#: ...or this long after, on an administrator's test, which would otherwise
#: take a day to try.
ASK_SOLVED_AFTER_TEST = timedelta(minutes=1)
#: She may say "no" this many times; after the second *No*, the next
#: *Resolved* closes it without asking again.
MAX_REOPENS = 2
#: What a comment is cut to, so a pasted essay cannot fill a row.
MAX_COMMENT = 4000

# ── What a tap says ───────────────────────────────────────────────────────────

_RATING = re.compile(r"fb_(loved|okay|unhappy)_(\d{1,32})")
_REASON = re.compile(r"fbr_([a-z_]{1,20})_(\d{1,12})")
_SOLVED = re.compile(r"fbs_(yes|no)_(\d{1,12})")
_REORDER = re.compile(r"fbo_(very_likely|maybe|unlikely)_(\d{1,12})")

#: Each kind of tap -> the pattern, and the step the survey must be on.
_GRAMMAR = (
    ("rating", _RATING),
    ("reason", _REASON),
    ("solved", _SOLVED),
    ("reorder", _REORDER),
)


@dataclass(frozen=True)
class Tap:
    """A tap on a feedback button, read but not yet believed.

    ``step`` is the step it answers: ``rating``, ``reason``, ``solved`` or
    ``reorder``. ``ref`` is an order id for a rating (the template's buttons
    are built before a survey id is shown to her) and a survey id otherwise.
    """

    step: str
    value: str
    ref: str


def parse_payload(payload: object) -> Tap | None:
    text = str(payload or "")
    for step, pattern in _GRAMMAR:
        found = pattern.fullmatch(text)
        if found:
            return Tap(step, found.group(1), found.group(2))
    return None


def read_tap(fields: dict) -> Tap | None:
    """The feedback tap in a message read by ``events._read_message``, if it is one."""
    if fields.get("kind") != "button":
        return None
    return parse_payload((fields.get("extra") or {}).get("payload"))


def survey_for(db: Session, tap: Tap) -> FeedbackSurvey | None:
    if tap.step == "rating":
        return db.scalar(
            select(FeedbackSurvey).where(FeedbackSurvey.shopify_order_id == tap.ref)
        )
    return db.get(FeedbackSurvey, int(tap.ref))


def accepted(db: Session, tap: Tap, phone: str) -> FeedbackSurvey | None:
    """The survey this tap answers, **only if it is the sender's and it is on
    the step this tap answers**; otherwise None and nothing changes."""
    survey = survey_for(db, tap)
    if survey is None or not survey.phone or _phone(survey.phone) != phone:
        return None
    if survey.state == "skipped" or survey.step != tap.step:
        return None
    if tap.step == "reason" and tap.value not in {key for key, _ in feedback.REASONS.get(survey.rating or "", ())}:
        return None
    if tap.step == "solved" and (survey.rating != "unhappy" or survey.solved_asked_at is None):
        return None
    return survey


def record_tap(
    db: Session,
    survey: FeedbackSurvey,
    tap: Tap,
    at: datetime,
    conversation: InboxConversation,
    message_id: int,
) -> None:
    """Keep her answer and move the survey to its next step. What is sent
    because of it is queued, not done here."""
    now = utcnow()
    survey.conversation_id = conversation.id
    if survey.state in ("pending", "would_send", "sending", "failed", "no_whatsapp"):
        # Her tap proves the question reached her.
        survey.state = "sent"
    survey.updated_at = now

    if tap.step == "rating":
        survey.rating, survey.rated_at, survey.step = tap.value, at, "reason"
    elif tap.step == "reason":
        survey.reason, survey.reason_at = tap.value, at
        survey.step = "support" if survey.rating == "unhappy" else "comment"
    elif tap.step == "solved":
        survey.solved, survey.solved_at = tap.value == "yes", at
        if survey.solved:
            survey.step = "reorder"
        else:
            # Not solved: back to a person, marked as reopened.
            survey.step = "support"
            survey.resolved_at = None
            survey.resolved_by = None
            survey.reopened_count += 1
            survey.solved_asked_at = None
    elif tap.step == "reorder":
        survey.reorder, survey.step = tap.value, "done"
    db.flush()
    queue_reply(db, message_id)


def capture_comment(db: Session, phone: str, body: str | None, at: datetime) -> bool:
    """Her first words after her reason, within 24 hours, are her comment.

    The message stays in the chat as it is; this only copies it onto the
    survey. A survey waiting for a person (``support``) stays there.
    """
    if not body or not body.strip():
        return False
    survey = db.scalar(
        select(FeedbackSurvey)
        .where(
            FeedbackSurvey.phone == phone,
            FeedbackSurvey.step.in_(("comment", "support")),
            FeedbackSurvey.comment.is_(None),
            FeedbackSurvey.reason_at.is_not(None),
            FeedbackSurvey.reason_at <= at,
            FeedbackSurvey.reason_at >= at - COMMENT_WINDOW,
        )
        # A real survey awaiting her words comes before a test: a test only
        # receives them when nothing real is waiting.
        .order_by(FeedbackSurvey.is_test, FeedbackSurvey.reason_at.desc())
        .limit(1)
    )
    if survey is None:
        return False
    survey.comment = body.strip()[:MAX_COMMENT]
    survey.comment_at = at
    if survey.step == "comment":
        survey.step = "done"
    survey.updated_at = utcnow()
    db.flush()
    return True


# ── What is said next ─────────────────────────────────────────────────────────


def get_settings(db: Session) -> FeedbackSettings:
    return feedback.get_settings(db)


def issue_code(
    db: Session, survey: FeedbackSurvey, *, final_attempt: bool = False
) -> str | None:
    """Her reward code, or None (``feedback_codes.issue_code``, which says
    how and why). Called by the closing message (``send_closing``) just before
    it is built. Safe to call twice for one survey: it returns the code she
    already has."""
    return feedback_codes.issue_code(db, survey, final_attempt=final_attempt)


def closing_text(survey: FeedbackSurvey, cfg: FeedbackSettings, code: str | None = None) -> str:
    """The last message, in the wording of ``feedback_messages``: thanks for
    her answer; her code if she has one; the review link if she loved it and
    one is set; then one last line.

    That last line asks what *Something else* was, or else invites her to
    write - except that a customer who loved it and was shown the review link
    gets no invitation (one ask per message), and an unhappy customer gets
    neither: a person has already followed her up. One function, so the
    closing words are put together in one place. Without a code the code line
    is simply absent.
    """
    name = feedback_messages.first_name(survey)
    rating = survey.rating if survey.rating in feedback.RATINGS else "okay"
    lines = [feedback_messages.text(cfg, f"thanks.{rating}", name=name)]
    if code:
        lines.append(
            feedback_messages.text(
                cfg, "code_line", name=name, code=code,
                percent=feedback.DISCOUNT_PERCENT, days=feedback.CODE_DAYS,
            )
        )
    review_url = (cfg.review_url or "").strip()
    review_shown = survey.rating == "loved" and bool(review_url)
    if review_shown:
        lines.append(feedback_messages.text(cfg, "review_line", name=name, url=review_url))
    if survey.rating != "unhappy":
        if _something_else(survey):
            lines.append(feedback_messages.text(cfg, "tell_us", name=name))
        elif not review_shown:
            lines.append(feedback_messages.text(cfg, "invitation", name=name))
    return "\n\n".join(lines)


def _something_else(survey: FeedbackSurvey | None) -> bool:
    return getattr(survey, "reason", None) == feedback.OTHER_REASON


def support_text(cfg: FeedbackSettings, survey: FeedbackSurvey | None = None) -> str:
    """The promise of a person. After *Something else* it also asks what went
    wrong, so whoever writes to her already knows."""
    name = feedback_messages.first_name(survey)
    words = feedback_messages.text(cfg, "support", name=name, hours=cfg.reply_hours)
    if _something_else(survey):
        words += "\n\n" + feedback_messages.text(cfg, "tell_us", name=name)
    return words


def send_closing(
    db: Session,
    survey: FeedbackSurvey,
    conversation: InboxConversation,
    reference: str,
    client: MetaClient | None,
    *,
    final_attempt: bool = False,
):
    """Thank her, with her code if one can be issued. **The thank-you does not
    wait on Shopify**: a code that cannot be issued is left out and the survey
    says why (``issue_code``). ``code_sent_at`` is set only if the message
    carrying the code was really sent."""
    code = issue_code(db, survey, final_attempt=final_attempt)
    words = closing_text(survey, get_settings(db), code)
    message = send_text(
        db, conversation, words, origin="automatic", source_ref=reference, client=client
    )
    if code and message.status != "failed":
        feedback_codes.code_sent(survey)
    return message


def queue_reply(db: Session, message_id: int) -> None:
    enqueue(
        db,
        JobKind.INBOX_FEEDBACK_REPLY,
        {"message_id": message_id},
        dedupe_key=f"{JobKind.INBOX_FEEDBACK_REPLY}:{message_id}",
    )


def reply(
    db: Session,
    message_id: int,
    client: MetaClient | None = None,
    *,
    final_attempt: bool = False,
) -> InboxMessage | None:
    """Answer one tap on a feedback question. At most one message per tap.

    ``None`` when there is nothing to say: not a tap we took as an answer,
    one already answered, her 24 hours closed, or a customer this server may
    not message. The reply is
    stored under the tap's own id, so a job run twice cannot answer twice.

    ``final_attempt`` is the job's last try at a reward code: until then a
    Shopify error that may pass is raised, so the whole reply is tried again
    (nothing has been sent yet); on the last try she is thanked without a code.
    """
    tap = db.get(InboxMessage, message_id)
    if tap is None or tap.direction != "in" or tap.kind != "button" or not tap.wa_message_id:
        return None
    extra: dict[str, Any] = tap.extra or {}
    parsed = parse_payload(extra.get("payload"))
    if parsed is None or extra.get("unmatched") or not tap.shopify_order_id:
        return None
    survey = survey_for(db, parsed)
    if survey is None or survey.shopify_order_id != tap.shopify_order_id:
        return None
    reference = f"fb:{tap.wa_message_id}"[:80]
    if db.scalar(select(InboxMessage.id).where(InboxMessage.source_ref == reference)):
        return None
    conversation = db.get(InboxConversation, tap.conversation_id)

    try:
        message = _next_message(
            db, parsed, survey, conversation, reference, client, final_attempt
        )
    except NotSent:
        # Sending is off, this server may not message her, or her 24 hours
        # have closed. Say nothing.
        return None
    if message is not None and message.status == "failed":
        # WhatsApp refused it for good (the job is not retried). The survey
        # stays on its step; the reason is kept where the Feedback sheet can
        # show it.
        survey.last_error = f"A follow-up could not be sent: {message.error or 'WhatsApp refused it'}"[:300]
        survey.updated_at = utcnow()
    return message


def _next_message(
    db: Session,
    parsed: Tap,
    survey: FeedbackSurvey,
    conversation: InboxConversation,
    reference: str,
    client: MetaClient | None,
    final_attempt: bool = False,
) -> InboxMessage | None:
    """Send what follows this tap, or return None if nothing does."""
    cfg = get_settings(db)
    name = feedback_messages.first_name(survey)
    if parsed.step == "rating":
        return send_list(
            db, conversation,
            feedback_messages.text(cfg, f"reason_question.{parsed.value}", name=name),
            feedback_messages.text(cfg, "list_label"),
            [
                {
                    "id": f"fbr_{key}_{survey.id}",
                    "title": feedback_messages.text(cfg, f"reason_option.{parsed.value}.{key}"),
                }
                for key, _ in feedback.REASONS[parsed.value]
            ],
            origin="automatic", source_ref=reference, client=client,
        )
    if parsed.step == "reason":
        if survey.rating == "unhappy":
            return send_text(
                db, conversation, support_text(cfg, survey),
                origin="automatic", source_ref=reference, client=client,
            )
        return send_closing(
            db, survey, conversation, reference, client, final_attempt=final_attempt
        )
    if parsed.step == "solved":
        if parsed.value != "yes":
            # She says it is not solved: she is told a person will write
            # again. (Reopening it for them was done when her tap was applied.)
            return send_text(
                db, conversation,
                feedback_messages.text(cfg, "not_solved", name=name, hours=cfg.reply_hours),
                origin="automatic", source_ref=reference, client=client,
            )
        return send_buttons(
            db, conversation, feedback_messages.text(cfg, "reorder_question", name=name),
            [
                {
                    "id": f"fbo_{key}_{survey.id}",
                    "title": feedback_messages.text(cfg, f"reorder_option.{key}"),
                }
                for key, _ in feedback.REORDERS
            ],
            origin="automatic", source_ref=reference, client=client,
        )
    # reorder
    return send_closing(
        db, survey, conversation, reference, client, final_attempt=final_attempt
    )


# ── A person presses Resolved ─────────────────────────────────────────────────


def resolve(db: Session, survey_id: int, user: Any, now: datetime | None = None) -> dict:
    """A person has followed up an unhappy answer. Only for an unhappy answer
    waiting for a person.

    A day later she is asked whether it was solved - unless she has already
    said *No* twice, in which case it is closed without asking again.
    """
    # Imported here: chats builds on the services this module is part of.
    from app.modules.inbox.services.chats import NotFound, Refused

    survey = db.scalar(
        select(FeedbackSurvey).where(FeedbackSurvey.id == survey_id).with_for_update()
    )
    if survey is None:
        raise NotFound("No such feedback.")
    if survey.rating != "unhappy" or survey.step != "support":
        raise Refused("Only an unhappy answer waiting for follow-up can be resolved.")

    now = now or utcnow()
    before = {"step": survey.step, "reopened": survey.reopened_count}
    survey.resolved_at = now
    survey.resolved_by = user.id
    survey.updated_at = now
    if survey.reopened_count >= MAX_REOPENS:
        survey.step = "done"
    else:
        survey.step = "solved"
        enqueue(
            db,
            JobKind.INBOX_FEEDBACK_ASK_SOLVED,
            {"survey_id": survey.id},
            run_after=now + (ASK_SOLVED_AFTER_TEST if survey.is_test else ASK_SOLVED_AFTER),
            # The reopen count is in the key: the second round is its own job.
            dedupe_key=f"{JobKind.INBOX_FEEDBACK_ASK_SOLVED}:{survey.id}:{survey.reopened_count}",
        )
    db.flush()
    record_audit(
        db,
        action="inbox.feedback_resolved",
        subject=f"feedback:{survey.id}",
        actor_id=user.id,
        actor_email=getattr(user, "email", None),
        before=before,
        after={"step": survey.step, "order": survey.order_name},
    )
    db.flush()
    names = feedback._names(db, [survey])
    return feedback.describe(survey, names.get(survey.resolved_by))


#: What a survey says when the solved question may or may not have gone out.
INTERRUPTED_ASKING = (
    "Interrupted while asking whether the issue was solved. Check the chat in "
    "WhatsApp before asking again: the question may have gone out."
)
COULD_NOT_ASK = "The question \"Was your issue solved?\" could not be sent: {why}"


def _asked_reference(survey: FeedbackSurvey) -> str:
    """One per press of *Resolved*: the survey and the second it was pressed."""
    return f"fbq:{survey.id}:{int(survey.resolved_at.timestamp())}"


def _claim_asked(survey_id: int) -> bool:
    """Take the solved question for sending, in a transaction of its own.

    Committed before WhatsApp is asked: whatever happens next - a crash after
    WhatsApp accepted it, a lost lease, a second worker - the question counts
    as asked and nobody sends it a second time. A template is billed.
    """
    from app.db import SessionLocal

    with SessionLocal() as own:
        claimed = own.execute(
            update(FeedbackSurvey)
            .where(
                FeedbackSurvey.id == survey_id,
                FeedbackSurvey.step == "solved",
                FeedbackSurvey.solved_asked_at.is_(None),
            )
            .values(solved_asked_at=utcnow(), updated_at=utcnow())
        ).rowcount
        own.commit()
    return claimed == 1


def _release_asked(survey_id: int) -> None:
    """Give the claim back, in a transaction of its own, because nothing went
    out and the job is to be tried again."""
    from app.db import SessionLocal

    with SessionLocal() as own:
        own.execute(
            update(FeedbackSurvey)
            .where(FeedbackSurvey.id == survey_id, FeedbackSurvey.step == "solved")
            .values(solved_asked_at=None, updated_at=utcnow())
        )
        own.commit()


def back_to_support(survey: FeedbackSurvey, why: str, now: datetime | None = None) -> None:
    """The solved question cannot be (or may not have been) sent, so a person
    has it again: the survey returns to step ``support`` - listed under needs
    follow-up - with the reason in ``last_error``. Nothing is counted as a
    reopening: she has not said *No*."""
    now = now or utcnow()
    survey.step = "support"
    survey.resolved_at = None
    survey.resolved_by = None
    survey.solved_asked_at = None
    survey.last_error = why[:300]
    survey.updated_at = now


def ask_solved(
    db: Session,
    survey_id: int,
    *,
    client: MetaClient | None = None,
    now: datetime | None = None,
    claim: Callable[[int], bool] = _claim_asked,
    release: Callable[[int], None] = _release_asked,
) -> FeedbackSurvey | None:
    """Ask *Was your issue solved?* once per *Resolved*: as buttons in the
    chat if her 24 hours are open, otherwise as the approved message.

    **Claimed before WhatsApp is asked** (``solved_asked_at``, committed in a
    session of its own), so a crash after WhatsApp took the message can never
    send it twice. **``solved_asked_at`` stays set only if the message really
    went out.** Whenever it did not, a person must be able to see her, so:

    - a *retryable* Meta error (WhatsApp did not answer): the claim is given
      back and the error raised, so the job is tried again;
    - a refusal (sending off, this server may not message her, keys
      unreadable) or a refusal from WhatsApp that will not change (no
      WhatsApp on that number, template paused): the survey returns to step
      ``support`` with the reason in ``last_error`` (``back_to_support``);
    - a crash: the claim stands and no message is in the chat; the sweep
      returns the survey to ``support`` marked interrupted
      (``recover_interrupted_solved``), and it is not asked again on its own.
    """
    survey = db.get(FeedbackSurvey, survey_id)
    if (
        survey is None
        or survey.step != "solved"
        or survey.solved_asked_at is not None
        or not survey.phone
        or survey.resolved_at is None
    ):
        return survey
    now = now or utcnow()
    if (why := sending.refusal(db, survey.phone)) is not None:
        back_to_support(survey, COULD_NOT_ASK.format(why=why), now)
        return survey

    conversation = (
        db.get(InboxConversation, survey.conversation_id) if survey.conversation_id else None
    ) or _conversation(db, survey.phone, None)
    reference = _asked_reference(survey)
    already = db.scalar(
        select(InboxMessage.status).where(InboxMessage.source_ref == reference)
    )
    if already is not None:
        # Asked already; only the survey's note of it was lost.
        if already != "failed":
            survey.solved_asked_at = now
        return survey

    cfg = get_settings(db)
    choices = [
        {
            "id": f"fbs_{key}_{survey.id}",
            "title": feedback_messages.text(cfg, f"solved_option.{key}"),
        }
        for key in feedback.SOLVED_ANSWERS
    ]
    if not claim(survey.id):
        return survey
    # What the claim committed, as this session sees it.
    set_committed_value(survey, "solved_asked_at", now)
    try:
        if outbound.window_open(conversation, now):
            message = send_buttons(
                db, conversation,
                feedback_messages.text(
                    cfg, "solved_question", name=feedback_messages.first_name(survey)
                ),
                choices,
                origin="automatic", source_ref=reference, client=client,
            )
        else:
            message = _send_solved_template(db, survey, conversation, choices, reference, client)
    except MetaError:
        release(survey.id)
        set_committed_value(survey, "solved_asked_at", None)
        raise
    except NotSent as exc:
        back_to_support(survey, COULD_NOT_ASK.format(why=exc), now)
        return survey
    if message.status == "failed":
        back_to_support(
            survey, COULD_NOT_ASK.format(why=message.error or "WhatsApp refused it"), now
        )
    else:
        survey.updated_at = now
    return survey


def recover_interrupted_solved(db: Session, now: datetime | None = None) -> int:
    """Surveys whose solved question was claimed, with no message to show for
    it ten minutes later, go back to a person marked interrupted - never asked
    again on their own, because the platform cannot know whether it went out."""
    now = now or utcnow()
    reference = func.concat(
        "fbq:", FeedbackSurvey.id, ":",
        cast(func.floor(func.extract("epoch", FeedbackSurvey.resolved_at)), BigInteger),
    )
    stuck = list(
        db.scalars(
            select(FeedbackSurvey).where(
                FeedbackSurvey.is_test.is_(False),
                FeedbackSurvey.step == "solved",
                FeedbackSurvey.solved_asked_at.is_not(None),
                FeedbackSurvey.solved_asked_at < now - outbound.INTERRUPTED_AFTER,
                ~exists().where(InboxMessage.source_ref == reference),
            )
        )
    )
    for survey in stuck:
        back_to_support(survey, INTERRUPTED_ASKING, now)
    return len(stuck)


def _send_solved_template(
    db: Session,
    survey: FeedbackSurvey,
    conversation: InboxConversation,
    choices: list[dict[str, str]],
    reference: str,
    client: MetaClient | None,
) -> InboxMessage:
    """The second approved message, for a customer whose 24 hours have closed.
    Returns the message as recorded in the chat (``failed`` if WhatsApp refused
    it for good); a refusal worth retrying is raised."""
    components: list[dict[str, Any]] = [
        {"type": "body", "parameters": [{"type": "text", "text": survey.order_name or ""}]}
    ]
    for index, choice in enumerate(choices):
        components.append(
            {
                "type": "button",
                "sub_type": "quick_reply",
                "index": str(index),
                "parameters": [{"type": "payload", "payload": choice["id"]}],
            }
        )
    owned = client is None
    client = client or outbound._client(db)
    try:
        wa_message_id = client.send_template(
            conversation.phone, feedback.SOLVED_TEMPLATE, feedback.SOLVED_LANGUAGE, components
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
        body=feedback.SOLVED_CHAT.format(order=survey.order_name or survey.shopify_order_id),
        origin="automatic",
        status=status,
        wa_message_id=wa_message_id,
        error=error,
        template_name=feedback.SOLVED_TEMPLATE,
        # The approved message's own buttons, whatever the chat's say.
        extra={"buttons": list(feedback_messages.SOLVED_TEMPLATE_BUTTONS)},
        order_id=survey.shopify_order_id,
        source_ref=reference,
    )


@register_handler(JobKind.INBOX_FEEDBACK_REPLY)
def _handle_reply(db: Session, payload: dict) -> None:
    message_id = payload.get("message_id")
    if not isinstance(message_id, int):
        raise PermanentFailure(
            f"{JobKind.INBOX_FEEDBACK_REPLY} requires a message_id; got payload keys "
            f"{sorted(payload)!r}"
        )
    # Off, only an administrator's test is answered (``feedback.send_test``).
    if not feedback.enabled() and not _is_test_tap(db, message_id):
        return
    reply(db, message_id, final_attempt=_final_code_attempt(db, message_id))


def _is_test_tap(db: Session, message_id: int) -> bool:
    """Whether this tap answers an administrator's test survey."""
    order_id = db.scalar(select(InboxMessage.shopify_order_id).where(InboxMessage.id == message_id))
    if not order_id:
        return False
    return bool(
        db.scalar(
            select(FeedbackSurvey.is_test).where(FeedbackSurvey.shopify_order_id == order_id)
        )
    )


def _final_code_attempt(db: Session, message_id: int) -> bool:
    """Whether this is the reply job's last try at her reward code.

    The job's own count of failed tries is the only thing that survives a
    failed run (the run's own writes are rolled back), so it is read from the
    job's row: its key is this tap's. Not found (run by hand, in a test) is
    the last try - nobody is coming back to try again.
    """
    failed = db.scalar(
        select(BackgroundJob.attempts).where(
            BackgroundJob.kind == JobKind.INBOX_FEEDBACK_REPLY,
            BackgroundJob.dedupe_key == f"{JobKind.INBOX_FEEDBACK_REPLY}:{message_id}",
            BackgroundJob.status == JobStatus.RUNNING,
        )
    )
    return failed is None or failed + 1 >= feedback_codes.CODE_ATTEMPTS


@register_handler(JobKind.INBOX_FEEDBACK_ASK_SOLVED)
def _handle_ask_solved(db: Session, payload: dict) -> None:
    survey_id = payload.get("survey_id")
    if not isinstance(survey_id, int):
        raise PermanentFailure(
            f"{JobKind.INBOX_FEEDBACK_ASK_SOLVED} requires a survey_id; got payload keys "
            f"{sorted(payload)!r}"
        )
    if not feedback.enabled() and not feedback.is_test_survey(db, survey_id):
        # Nothing is sent with the feature off (a test aside), and she must
        # not be left where nobody can see her: a person has her again.
        survey = db.get(FeedbackSurvey, survey_id)
        if survey is not None and survey.step == "solved" and survey.solved_asked_at is None:
            back_to_support(survey, COULD_NOT_ASK.format(why="feedback is switched off."))
        return
    ask_solved(db, survey_id)
