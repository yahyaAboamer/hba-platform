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
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.modules.inbox.models import FeedbackFollowUp, FeedbackSurvey
from app.shared.services.audit import record_audit
from app.shared.services.jobs import JobKind, enqueue

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
