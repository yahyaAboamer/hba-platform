"""Post-delivery feedback, the second half (ADR 0083): her taps, the questions
that follow, her comment, the person who follows up, and the solved question.

Callbacks are in the shape Meta sends them, applied through ``apply_event``;
what is sent goes to a mock transport. Every number, name and order is made up.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text as sql_text

from app.core.businesstime import utcnow
from app.modules.inbox.models import (
    FeedbackSurvey,
    InboxConversation,
    InboxMessage,
    OrderConfirmation,
)
from app.modules.inbox.services import chats, feedback, feedback_replies, outbound
from app.modules.inbox.services.meta import MetaError
from app.modules.inbox.services.events import _read_message, apply_event
from app.shared.models.audit import AuditEvent
from app.shared.models.identity import UserAccount
from app.shared.services.jobs import JobKind
from tests.feedback_support import (  # noqa: F401  (fixtures)
    HER,
    NUMBER_ID,
    connected,
    conversation,
    jobs,
    may_send,
    meta,
    survey,
)

STRANGER = "201112223344"


def _at(ago: timedelta = timedelta(0)) -> str:
    return str(int((utcnow() - ago).timestamp()))


def _callback(messages: list[dict]) -> dict:
    value = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "201005550100", "phone_number_id": NUMBER_ID},
        "contacts": [{"profile": {"name": "Nour Adel"}, "wa_id": HER}],
        "messages": messages,
    }
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"field": "messages", "value": value}]}],
    }


def template_tap(payload, title, wamid, *, ago=timedelta(seconds=30), sender=HER) -> dict:
    """A tap on one of a template's quick-reply buttons."""
    return {
        "from": sender, "id": wamid, "timestamp": _at(ago), "type": "button",
        "button": {"payload": payload, "text": title},
        "context": {"from": "201005550100", "id": "wamid.OURS"},
    }


def interactive_tap(kind, choice_id, title, wamid, *, ago=timedelta(seconds=30), sender=HER) -> dict:
    """A tap on a reply button (``button_reply``) or a list row (``list_reply``) of ours."""
    return {
        "from": sender, "id": wamid, "timestamp": _at(ago), "type": "interactive",
        "interactive": {"type": kind, kind: {"id": choice_id, "title": title}},
    }


def text(body, wamid, *, ago=timedelta(seconds=10), sender=HER) -> dict:
    return {"from": sender, "id": wamid, "timestamp": _at(ago), "type": "text", "text": {"body": body}}


def apply(db, *messages) -> None:
    apply_event(db, _callback(list(messages)))
    db.flush()


def drain(db, client) -> None:
    """Run every queued reply, as the worker would. Running one twice is
    harmless by design, so this also leaves the idempotency to be proved."""
    for _, _, payload in jobs(db, JobKind.INBOX_FEEDBACK_REPLY):
        feedback_replies.reply(db, payload["message_id"], client)
    db.flush()


def _staff(db) -> UserAccount:
    user = UserAccount(email="mariam@example.com", password_hash="x", status="active", display_name="Mariam")
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def world(db, may_send):
    """A survey whose first question went out, her chat, and a recording Meta."""
    chat = conversation(db, wrote_ago=timedelta(days=2))
    row = survey(db, conversation_id=chat.id)
    asked: list = []
    return SimpleNamespace(row=row, chat=chat, asked=asked, client=meta(asked), staff=_staff(db))


def _bodies(asked) -> list[str]:
    return [
        (m.get("text") or m["interactive"])["body"]
        if m["type"] == "text"
        else m["interactive"]["body"]["text"]
        for m in asked
        if m["type"] in ("text", "interactive")
    ]


def _rated(world, db, rating="loved", reason=None):
    """Take the survey through the first tap, and her reason if given."""
    apply(db, template_tap(f"fb_{rating}_7001", "x", "wamid.T1", ago=timedelta(seconds=50)))
    drain(db, world.client)
    if reason:
        apply(
            db,
            interactive_tap("list_reply", f"fbr_{reason}_{world.row.id}", "x", "wamid.T2", ago=timedelta(seconds=40)),
        )
        drain(db, world.client)


# ── What arrives ──────────────────────────────────────────────────────────────


def test_a_list_choice_is_read_as_a_tap_with_its_id_and_title():
    fields = _read_message(interactive_tap("list_reply", "fbr_quality_9", "Quality", "wamid.X"))
    assert (fields["kind"], fields["body"], fields["extra"]) == (
        "button", "Quality", {"payload": "fbr_quality_9"},
    )


