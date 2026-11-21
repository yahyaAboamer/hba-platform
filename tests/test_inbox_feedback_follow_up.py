"""The follow-up an unhappy answer is owed, as a record (ADR 0087): every call
with no answer, every note, *Resolved* with what was agreed, *Couldn't reach*,
and the WhatsApp message after the second unanswered call.

What is sent goes to a mock transport. Every number, name and order is made up.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.businesstime import utcnow
from app.modules.inbox.models import FeedbackFollowUp, FeedbackSurvey, InboxMessage
from app.modules.inbox.services import chats, feedback, feedback_follow_up, feedback_replies, outbound
from app.modules.inbox.services.events import apply_event
from app.shared.models.audit import AuditEvent
from app.shared.models.identity import UserAccount
from app.shared.services.jobs import JobKind, PermanentFailure
from tests.feedback_support import (  # noqa: F401  (fixtures)
    HER,
    NUMBER_ID,
    connected,
    conversation,
    feature_on,
    jobs,
    may_send,
    message,
    meta,
    survey,
)


# ── The record ────────────────────────────────────────────────────────────────


def test_the_follow_up_table_holds_an_entry(db):
    s = survey(db, rating="unhappy", step="support")

    db.add(FeedbackFollowUp(survey_id=s.id, round=0, kind="no_answer", note=None))
    db.flush()

    entry = db.scalar(select(FeedbackFollowUp).where(FeedbackFollowUp.survey_id == s.id))
    assert (entry.round, entry.kind, entry.note, entry.actor_id) == (0, "no_answer", None, None)
    assert entry.at is not None


def test_an_unknown_kind_is_refused(db):
    s = survey(db, rating="unhappy", step="support")

    db.add(FeedbackFollowUp(survey_id=s.id, round=0, kind="call"))
    with pytest.raises(IntegrityError):
        db.flush()


# ── What a person records ─────────────────────────────────────────────────────


@pytest.fixture()
def staff(db) -> UserAccount:
    user = UserAccount(email="mariam@example.com", password_hash="x", status="active", display_name="Mariam")
    db.add(user)
    db.flush()
    return user


def _open(db, **changes) -> FeedbackSurvey:
    """An unhappy answer waiting for a person, in round 0."""
    values = {
        "rating": "unhappy", "rated_at": utcnow() - timedelta(hours=3),
        "reason": "delivery", "reason_at": utcnow() - timedelta(hours=3),
        "step": "support", "round_started_at": utcnow() - timedelta(hours=3),
    }
    values.update(changes)
    return survey(db, **values)


def _entries(db, row) -> list[FeedbackFollowUp]:
    return list(
        db.scalars(
            select(FeedbackFollowUp)
            .where(FeedbackFollowUp.survey_id == row.id)
            .order_by(FeedbackFollowUp.at, FeedbackFollowUp.id)
        )
    )


def _kinds(db, row) -> list[str]:
    return [entry.kind for entry in _entries(db, row)]


def _refused(call, *args, **kwargs) -> str:
    with pytest.raises(chats.Refused) as refused:
        call(*args, **kwargs)
    return str(refused.value)


TRIED = JobKind.INBOX_FEEDBACK_TRIED_TO_CALL
OPEN_ONLY = "Only a follow-up that is still open can be updated."


def test_no_answer_keeps_it_open_and_records_who(db, staff):
    row = _open(db)

    feedback_follow_up.no_answer(db, row.id, staff, " Phone off ")

    assert row.step == "support"
    [entry] = _entries(db, row)
    assert (entry.kind, entry.note, entry.actor_id, entry.round) == ("no_answer", "Phone off", staff.id, 0)
    assert jobs(db, TRIED) == []
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "inbox.feedback_no_answer"))
    assert (event.actor_id, event.after_json["count"], event.after_json["closed"]) == (staff.id, 1, False)


def test_the_second_no_answer_queues_one_message(db, staff):
    row = _open(db)

    feedback_follow_up.no_answer(db, row.id, staff, None)
    feedback_follow_up.no_answer(db, row.id, staff, "")
    assert [(key, payload) for _, key, payload in jobs(db, TRIED)] == [
        (f"{TRIED}:{row.id}:0", {"survey_id": row.id})
    ]
    feedback_follow_up.no_answer(db, row.id, staff, None)

    assert len(jobs(db, TRIED)) == 1
    assert feedback_follow_up.no_answer_count(db, row) == 3


def test_couldnt_reach_only_from_the_third_call(db, staff):
    row = _open(db)
    feedback_follow_up.no_answer(db, row.id, staff, None)

    words = _refused(feedback_follow_up.no_answer, db, row.id, staff, "No answer again", close=True)

    assert words == "It can be closed as couldn't reach from the third call with no answer."
    assert _kinds(db, row) == ["no_answer"] and row.step == "support"

    feedback_follow_up.no_answer(db, row.id, staff, None)
    feedback_follow_up.no_answer(db, row.id, staff, "Third try", close=True)

    assert row.step == "done" and row.unreached_at is not None and row.unreached_by == staff.id
    assert _kinds(db, row)[-2:] == ["no_answer", "unreached"]
    assert jobs(db, JobKind.INBOX_FEEDBACK_ASK_SOLVED) == []
    assert row.resolved_at is None


def test_resolve_needs_a_note(db, staff):
    row = _open(db)

    words = _refused(feedback_replies.resolve, db, row.id, staff, "  ")

    assert words == "Write what you agreed with her before resolving."
    assert row.step == "support" and _entries(db, row) == []

    feedback_replies.resolve(db, row.id, staff, "Exchange to L")

    assert row.step == "solved"
    [entry] = _entries(db, row)
    assert (entry.kind, entry.note, entry.actor_id) == ("resolved", "Exchange to L", staff.id)


def test_an_action_on_a_closed_follow_up_is_refused(db, staff):
    row = _open(db)
    feedback_replies.resolve(db, row.id, staff, "Refund agreed")

    assert _refused(feedback_follow_up.no_answer, db, row.id, staff, None) == OPEN_ONLY
    assert _refused(feedback_follow_up.add_note, db, row.id, staff, "Called again") == OPEN_ONLY
    assert _kinds(db, row) == ["resolved"]
    with pytest.raises(chats.NotFound):
        feedback_follow_up.add_note(db, 987654, staff, "Nobody")


def test_a_note_over_1000_characters_is_refused(db, staff):
    row = _open(db)

    words = _refused(feedback_follow_up.add_note, db, row.id, staff, "x" * 1001)

    assert words == "A note can be at most 1,000 characters."
    assert _entries(db, row) == []
    # Exactly 1,000 once trimmed is fine, and kept as typed, newlines and all.
    long = "  " + "سطر\n" * 249 + "سطري  "
    assert len(long.strip()) == 1000
    feedback_follow_up.add_note(db, row.id, staff, long)
    assert _entries(db, row)[0].note == long.strip()


def test_add_note_needs_words(db, staff):
    row = _open(db)

    assert _refused(feedback_follow_up.add_note, db, row.id, staff, " \n ") == "Write the note first."

    feedback_follow_up.add_note(db, row.id, staff, "Spoke to her, waiting on finance")
    assert row.step == "support"
    [entry] = _entries(db, row)
    assert (entry.kind, entry.note) == ("note", "Spoke to her, waiting on finance")
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "inbox.feedback_note")) is not None
    assert jobs(db, TRIED) == []


# ── Rounds ────────────────────────────────────────────────────────────────────


def test_a_reason_tap_starts_round_0(db):
    chat = conversation(db)
    row = survey(db, rating="unhappy", rated_at=utcnow(), step="reason", conversation_id=chat.id)
    at = utcnow()

    feedback_replies.record_tap(
        db, row, feedback_replies.Tap("reason", "delivery", str(row.id)), at, chat, message(db, chat).id
    )

    assert (row.step, row.follow_up_round, row.round_started_at) == ("support", 0, at)


def test_she_says_not_solved_starts_a_new_round(db, staff):
    chat = conversation(db)
    row = _open(db, conversation_id=chat.id)
    feedback_follow_up.no_answer(db, row.id, staff, None)
    feedback_replies.resolve(db, row.id, staff, "Exchange agreed")
    tapped = utcnow()

    feedback_replies.record_tap(
        db, row, feedback_replies.Tap("solved", "no", str(row.id)), tapped, chat, message(db, chat).id
    )

    assert (row.step, row.follow_up_round, row.round_started_at) == ("support", 1, tapped)
    assert row.reopened_count == 1
    assert feedback_follow_up.no_answer_count(db, row) == 0
    feedback_follow_up.no_answer(db, row.id, staff, None)
    feedback_follow_up.no_answer(db, row.id, staff, None)
    assert [key for _, key, _ in jobs(db, TRIED)] == [f"{TRIED}:{row.id}:1"]
    assert [entry.round for entry in _entries(db, row)] == [0, 0, 1, 1]


def test_back_to_support_writes_returned(db, staff):
    row = _open(db)
    feedback_replies.resolve(db, row.id, staff, "Exchange agreed")
    assert row.step == "solved"

    feedback_replies.back_to_support(row, "why")
    db.flush()

    assert row.step == "support"
    last = _entries(db, row)[-1]
    assert (last.kind, last.note, last.round, last.actor_id) == ("returned", "why", 0, None)


# ── She writes back after Couldn't reach ──────────────────────────────────────


def _unreached(db, staff, at, **changes) -> FeedbackSurvey:
    row = _open(db, **changes)
    for _ in range(2):
        feedback_follow_up.no_answer(db, row.id, staff, None, now=at)
    feedback_follow_up.no_answer(db, row.id, staff, None, close=True, now=at)
    assert row.step == "done"
    return row


def test_a_typed_message_reopens_couldnt_reach_within_14_days(db, staff):
    row = _unreached(db, staff, utcnow() - timedelta(days=13))
    wrote = utcnow()

    assert feedback_follow_up.reopen_if_unreached(db, HER, wrote) is True

    assert (row.step, row.unreached_at, row.unreached_by) == ("support", None, None)
    assert (row.follow_up_round, row.round_started_at) == (1, wrote)
    last = _entries(db, row)[-1]
    assert (last.kind, last.actor_id, last.round) == ("wrote_back", None, 1)
    # The close is still in the history.
    assert "unreached" in _kinds(db, row)
    assert feedback_follow_up.no_answer_count(db, row) == 0


def test_day_15_or_a_tap_does_not_reopen(db, staff):
    row = _unreached(db, staff, utcnow() - timedelta(days=15))

    assert feedback_follow_up.reopen_if_unreached(db, HER, utcnow()) is False
    assert row.step == "done"


def test_only_the_most_recent_unreached_survey_reopens(db, staff):
    older = _unreached(db, staff, utcnow() - timedelta(days=10))
    newer = _unreached(db, staff, utcnow() - timedelta(days=2), order_id="7002")

    assert feedback_follow_up.reopen_if_unreached(db, HER, utcnow()) is True

    assert (newer.step, older.step) == ("support", "done")


def _callback(message: dict) -> dict:
    value = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "201005550100", "phone_number_id": NUMBER_ID},
        "contacts": [{"profile": {"name": "Nour Adel"}, "wa_id": HER}],
        "messages": [message],
    }
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"field": "messages", "value": value}]}],
    }


def _now() -> str:
    return str(int(utcnow().timestamp()))


def test_her_typed_message_reopens_it_and_a_tap_does_not(db, connected, staff):
    row = _unreached(db, staff, utcnow() - timedelta(days=3))

    apply_event(db, _callback({
        "from": HER, "id": "wamid.TAP", "timestamp": _now(), "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": {"id": f"fbs_no_{row.id}", "title": "No"}},
    }))
    db.flush()
    assert row.step == "done"

    apply_event(db, _callback({
        "from": HER, "id": "wamid.TEXT", "timestamp": _now(), "type": "text",
        "text": {"body": "Sorry, I was at work. Call me after 6"},
    }))
    db.flush()
    db.refresh(row)
    assert row.step == "support" and _kinds(db, row)[-1] == "wrote_back"


# ── "We tried to call you" ────────────────────────────────────────────────────


def _after_two_calls(db, staff, chat) -> FeedbackSurvey:
    row = _open(db, conversation_id=chat.id)
    feedback_follow_up.no_answer(db, row.id, staff, None)
    feedback_follow_up.no_answer(db, row.id, staff, None)
    return row


def _sent_words(asked) -> list[str]:
    return [m["text"]["body"] for m in asked if m["type"] == "text"]


def test_the_message_goes_as_chat_while_her_24_hours_are_open(db, may_send, staff):
    chat = conversation(db, wrote_ago=timedelta(hours=1))
    row = _after_two_calls(db, staff, chat)
    asked: list = []

    feedback_follow_up.send_tried_to_call(db, row.id, client=meta(asked))

    words = "We tried to call you about your order #7001. Reply here or tell us a good time to call."
    assert _sent_words(asked) == [words]
    last = _entries(db, row)[-1]
    assert (last.kind, last.note, last.actor_id) == ("message_sent", words, None)
    sent = db.scalar(select(InboxMessage).where(InboxMessage.source_ref == f"fbt:{row.id}:0"))
    assert (sent.kind, sent.status, sent.origin) == ("text", "sent", "automatic")
    assert row.step == "support"


def test_the_template_goes_once_her_24_hours_closed(db, may_send, staff):
    chat = conversation(db, wrote_ago=timedelta(hours=30))
    row = _after_two_calls(db, staff, chat)
    asked: list = []

    feedback_follow_up.send_tried_to_call(db, row.id, client=meta(asked))

    [body] = asked
    assert body["type"] == "template"
    assert (body["template"]["name"], body["template"]["language"]["code"]) == ("feedback_tried_to_call", "en")
    assert body["template"]["components"] == [
        {"type": "body", "parameters": [{"type": "text", "text": "#7001"}]}
    ]
    sent = db.scalar(select(InboxMessage).where(InboxMessage.source_ref == f"fbt:{row.id}:0"))
    assert (sent.kind, sent.template_name, sent.shopify_order_id) == ("template", "feedback_tried_to_call", "7001")
    assert sent.body == feedback.TRIED_CHAT.format(order="#7001")
    assert _entries(db, row)[-1].kind == "message_sent"


def test_the_window_is_checked_when_sending(db, may_send, feature_on, staff, monkeypatch):
    chat = conversation(db, wrote_ago=timedelta(hours=1))
    row = _after_two_calls(db, staff, chat)
    [(_, _, payload)] = jobs(db, TRIED)
    # Her 24 hours close before the job runs.
    chat.last_inbound_at = utcnow() - timedelta(hours=25)
    db.flush()
    asked: list = []
    monkeypatch.setattr(outbound, "_client", lambda _db: meta(asked))

    feedback_follow_up._handle_tried_to_call(db, payload)

    assert [m["type"] for m in asked] == ["template"]


def test_running_twice_sends_once(db, may_send, staff):
    chat = conversation(db, wrote_ago=timedelta(hours=1))
    row = _after_two_calls(db, staff, chat)
    asked: list = []

    feedback_follow_up.send_tried_to_call(db, row.id, client=meta(asked))
    feedback_follow_up.send_tried_to_call(db, row.id, client=meta(asked))

    assert len(asked) == 1
    assert _kinds(db, row).count("message_sent") == 1


def test_a_message_already_in_the_chat_is_not_sent_again(db, may_send, staff):
    """Sent, but the history's line of it was lost: only the line is added."""
    chat = conversation(db, wrote_ago=timedelta(hours=1))
    row = _after_two_calls(db, staff, chat)
    outbound.record_outbound(
        db, chat, kind="text", body="We tried to call you", origin="automatic",
        status="sent", source_ref=f"fbt:{row.id}:0",
    )
    asked: list = []

    feedback_follow_up.send_tried_to_call(db, row.id, client=meta(asked))

    assert asked == []
    assert _kinds(db, row)[-1] == "message_sent"