def test_a_reply_button_is_still_read_as_a_tap():
    fields = _read_message(interactive_tap("button_reply", "fbs_yes_9", "Yes", "wamid.X"))
    assert (fields["kind"], fields["body"], fields["extra"]) == ("button", "Yes", {"payload": "fbs_yes_9"})


def test_a_list_choice_is_stored_in_the_chat_as_what_she_chose(db, world):
    apply(db, template_tap("fb_loved_7001", "Loved it", "wamid.T1"))
    apply(db, interactive_tap("list_reply", f"fbr_quality_{world.row.id}", "Quality", "wamid.T2"))
    stored = db.scalar(select(InboxMessage).where(InboxMessage.wa_message_id == "wamid.T2"))
    assert (stored.kind, stored.body, stored.direction) == ("button", "Quality", "in")
    assert stored.shopify_order_id == "7001"
    assert world.chat.last_preview == "Quality"


# ── A tap counts only if it is hers and expected ──────────────────────────────


def test_a_tap_from_another_phone_changes_nothing(db, world):
    apply(db, template_tap("fb_unhappy_7001", "Not happy", "wamid.EVIL", sender=STRANGER))
    assert (world.row.rating, world.row.step, world.row.state) == (None, "rating", "sent")
    stored = db.scalar(select(InboxMessage).where(InboxMessage.wa_message_id == "wamid.EVIL"))
    assert stored.extra == {"payload": "fb_unhappy_7001", "unmatched": True}
    assert stored.shopify_order_id is None
    assert jobs(db, JobKind.INBOX_FEEDBACK_REPLY) == []


def test_a_tap_on_a_survey_that_is_not_there_changes_nothing(db, world):
    apply(db, template_tap("fb_loved_9999", "Loved it", "wamid.T1"))
    apply(db, interactive_tap("list_reply", "fbr_quality_999999", "Quality", "wamid.T2"))
    assert world.row.rating is None
    assert jobs(db, JobKind.INBOX_FEEDBACK_REPLY) == []


@pytest.mark.parametrize(
    ("step", "payload"),
    [
        ("rating", "fbr_quality_{id}"),     # a reason before a rating
        ("rating", "fbs_yes_{id}"),         # solved before it was asked
        ("rating", "fbo_maybe_{id}"),
        ("reason", "fb_unhappy_7001"),      # a rating again
        ("reason", "fbs_no_{id}"),
        ("reason", "fbr_price_{id}"),       # not one of a loved customer's reasons
        ("comment", "fbr_quality_{id}"),
        ("support", "fbo_maybe_{id}"),
        ("done", "fb_loved_7001"),
        ("done", "fbo_maybe_{id}"),
    ],
)
def test_a_tap_for_a_step_the_survey_is_not_on_changes_nothing(db, world, step, payload):
    world.row.step = step
    world.row.rating = None if step == "rating" else "loved"
    db.flush()
    before = (world.row.rating, world.row.reason, world.row.reorder, world.row.solved, world.row.step)

    apply(db, template_tap(payload.format(id=world.row.id), "x", "wamid.T1"))

    assert (world.row.rating, world.row.reason, world.row.reorder, world.row.solved, world.row.step) == before
    assert jobs(db, JobKind.INBOX_FEEDBACK_REPLY) == []
    assert db.scalar(select(InboxMessage.extra).where(InboxMessage.wa_message_id == "wamid.T1"))["unmatched"]


def test_a_solved_tap_is_not_taken_until_the_question_was_asked(db, world):
    world.row.rating, world.row.step, world.row.solved_asked_at = "unhappy", "solved", None
    db.flush()
    apply(db, template_tap(f"fbs_yes_{world.row.id}", "Yes", "wamid.T1"))
    assert (world.row.solved, world.row.step) == (None, "solved")


def test_a_skipped_order_is_never_answered(db, may_send):
    skipped = survey(db, "7002", state="skipped", step="done", skip_reason="no_phone")
    apply(db, template_tap("fb_loved_7002", "Loved it", "wamid.T1"))
    assert (skipped.rating, skipped.state) == (None, "skipped")


def test_a_repeated_tap_sends_no_second_follow_up(db, world):
    apply(db, template_tap("fb_loved_7001", "Loved it", "wamid.T1", ago=timedelta(seconds=40)))
    drain(db, world.client)
    # She taps it again from the old message, and Meta repeats the callback.
    apply(db, template_tap("fb_loved_7001", "Loved it", "wamid.T1b", ago=timedelta(seconds=20)))
    apply(db, template_tap("fb_loved_7001", "Loved it", "wamid.T1", ago=timedelta(seconds=40)))
    drain(db, world.client)
    drain(db, world.client)

    assert len(world.asked) == 1 and world.asked[0]["interactive"]["type"] == "list"
    assert len(jobs(db, JobKind.INBOX_FEEDBACK_REPLY)) == 1
    assert (world.row.rating, world.row.step) == ("loved", "reason")


def test_confirmation_taps_still_work_beside_feedback_taps(db, world):
    db.add(OrderConfirmation(shopify_order_id="5001", order_name="#5001", state="sent", phone=HER, customer_name="Nour"))
    db.flush()
    apply(db, template_tap("confirm_5001", "Confirm", "wamid.C1"))
    confirmation = db.scalar(select(OrderConfirmation))
    assert (confirmation.answer, confirmation.answered_in) == ("confirmed", "whatsapp")
    assert (world.row.rating, world.row.step) == (None, "rating")
    assert jobs(db, JobKind.INBOX_FEEDBACK_REPLY) == []

    apply(db, template_tap("fb_okay_7001", "It was okay", "wamid.F1"))
    assert world.row.rating == "okay"
    assert db.scalar(select(OrderConfirmation.answer)) == "confirmed"


def test_her_tap_proves_the_question_reached_her(db, world):
    for state in ("failed", "no_whatsapp", "would_send"):
        world.row.state, world.row.step, world.row.rating = state, "rating", None
        db.flush()
        apply(db, template_tap("fb_loved_7001", "Loved it", f"wamid.{state}"))
        assert world.row.state == "sent"


# ── The three paths ───────────────────────────────────────────────────────────


def test_the_loved_path(db, world):
    apply(db, template_tap("fb_loved_7001", "Loved it", "wamid.T1", ago=timedelta(seconds=50)))
    row = world.row
    assert (row.rating, row.step, row.conversation_id) == ("loved", "reason", world.chat.id)
    assert row.rated_at is not None

    drain(db, world.client)
    question = world.asked[0]["interactive"]
    assert question["type"] == "list" and question["body"]["text"] == "What did you like most?"
    assert [r["id"] for r in question["action"]["sections"][0]["rows"]] == [
        f"fbr_{key}_{row.id}" for key in ("quality", "fit", "design", "delivery", "other")
    ]
    asked_in_chat = db.scalar(select(InboxMessage).where(InboxMessage.source_ref == "fb:wamid.T1"))
    assert (asked_in_chat.kind, asked_in_chat.origin, asked_in_chat.status) == ("text", "automatic", "sent")
    assert asked_in_chat.extra["buttons"] == ["Quality", "Fit", "Design", "Delivery", "Something else"]

    apply(db, interactive_tap("list_reply", f"fbr_design_{row.id}", "Design", "wamid.T2", ago=timedelta(seconds=40)))
    assert (row.reason, row.step) == ("design", "comment")
    drain(db, world.client)
    closing = world.asked[1]["text"]["body"]
    assert closing == feedback_replies.closing_text(row, feedback.get_settings(db))
    assert "If there is anything we could do better, just reply here." in closing

    apply(db, text("The linen is beautiful, thank you", "wamid.T3"))
    assert (row.comment, row.step) == ("The linen is beautiful, thank you", "done")
    assert row.comment_at is not None
    stored = db.scalar(select(InboxMessage).where(InboxMessage.wa_message_id == "wamid.T3"))
    assert (stored.kind, stored.body, stored.direction) == ("text", "The linen is beautiful, thank you", "in")
    assert len(world.asked) == 2


def test_the_okay_path(db, world):
    _rated(world, db, "okay")
    question = world.asked[0]["interactive"]
    assert question["body"]["text"] == "What would have made it better?"
    assert [r["id"].split("_", 1)[1].rsplit("_", 1)[0] for r in question["action"]["sections"][0]["rows"]] == [
        "size_fit", "quality", "delivery", "packaging", "price", "other",
    ]
    apply(db, interactive_tap("list_reply", f"fbr_size_fit_{world.row.id}", "Size / fit", "wamid.T2", ago=timedelta(seconds=40)))
    assert (world.row.rating, world.row.reason, world.row.step) == ("okay", "size_fit", "comment")
    drain(db, world.client)
    assert "If there is anything we could do better" in world.asked[1]["text"]["body"]
    assert "A member of our team" not in world.asked[1]["text"]["body"]


def _unhappy_waiting_for_a_person(world, db):
    _rated(world, db, "unhappy", "wrong_item")
    return world.row