def test_a_template_meta_refuses_tells_the_team(db, may_send, staff):
    chat = conversation(db, wrote_ago=timedelta(hours=30))
    row = _after_two_calls(db, staff, chat)
    asked: list = []

    # Not approved yet: Meta refuses it, and asking again would not help.
    feedback_follow_up.send_tried_to_call(db, row.id, client=meta(asked, refuse=(404, 132001)))

    last = _entries(db, row)[-1]
    assert last.kind == "message_failed"
    assert last.note.startswith("Couldn't send the WhatsApp message:")
    assert last.note.endswith("Write to her yourself.")
    assert row.step == "support"


def test_sending_off_tells_the_team(db, connected, staff):
    chat = conversation(db, wrote_ago=timedelta(hours=1))
    row = _after_two_calls(db, staff, chat)
    asked: list = []

    feedback_follow_up.send_tried_to_call(db, row.id, client=meta(asked))

    assert asked == []
    last = _entries(db, row)[-1]
    assert (last.kind, last.note) == (
        "message_failed",
        "Couldn't send the WhatsApp message: Sending is turned off in Settings. Write to her yourself.",
    )


def test_feature_off_sends_nothing(db, may_send, staff, monkeypatch):
    chat = conversation(db, wrote_ago=timedelta(hours=1))
    row = _after_two_calls(db, staff, chat)
    asked: list = []
    monkeypatch.setattr(outbound, "_client", lambda _db: meta(asked))

    feedback_follow_up._handle_tried_to_call(db, {"survey_id": row.id})

    assert asked == []
    last = _entries(db, row)[-1]
    assert (last.kind, last.note) == (
        "message_failed",
        "Couldn't send the WhatsApp message: feedback is switched off. Write to her yourself.",
    )


def test_resolved_before_the_job_ran_sends_nothing(db, may_send, feature_on, staff):
    chat = conversation(db, wrote_ago=timedelta(hours=1))
    row = _after_two_calls(db, staff, chat)
    feedback_replies.resolve(db, row.id, staff, "She answered the third time")
    asked: list = []

    feedback_follow_up.send_tried_to_call(db, row.id, client=meta(asked))

    assert asked == []
    assert _kinds(db, row)[-1] == "resolved"


def test_the_job_needs_a_survey(db):
    with pytest.raises(PermanentFailure):
        feedback_follow_up._handle_tried_to_call(db, {})