def test_the_unhappy_path_until_a_person_has_to_act(db, world):
    row = world.row
    apply(db, template_tap("fb_unhappy_7001", "Not happy", "wamid.T1", ago=timedelta(seconds=50)))
    drain(db, world.client)
    question = world.asked[0]["interactive"]
    assert question["body"]["text"] == "We're sorry about that. What went wrong?"
    assert [r["id"] for r in question["action"]["sections"][0]["rows"]] == [
        f"fbr_{key}_{row.id}" for key in ("size_fit", "quality", "wrong_item", "delivery", "other")
    ]

    apply(db, interactive_tap("list_reply", f"fbr_wrong_item_{row.id}", "Wrong item", "wamid.T2", ago=timedelta(seconds=40)))
    assert (row.reason, row.step) == ("wrong_item", "support")
    drain(db, world.client)
    assert world.asked[1]["text"]["body"] == (
        "We're sorry, Nour, and thank you for telling us. A member of our team will message "
        "you here within 24 hours to make it right."
    )

    apply(db, text("I got the black one, not the beige", "wamid.T3"))
    assert (row.comment, row.step) == ("I got the black one, not the beige", "support")

    listed = feedback.needs_follow_up(db)
    assert [(r["order_name"], r["reason"], r["comment"]) for r in listed] == [
        ("#7001", "wrong_item", "I got the black one, not the beige")
    ]
    assert len(world.asked) == 2


def test_the_promised_time_is_the_one_in_settings(db, world):
    feedback.get_settings(db).reply_hours = 48
    _unhappy_waiting_for_a_person(world, db)
    assert "within 48 hours" in world.asked[1]["text"]["body"]


# ── A person presses Resolved ─────────────────────────────────────────────────


def test_resolving_is_audited_and_asks_her_a_day_later(db, world):
    row = _unhappy_waiting_for_a_person(world, db)
    mariam = world.staff
    now = utcnow()

    described = feedback_replies.resolve(db, row.id, mariam, now)

    assert (row.step, row.resolved_by, row.resolved_at) == ("solved", mariam.id, now)
    assert described["resolved_by_name"] == "Mariam" and not described["needs_follow_up"]
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "inbox.feedback_resolved"))
    assert (event.department, event.actor_id, event.after_json["order"]) == ("inbox", mariam.id, "#7001")
    queued = jobs(db, JobKind.INBOX_FEEDBACK_ASK_SOLVED)
    assert [(key, payload) for _, key, payload in queued] == [
        (f"{JobKind.INBOX_FEEDBACK_ASK_SOLVED}:{row.id}:0", {"survey_id": row.id})
    ]
    run_after = db.scalar(
        sql_text("SELECT run_after FROM background_job WHERE kind = 'inbox_feedback_ask_solved'")
    )
    assert run_after == now + timedelta(hours=24)


def test_only_an_unhappy_answer_waiting_for_a_person_can_be_resolved(db, world):
    mariam = world.staff
    row = world.row
    with pytest.raises(chats.Refused):
        feedback_replies.resolve(db, row.id, mariam)  # not rated yet
    row.rating, row.step = "loved", "support"
    db.flush()
    with pytest.raises(chats.Refused):
        feedback_replies.resolve(db, row.id, mariam)  # not unhappy
    with pytest.raises(chats.NotFound):
        feedback_replies.resolve(db, 987654, mariam)
    row.rating = "unhappy"
    db.flush()
    feedback_replies.resolve(db, row.id, mariam)
    with pytest.raises(chats.Refused):
        feedback_replies.resolve(db, row.id, mariam)  # twice
    assert len(jobs(db, JobKind.INBOX_FEEDBACK_ASK_SOLVED)) == 1


def _ask(db, row, world, **kw):
    """``ask_solved`` with its claim stood in for: the real one commits in a
    session of its own, which a test's rolled-back transaction cannot see."""
    kw.setdefault("client", world.client)
    kw.setdefault("claim", lambda _id: True)
    kw.setdefault("release", lambda _id: None)
    return feedback_replies.ask_solved(db, row.id, **kw)


def _resolved(world, db):
    row = _unhappy_waiting_for_a_person(world, db)
    feedback_replies.resolve(db, row.id, world.staff)
    return row


def test_the_solved_question_is_asked_with_buttons_while_her_24_hours_are_open(db, world):
    row = _resolved(world, db)
    sent = len(world.asked)

    _ask(db, row, world)

    assert row.solved_asked_at is not None
    message = world.asked[sent]
    assert message["type"] == "interactive" and message["interactive"]["type"] == "button"
    assert message["interactive"]["body"] == {"text": "Was your issue solved?"}
    assert [b["reply"] for b in message["interactive"]["action"]["buttons"]] == [
        {"id": f"fbs_yes_{row.id}", "title": "Yes"}, {"id": f"fbs_no_{row.id}", "title": "No"},
    ]
    # Once per Resolved, however often the job runs.
    _ask(db, row, world)
    assert len(world.asked) == sent + 1


def test_the_solved_question_is_the_approved_message_once_her_24_hours_have_closed(db, world):
    row = _resolved(world, db)
    world.chat.last_inbound_at = utcnow() - timedelta(hours=30)
    db.flush()
    sent = len(world.asked)

    _ask(db, row, world)

    assert row.solved_asked_at is not None
    template = world.asked[sent]["template"]
    assert (template["name"], template["language"]) == ("feedback_resolved", {"code": "en"})
    body, *buttons = template["components"]
    assert [p["text"] for p in body["parameters"]] == ["#7001"]
    assert [(b["sub_type"], b["index"], b["parameters"][0]["payload"]) for b in buttons] == [
        ("quick_reply", "0", f"fbs_yes_{row.id}"), ("quick_reply", "1", f"fbs_no_{row.id}"),
    ]
    message = db.scalar(select(InboxMessage).where(InboxMessage.template_name == "feedback_resolved"))
    assert (message.kind, message.origin, message.shopify_order_id) == ("template", "automatic", "7001")
    assert message.extra == {"buttons": ["Yes", "No"]}


def test_the_solved_question_is_not_asked_unless_it_is_due_and_allowed(db, world, connected):
    row = _resolved(world, db)
    sent = len(world.asked)
    row.step = "support"
    db.flush()
    _ask(db, row, world)  # not on that step
    row.step = "solved"
    row.solved_asked_at = utcnow()
    db.flush()
    _ask(db, row, world)  # already asked
    assert len(world.asked) == sent


def test_the_solved_question_is_not_sent_where_this_server_may_not_message_her(db, world, monkeypatch):
    row = _resolved(world, db)
    monkeypatch.setattr("app.config.settings.inbox_send_to_customers", False)
    sent = len(world.asked)
    _ask(db, row, world)
    assert len(world.asked) == sent
    # Nothing went out, and she is not left where nobody can see her.
    assert (row.step, row.solved_asked_at, row.resolved_at, row.reopened_count) == ("support", None, None, 0)
    assert "could not be sent" in row.last_error
    db.flush()
    assert [r["id"] for r in feedback.needs_follow_up(db)] == [row.id]


def test_yes_leads_to_how_likely_she_is_to_order_again_and_then_the_closing_words(db, world):
    row = _resolved(world, db)
    _ask(db, row, world)
    sent = len(world.asked)

    apply(db, interactive_tap("button_reply", f"fbs_yes_{row.id}", "Yes", "wamid.S1", ago=timedelta(seconds=20)))
    assert (row.solved, row.step) == (True, "reorder")
    assert row.solved_at is not None
    drain(db, world.client)
    question = world.asked[sent]["interactive"]
    assert question["type"] == "button" and question["body"] == {"text": "How likely are you to order from us again?"}
    assert [b["reply"] for b in question["action"]["buttons"]] == [
        {"id": f"fbo_very_likely_{row.id}", "title": "Very likely"},
        {"id": f"fbo_maybe_{row.id}", "title": "Maybe"},
        {"id": f"fbo_unlikely_{row.id}", "title": "Unlikely"},
    ]

    apply(db, interactive_tap("button_reply", f"fbo_maybe_{row.id}", "Maybe", "wamid.S2", ago=timedelta(seconds=10)))
    assert (row.reorder, row.step) == ("maybe", "done")
    drain(db, world.client)
    assert world.asked[sent + 1]["text"]["body"] == feedback_replies.closing_text(row, feedback.get_settings(db))
    assert len(world.asked) == sent + 2


def test_yes_to_the_approved_message_is_a_template_tap_and_works_the_same(db, world):
    row = _resolved(world, db)
    world.chat.last_inbound_at = utcnow() - timedelta(hours=30)
    db.flush()
    _ask(db, row, world)

    apply(db, template_tap(f"fbs_yes_{row.id}", "Yes", "wamid.S1", ago=timedelta(seconds=20)))
    assert (row.solved, row.step) == (True, "reorder")
    drain(db, world.client)
    assert world.asked[-1]["interactive"]["body"] == {"text": "How likely are you to order from us again?"}


def test_no_sends_her_back_to_a_person_marked_as_reopened(db, world):
    row = _resolved(world, db)
    _ask(db, row, world)
    sent = len(world.asked)

    apply(db, interactive_tap("button_reply", f"fbs_no_{row.id}", "No", "wamid.S1", ago=timedelta(seconds=20)))

    assert (row.solved, row.step, row.reopened_count) == (False, "support", 1)
    assert (row.resolved_at, row.resolved_by, row.solved_asked_at) == (None, None, None)
    assert row.solved_at is not None
    drain(db, world.client)
    # She is told a person will write to her again, once, and nothing else.
    assert len(world.asked) == sent + 1
    assert _bodies(world.asked)[-1] == (
        "We're sorry it isn't solved yet. We've passed it back to our team, and someone "
        "will message you here within 24 hours."
    )
    drain(db, world.client)
    assert len(world.asked) == sent + 1
    assert [r["id"] for r in feedback.needs_follow_up(db)] == [row.id]
    assert feedback.needs_follow_up(db)[0]["reopened_count"] == 1


def test_after_the_second_resolve_she_is_asked_once_more_and_after_the_third_not_again(db, world):
    row = _resolved(world, db)
    mariam = world.staff
    _ask(db, row, world)
    apply(db, interactive_tap("button_reply", f"fbs_no_{row.id}", "No", "wamid.S1", ago=timedelta(seconds=30)))

    later = utcnow() + timedelta(hours=1)
    feedback_replies.resolve(db, row.id, mariam, later)
    assert row.step == "solved"
    _ask(db, row, world)
    assert row.solved_asked_at is not None
    asked_twice = [m for m in world.asked if m["type"] == "interactive" and m["interactive"]["type"] == "button"]
    assert len(asked_twice) == 2

    apply(db, interactive_tap("button_reply", f"fbs_no_{row.id}", "No", "wamid.S2", ago=timedelta(seconds=10)))
    assert (row.step, row.reopened_count) == ("support", 2)

    sent = len(world.asked)
    feedback_replies.resolve(db, row.id, mariam, later + timedelta(hours=1))
    assert row.step == "done" and row.resolved_at is not None
    assert len(jobs(db, JobKind.INBOX_FEEDBACK_ASK_SOLVED)) == 2
    _ask(db, row, world)
    assert len(world.asked) == sent
    assert [r["id"] for r in feedback.needs_follow_up(db)] == []
    keys = [key for _, key, _ in jobs(db, JobKind.INBOX_FEEDBACK_ASK_SOLVED)]
    assert keys == [f"{JobKind.INBOX_FEEDBACK_ASK_SOLVED}:{row.id}:{n}" for n in (0, 1)]


# ── Her comment ───────────────────────────────────────────────────────────────


def test_her_words_a_day_after_her_reason_are_not_a_comment(db, world):
    apply(db, template_tap("fb_loved_7001", "Loved it", "wamid.T1", ago=timedelta(hours=31)))
    apply(db, interactive_tap("list_reply", f"fbr_fit_{world.row.id}", "Fit", "wamid.T2", ago=timedelta(hours=30)))
    assert world.row.step == "comment"

    apply(db, text("By the way, is the beige back?", "wamid.T3", ago=timedelta(seconds=5)))
    assert (world.row.comment, world.row.step) == (None, "comment")
    assert db.scalar(select(InboxMessage.body).where(InboxMessage.wa_message_id == "wamid.T3")) == "By the way, is the beige back?"


def test_her_words_just_inside_the_day_are_her_comment(db, world):
    apply(db, template_tap("fb_loved_7001", "Loved it", "wamid.T1", ago=timedelta(hours=24)))
    apply(db, interactive_tap("list_reply", f"fbr_fit_{world.row.id}", "Fit", "wamid.T2", ago=timedelta(hours=23, minutes=30)))
    apply(db, text("Perfect fit", "wamid.T3", ago=timedelta(seconds=5)))
    assert (world.row.comment, world.row.step) == ("Perfect fit", "done")


def test_only_her_first_words_are_kept_and_only_from_her_own_phone(db, world):
    _rated(world, db, "unhappy", "quality")
    apply(db, text("From someone else", "wamid.X1", sender=STRANGER, ago=timedelta(seconds=20)))
    assert world.row.comment is None
    apply(db, text("The seam came apart", "wamid.X2", ago=timedelta(seconds=15)))
    apply(db, text("And the button too", "wamid.X3", ago=timedelta(seconds=10)))
    assert world.row.comment == "The seam came apart"


def test_words_before_she_has_answered_are_not_a_comment(db, world):
    apply(db, text("Hello?", "wamid.X1", ago=timedelta(seconds=20)))
    assert (world.row.comment, world.row.step) == (None, "rating")
    _rated(world, db, "loved")
    apply(db, text("Hello again", "wamid.X2", ago=timedelta(seconds=5)))
    assert world.row.comment is None  # still choosing a reason


# ── What is sent, and when ────────────────────────────────────────────────────


def test_a_follow_up_is_sent_even_when_her_tap_was_applied_late(db, world):
    """Unlike the reply to a confirmation's tap, an hour is not too late: she
    answered, and the next question is still the right one."""
    apply(db, template_tap("fb_loved_7001", "Loved it", "wamid.T1", ago=timedelta(hours=2)))
    drain(db, world.client)
    assert len(world.asked) == 1


def test_no_follow_up_is_sent_once_her_24_hours_have_closed(db, world):
    apply(db, template_tap("fb_loved_7001", "Loved it", "wamid.T1", ago=timedelta(hours=30)))
    drain(db, world.client)
    assert world.asked == []
    assert world.row.rating == "loved"  # the answer is kept all the same


def test_no_follow_up_is_sent_on_a_server_that_may_not_message_her(db, world, monkeypatch):
    monkeypatch.setattr("app.config.settings.inbox_send_to_customers", False)
    apply(db, template_tap("fb_loved_7001", "Loved it", "wamid.T1"))
    drain(db, world.client)
    assert world.asked == [] and world.row.rating == "loved"


def test_the_reply_handlers_do_nothing_with_the_flag_off(db, world, monkeypatch):
    monkeypatch.setattr("app.config.settings.inbox_feedback_enabled", False)
    apply(db, template_tap("fb_loved_7001", "Loved it", "wamid.T1"))
    [(_, _, payload)] = jobs(db, JobKind.INBOX_FEEDBACK_REPLY)
    feedback_replies._handle_reply(db, payload)
    feedback_replies._handle_ask_solved(db, {"survey_id": world.row.id})
    assert db.query(InboxMessage).filter(InboxMessage.source_ref.is_not(None)).count() == 0


def test_the_closing_words_are_built_in_one_place_with_a_seam_for_her_code(db, world, monkeypatch):
    """The code is issued by ``issue_code`` alone; the words by ``closing_text``.
    (The codes themselves are tested in ``test_inbox_feedback_codes``.)"""
    cfg = feedback.get_settings(db)
    # No answer yet: the neutral thanks.
    assert feedback_replies.closing_text(world.row, cfg) == (
        "Thank you, Nour. Your honest answer helps us get better.\n\n"
        "If there is anything we could do better, just reply here."
    )

    monkeypatch.setattr(feedback_replies, "issue_code", lambda _db, _survey, **_: "THANKS-7K2Q")
    _rated(world, db, "loved", "quality")
    closing = world.asked[1]["text"]["body"]
    assert "THANKS-7K2Q" in closing and "just reply here" in closing


def test_a_tap_job_for_something_that_is_not_a_tap_does_nothing(db, world):
    assert feedback_replies.reply(db, 987654, world.client) is None
    plain = InboxMessage(
        conversation_id=world.chat.id, direction="in", kind="text", body="fb_loved_7001",
        wa_message_id="wamid.PLAIN", status="received", origin="customer", occurred_at=utcnow(),
    )
    db.add(plain)
    db.flush()
    assert feedback_replies.reply(db, plain.id, world.client) is None
    assert world.asked == []
    assert db.query(InboxConversation).count() == 1 and db.query(FeedbackSurvey).count() == 1


# ── The solved question: claimed before it is sent, and never strands her ─────


def test_the_question_is_claimed_before_whatsapp_is_asked(db, world):
    row = _resolved(world, db)
    sent = len(world.asked)
    seen = []
    _ask(db, row, world, claim=lambda _id: seen.append(len(world.asked)) or True)
    assert seen == [sent] and len(world.asked) == sent + 1


def test_a_question_another_worker_claimed_is_not_sent(db, world):
    row = _resolved(world, db)
    sent = len(world.asked)
    _ask(db, row, world, claim=lambda _id: False)
    assert len(world.asked) == sent and row.step == "solved"


def test_a_crash_after_whatsapp_took_the_question_never_sends_it_twice(db, world):
    """The first run claimed it (committed) and WhatsApp took the message; the
    job then died before its own commit, so no message is in the chat. The
    retry finds the claim and sends nothing."""
    row = _resolved(world, db)
    row.solved_asked_at = utcnow()
    db.flush()
    sent = len(world.asked)

    _ask(db, row, world)
    _ask(db, row, world)

    assert len(world.asked) == sent
    assert db.query(InboxMessage).filter(InboxMessage.source_ref.like("fbq:%")).count() == 0


def test_a_claimed_question_with_nothing_to_show_for_it_goes_back_to_a_person(db, world):
    row = _resolved(world, db)
    row.solved_asked_at = utcnow() - timedelta(minutes=11)
    db.flush()

    assert feedback_replies.recover_interrupted_solved(db) == 1

    assert (row.step, row.solved_asked_at, row.resolved_at, row.resolved_by) == ("support", None, None, None)
    assert (row.last_error, row.reopened_count) == (feedback_replies.INTERRUPTED_ASKING, 0)
    db.flush()
    assert [r["id"] for r in feedback.needs_follow_up(db)] == [row.id]


def test_a_claim_that_is_recent_or_has_its_message_is_not_called_interrupted(db, world):
    recent = _resolved(world, db)
    recent.solved_asked_at = utcnow() - timedelta(minutes=2)
    db.flush()
    assert feedback_replies.recover_interrupted_solved(db) == 0
    assert recent.step == "solved"

    recent.solved_asked_at = None
    _ask(db, recent, world)  # asked for real: its message is in the chat
    assert recent.solved_asked_at is not None
    recent.solved_asked_at = utcnow() - timedelta(minutes=30)
    db.flush()
    assert feedback_replies.recover_interrupted_solved(db) == 0
    assert recent.step == "solved"


@pytest.mark.parametrize("window_open", [True, False])
def test_a_retryable_error_gives_the_claim_back_and_is_raised_for_a_retry(db, world, window_open):
    row = _resolved(world, db)
    if not window_open:
        world.chat.last_inbound_at = utcnow() - timedelta(hours=30)
        db.flush()
    released: list = []

    with pytest.raises(MetaError):
        _ask(db, row, world, client=meta([], refuse=(400, 131000)), release=released.append)

    assert released == [row.id]
    assert (row.step, row.solved_asked_at, row.reopened_count) == ("solved", None, 0)
    assert db.query(InboxMessage).filter(InboxMessage.source_ref.like("fbq:%")).count() == 0


@pytest.mark.parametrize("window_open", [True, False])
def test_a_refusal_that_will_not_change_sends_her_back_to_a_person_and_can_be_asked_again(db, world, window_open):
    row = _resolved(world, db)
    if not window_open:
        world.chat.last_inbound_at = utcnow() - timedelta(hours=30)
        db.flush()

    _ask(db, row, world, client=meta([], refuse=(400, 132001)))

    assert (row.step, row.solved_asked_at, row.resolved_at, row.resolved_by) == ("support", None, None, None)
    assert row.reopened_count == 0
    assert row.last_error.startswith('The question "Was your issue solved?" could not be sent: ')
    failed = db.scalar(select(InboxMessage).where(InboxMessage.source_ref.like("fbq:%")))
    assert failed.status == "failed"
    db.flush()
    assert [r["id"] for r in feedback.needs_follow_up(db)] == [row.id]

    # A person follows up and presses Resolved again; this time it goes.
    feedback_replies.resolve(db, row.id, world.staff, utcnow() + timedelta(hours=1))
    sent = len(world.asked)
    _ask(db, row, world, client=world.client, now=utcnow() + timedelta(hours=25))
    assert len(world.asked) == sent + 1 and row.solved_asked_at is not None and row.step == "solved"


def test_keys_that_cannot_be_read_send_her_back_to_a_person(db, world, monkeypatch):
    def unreadable(_db):
        raise outbound.NotSent("WhatsApp is not connected.")

    row = _resolved(world, db)
    monkeypatch.setattr(outbound, "_client", unreadable)
    _ask(db, row, world, client=None)
    assert (row.step, row.solved_asked_at, row.reopened_count) == ("support", None, 0)
    assert "could not be sent" in row.last_error


def test_with_the_feature_off_the_solved_job_hands_her_back_to_a_person(db, world, monkeypatch):
    row = _resolved(world, db)
    monkeypatch.setattr("app.config.settings.inbox_feedback_enabled", False)
    feedback_replies._handle_ask_solved(db, {"survey_id": row.id})
    assert (row.step, row.solved_asked_at, row.reopened_count) == ("support", None, 0)
    assert "switched off" in row.last_error
    assert len(world.asked) == 2  # her first two follow-ups; nothing since


# ── A follow-up WhatsApp refuses leaves its reason on the survey ──────────────


def test_a_follow_up_whatsapp_refuses_for_good_is_recorded_on_the_survey(db, world):
    apply(db, template_tap("fb_loved_7001", "Loved it", "wamid.T1"))
    asked: list = []

    drain(db, meta(asked, refuse=(400, 132001)))

    row = world.row
    assert (row.rating, row.step) == ("loved", "reason")
    assert row.last_error.startswith("A follow-up could not be sent: ")
    failed = db.scalar(select(InboxMessage).where(InboxMessage.source_ref == "fb:wamid.T1"))
    assert failed.status == "failed"
    # Run again: still one attempt.
    drain(db, meta(asked))
    assert len(asked) == 1
