"""Post-delivery feedback: an administrator's test (ADR 0083, decision 7).

"Send a test to my number" runs the real flow for one phone, at once, with the
questions still switched off for everyone else. These tests hold the feature
**off** throughout and prove that a test goes through every gate that a real
survey does not, and that it stays out of every number and every rule that
concerns real customers.

WhatsApp and Shopify are mocked (``meta`` over ``httpx.MockTransport``, and the
in-memory ``Shop`` of the codes tests); nothing leaves the machine. Every
number, name and order is made up.
"""

from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select, text

from app.core.businesstime import utcnow
from app.core.permissions import Permission
from app.db import SessionLocal
from app.modules.inbox import today
from app.main import app
from app.modules.inbox.models import FeedbackSurvey, InboxConversation, InboxMessage
from app.modules.inbox.services import (
    chats,
    connection,
    feedback,
    feedback_codes,
    feedback_messages,
    feedback_replies,
    feedback_sheet,
    outbound,
)
from app.modules.inbox.services.meta import NumberInfo
from app.shared.models.audit import AuditEvent
from app.shared.models.identity import UserAccount
from app.shared.services.jobs import JobKind
from tests.feedback_support import (  # noqa: F401  (fixtures)
    HER,
    NUMBER_ID,
    TOKEN,
    connected,
    conversation,
    feature_on,
    jobs,
    may_send,
    meta,
    node,
    order,
    survey,
)
from tests.test_inbox_feedback_api import _demote_to, client  # noqa: F401  (fixtures)
from tests.test_inbox_feedback_codes import CODE_SHAPE, shop  # noqa: F401  (fixtures)
from tests.test_inbox_feedback_events import (
    _bodies,
    apply,
    interactive_tap,
    template_tap,
)
from tests.test_inbox_feedback_events import text as typed

HER_WRITTEN = "010 0555 0188"


def _yes(survey_id: int) -> bool:
    return True


@pytest.fixture()
def world(db, may_send, shop, monkeypatch):
    """Sending allowed, the questions OFF, WhatsApp recording what it is sent,
    and the staff member who sends the test."""
    monkeypatch.setattr("app.config.settings.inbox_feedback_enabled", False)
    asked: list = []
    monkeypatch.setattr(outbound, "_client", lambda _db: meta(asked))
    # What the jobs ask for in a transaction of their own cannot see this
    # test's uncommitted rows, so the claim is answered for them.
    real_ask = feedback_replies.ask_solved
    monkeypatch.setattr(
        feedback_replies,
        "ask_solved",
        lambda d, sid, **kw: real_ask(d, sid, claim=_yes, release=lambda _id: None, **kw),
    )
    owner = UserAccount(
        email="yahya@example.com", password_hash="x", status="active", display_name="Yahya Aboamer"
    )
    db.add(owner)
    db.flush()
    return SimpleNamespace(asked=asked, owner=owner, shop=shop)


def send(db, world, phone=HER_WRITTEN):
    return feedback.send_test(db, phone, world.owner, client=meta(world.asked), claim=_yes)


def the_test(db) -> FeedbackSurvey:
    return db.scalars(
        select(FeedbackSurvey).where(FeedbackSurvey.is_test.is_(True)).order_by(FeedbackSurvey.id.desc())
    ).first()


def run_replies(db) -> None:
    """Every queued reply, through the job's own handler (which has the switch)."""
    for _, _, payload in jobs(db, JobKind.INBOX_FEEDBACK_REPLY):
        feedback_replies._handle_reply(db, payload)
    db.flush()


def tap_rating(db, row, rating, wamid):
    apply(db, template_tap(f"fb_{rating}_{row.shopify_order_id}", "x", wamid))
    run_replies(db)


def tap_list(db, row, reason, wamid):
    apply(db, interactive_tap("list_reply", f"fbr_{reason}_{row.id}", "x", wamid))
    run_replies(db)


# ── Sending ───────────────────────────────────────────────────────────────────


def test_a_test_is_sent_with_the_questions_switched_off(db, world):
    assert feedback.enabled() is False
    result = send(db, world)
    row = the_test(db)
    assert result == {"sent": True, "phone": HER, "conversation_id": row.conversation_id}
    assert row.conversation_id is not None
    assert (row.state, row.step, row.phone, row.is_test) == ("sent", "rating", HER, True)
    assert (row.order_name, row.courier, row.products) == ("TEST", "Test", ["Test order"])
    assert row.customer_name == "Yahya"
    [first] = world.asked
    assert first["to"] == HER and first["type"] == "template"
    assert first["template"]["name"] == feedback.TEMPLATE
    # The three buttons carry the survey's own (synthetic) order id.
    payloads = [
        c["parameters"][0]["payload"]
        for c in first["template"]["components"]
        if c["type"] == "button"
    ]
    assert payloads == [f"fb_{r}_{row.shopify_order_id}" for r in feedback.RATINGS]
    # The question is in her chat, like a real one.
    chat_rows = db.scalars(
        select(InboxMessage).where(InboxMessage.conversation_id == row.conversation_id)
    ).all()
    assert [m.template_name for m in chat_rows] == [feedback.TEMPLATE]


def test_the_name_falls_back_to_there(db, world):
    world.owner.display_name = None
    send(db, world)
    assert the_test(db).customer_name == "there"


def test_the_synthetic_order_id_cannot_be_a_shopify_order_id_and_the_taps_read_it(db, world):
    send(db, world)
    send(db, world)
    ids = db.scalars(select(FeedbackSurvey.shopify_order_id).where(FeedbackSurvey.is_test)).all()
    assert len(set(ids)) == 2
    for order_id in ids:
        # Shopify's ids are 64-bit numbers: 19 digits at most, below 2**63.
        assert order_id.isdigit() and len(order_id) == 20 and int(order_id) > 2**63 - 1
        tap = feedback_replies.parse_payload(f"fb_loved_{order_id}")
        assert tap is not None and tap.ref == order_id


def test_a_number_that_is_not_an_egyptian_mobile_is_refused(db, world):
    from app.modules.inbox.services.chats import Refused

    for bad in ("", "12345", "+44 7700 900123", "02 2575 0000", "not a number"):
        with pytest.raises(Refused, match="Egyptian mobile"):
            send(db, world, bad)
    assert world.asked == []
    assert the_test(db) is None


def test_a_number_may_be_written_any_usual_way(db, world):
    for written in ("01005550188", "+20 100 555 0188", "0020 100 555 0188", "1005550188"):
        assert send(db, world, written)["phone"] == HER


def test_it_is_refused_when_sending_is_not_allowed_for_that_phone(db, connected, world):
    """Connected, but sending is off: the reason is said, nothing is made."""
    connection.set_sending(db, False, actor_id=None, actor_email=None)
    with pytest.raises(outbound.NotSent) as refused:
        send(db, world)
    assert "sending" in str(refused.value).lower()
    assert world.asked == [] and the_test(db) is None


def test_it_is_refused_when_this_server_may_not_message_that_number(db, world, monkeypatch):
    monkeypatch.setattr("app.config.settings.inbox_send_to_customers", False)
    monkeypatch.setattr("app.config.settings.inbox_test_numbers", "")
    with pytest.raises(outbound.NotSent):
        send(db, world)
    assert world.asked == [] and the_test(db) is None


def test_a_server_not_connected_to_whatsapp_refuses_with_the_reason(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.inbox_feedback_enabled", False)
    owner = UserAccount(email="a@example.com", password_hash="x", status="active", display_name="A")
    db.add(owner)
    db.flush()
    with pytest.raises(outbound.NotSent) as refused:
        feedback.send_test(db, HER, owner, client=meta([]), claim=_yes)
    assert str(refused.value) == feedback.sending.NOT_CONNECTED


def test_whatsapp_refusing_the_message_gives_the_caller_the_reason_and_no_retry(db, world):
    with pytest.raises(outbound.NotSent) as refused:
        feedback.send_test(
            db, HER, world.owner, client=meta([], refuse=(500, 131000)), claim=_yes
        )
    assert str(refused.value)
    row = the_test(db)
    # Never queued for another try in the background: whoever sent it is told.
    assert (row.state, row.step) == ("failed", "done")
    assert jobs(db, JobKind.INBOX_FEEDBACK_SEND) == []


def test_a_number_without_whatsapp_says_so(db, world):
    with pytest.raises(outbound.NotSent):
        feedback.send_test(
            db, HER, world.owner, client=meta([], refuse=(400, 131026)), claim=_yes
        )
    assert the_test(db).state == "no_whatsapp"


def test_repeating_a_test_closes_the_earlier_one(db, world):
    send(db, world)
    first = the_test(db)
    tap_rating(db, first, "okay", "wamid.A1")
    assert first.step == "reason"
    send(db, world)
    second = the_test(db)
    db.refresh(first)
    assert second.id != first.id
    assert first.step == "done" and second.step == "rating"
    # A tap on the old question no longer counts.
    apply(db, interactive_tap("list_reply", f"fbr_price_{first.id}", "x", "wamid.A2"))
    db.refresh(first)
    assert first.reason is None


def test_repeating_a_test_leaves_a_real_survey_alone(db, world):
    real = survey(db, state="sent", step="reason", rating="okay")
    send(db, world)
    db.refresh(real)
    assert real.step == "reason"


# ── The flow, with the feature off ────────────────────────────────────────────


def test_the_loved_path_ends_with_a_real_code_and_the_closing_message_with_the_feature_off(db, world):
    send(db, world)
    row = the_test(db)
    tap_rating(db, row, "loved", "wamid.T1")
    assert row.rating == "loved" and row.step == "reason"
    tap_list(db, row, "quality", "wamid.T2")
    db.refresh(row)

    assert row.step == "comment"  # waiting for her words, if she writes any
    # A real code in the real discount, as for a customer.
    assert CODE_SHAPE.fullmatch(row.code)
    assert [c["code"] for c in world.shop.codes.values()] == [row.code]
    assert row.code_sent_at is not None and row.code_expires_at is not None
    closing = _bodies(world.asked)[-1]
    assert "We're so glad you loved it" in closing and row.code in closing
    assert feedback_messages.text(None, "invitation") in closing
    assert feedback.enabled() is False


def test_the_unhappy_path_asks_was_it_solved_after_a_minute_then_reorder_then_a_code(db, world):
    send(db, world)
    row = the_test(db)
    tap_rating(db, row, "unhappy", "wamid.U1")
    tap_list(db, row, "size_fit", "wamid.U2")
    db.refresh(row)
    assert row.step == "support" and _bodies(world.asked)[-1] == feedback_replies.support_text(
        feedback.get_settings(db), row
    )

    before = utcnow()
    feedback_replies.resolve(db, row.id, world.owner)
    assert row.step == "solved"
    [(_, run_after)] = [
        (kind, when)
        for kind, when in db.execute(
            text("SELECT kind, run_after FROM background_job WHERE kind = :k"),
            {"k": JobKind.INBOX_FEEDBACK_ASK_SOLVED},
        )
    ]
    assert timedelta(seconds=50) <= run_after - before <= timedelta(seconds=75)

    # The job runs (through its handler, with the switch off) and asks.
    feedback_replies._handle_ask_solved(db, {"survey_id": row.id})
    assert row.solved_asked_at is not None
    assert _bodies(world.asked)[-1] == feedback_messages.text(None, "solved_question")

    apply(db, interactive_tap("button_reply", f"fbs_yes_{row.id}", "Yes", "wamid.U3"))
    run_replies(db)
    assert row.solved is True and row.step == "reorder"
    assert _bodies(world.asked)[-1] == feedback_messages.text(None, "reorder_question")

    apply(db, interactive_tap("button_reply", f"fbo_very_likely_{row.id}", "x", "wamid.U4"))
    run_replies(db)
    db.refresh(row)
    assert (row.step, row.reorder) == ("done", "very_likely")
    assert CODE_SHAPE.fullmatch(row.code) and row.code_sent_at is not None
    assert row.code in _bodies(world.asked)[-1]


def test_a_real_survey_is_still_given_no_reply_with_the_feature_off(db, world):
    chat = conversation(db)
    real = survey(db, conversation_id=chat.id)
    apply(db, template_tap(f"fb_loved_{real.shopify_order_id}", "x", "wamid.R1"))
    assert real.rating == "loved"  # her answer is kept...
    run_replies(db)
    assert world.asked == []  # ...but nothing is sent while the feature is off


def test_a_real_question_still_waits_with_the_feature_off_and_a_test_does_not(db, world, monkeypatch):
    real_send = feedback.send_first_question
    monkeypatch.setattr(
        feedback, "send_first_question", lambda d, sid, **kw: real_send(d, sid, claim=_yes, **kw)
    )
    monkeypatch.setattr(outbound, "_client", lambda _db: meta(world.asked))
    waiting = survey(db, "7002", state="pending", sent_at=None, wa_message_id=None)
    testing = survey(
        db, "9" * 20, state="pending", sent_at=None, wa_message_id=None, is_test=True
    )
    feedback._handle_send(db, {"survey_id": waiting.id})
    assert waiting.state == "pending" and world.asked == []
    feedback._handle_send(db, {"survey_id": testing.id})
    assert testing.state == "sent" and len(world.asked) == 1


def test_a_solved_question_for_a_real_survey_still_goes_back_to_a_person_with_the_feature_off(db, world):
    chat = conversation(db)
    real = survey(
        db, conversation_id=chat.id, rating="unhappy", step="solved", resolved_at=utcnow()
    )
    feedback_replies._handle_ask_solved(db, {"survey_id": real.id})
    assert real.step == "support" and world.asked == []


def test_only_a_tests_codes_are_cleared_away_with_the_feature_off(db, world):
    send(db, world)
    row = the_test(db)
    tap_rating(db, row, "loved", "wamid.E1")
    tap_list(db, row, "quality", "wamid.E2")
    db.refresh(row)
    past = utcnow() - timedelta(days=1)
    row.code_expires_at = past
    real = survey(
        db, "7002", code="FB-REAL22", code_gid="gid://shopify/DiscountRedeemCode/999",
        code_sent_at=past - timedelta(days=30), code_expires_at=past, step="done",
    )
    db.flush()
    feedback_codes._handle_expire(db, {})
    [removed] = world.shop.names("FeedbackCodesRemove")
    assert removed["ids"] == [row.code_gid]
    assert real.code_removed_at is None


def test_with_the_feature_off_and_no_test_code_the_clean_up_does_nothing(db, world):
    survey(db, "7002", code="FB-REAL22", code_gid="g", code_expires_at=utcnow() - timedelta(days=1))
    feedback_codes._handle_expire(db, {})
    assert world.shop.calls == []


# ── Never in the way of a real question, and never in the numbers ─────────────


def test_a_test_does_not_trip_the_sixty_day_rule_for_a_real_question(db, world):
    send(db, world)
    assert the_test(db).state == "sent"
    assert feedback._asked_recently(db, HER, utcnow()) is False
    row = feedback.decide(db, order(db), node())
    assert (row.state, row.skip_reason) == ("pending", None)


def test_a_test_that_is_unhappy_and_open_does_not_hold_back_a_real_question(db, world):
    send(db, world)
    test_row = the_test(db)
    test_row.rating, test_row.step, test_row.rated_at = "unhappy", "support", utcnow()
    db.flush()
    row = feedback.decide(db, order(db), node())
    assert row.state == "pending"


def test_a_real_survey_does_not_block_a_test(db, world):
    survey(db, "7002", state="sent", sent_at=utcnow() - timedelta(days=1))
    survey(db, "7003", state="sent", step="support", rating="unhappy", rated_at=utcnow())
    unanswered = conversation(db, wrote_ago=timedelta(hours=1))
    assert unanswered.id
    assert send(db, world)["sent"] is True
    assert the_test(db).state == "sent"


def test_a_real_survey_is_still_blocked_by_a_real_one(db, world):
    """The rules themselves did not move."""
    survey(db, "7002", state="sent", sent_at=utcnow() - timedelta(days=1))
    row = feedback.decide(db, order(db), node())
    assert (row.state, row.skip_reason) == ("skipped", feedback.SKIP_ASKED_RECENTLY)


def _unhappy_test(db, world):
    send(db, world)
    row = the_test(db)
    tap_rating(db, row, "unhappy", "wamid.N1")
    tap_list(db, row, "quality", "wamid.N2")
    db.refresh(row)
    assert (row.rating, row.step) == ("unhappy", "support")
    return row


def test_a_test_is_in_no_sheet_number_menu_or_download(db, world):
    _unhappy_test(db, world)
    assert feedback.rows(db) == [] and feedback.rows(db, limit=None, include_skipped=True) == []
    assert feedback.rows(db, state="needs_follow_up") == []
    assert feedback.rows(db, q="TEST") == [] and feedback.rows(db, q="Yahya") == []
    assert set(feedback.summary(db).values()) == {0}
    assert feedback.options(db)["couriers"] == []
    assert feedback.needs_follow_up(db) == []
    built = load_workbook(BytesIO(feedback_sheet.build(feedback.rows(db, limit=None)))).active
    empty = load_workbook(BytesIO(feedback_sheet.build([]))).active
    assert built.max_row == empty.max_row
    cells = {str(c.value) for row in built.iter_rows() for c in row}
    assert not cells & {"TEST", HER, "Yahya"}


def test_a_real_survey_beside_a_test_is_still_counted(db, world):
    _unhappy_test(db, world)
    survey(
        db, "7002", state="sent", step="support", rating="unhappy", rated_at=utcnow(),
        sent_at=utcnow(),
    )
    assert feedback.summary(db)["asked"] == 1
    assert [r["order_name"] for r in feedback.rows(db)] == ["#7002"]


def test_a_test_is_not_counted_in_today_or_the_sidebar_but_is_in_the_chats_view(db, world):
    row = _unhappy_test(db, world)
    assert chats.counts(db)["follow_up"] == 0
    found = today.look(db, frozenset({Permission.INBOX_USE}), utcnow())
    assert found.counts["chats_follow_up"] == 0
    assert [i.key for i in found.items if i.key.startswith("inbox.feedback")] == []

    listed = chats.list_conversations(db, view="follow_up")["conversations"]
    assert [c["id"] for c in listed] == [row.conversation_id]
    assert listed[0]["feedback"] == "follow_up"
    assert chats.list_conversations(db, view="all")["conversations"][0]["feedback"] == "follow_up"


def test_a_tests_reopened_answer_is_not_counted_either(db, world):
    row = _unhappy_test(db, world)
    row.reopened_count = 1
    db.flush()
    assert feedback.reopened_chats(db) == (0, None)
    assert feedback.oldest_follow_up(db) is None


def test_a_real_follow_up_is_counted_and_listed_beside_a_test(db, world):
    test_row = _unhappy_test(db, world)
    chat = InboxConversation(phone="201005550199", name="Salma")
    db.add(chat)
    db.flush()
    survey(
        db, "7002", phone="201005550199", conversation_id=chat.id, state="sent",
        step="support", rating="unhappy", rated_at=utcnow(),
    )
    assert chats.counts(db)["follow_up"] == 1
    ids = {c["id"] for c in chats.list_conversations(db, view="follow_up")["conversations"]}
    assert ids == {chat.id, test_row.conversation_id}


def test_the_chat_shows_the_test_with_its_label_and_resolved_works(db, world):
    row = _unhappy_test(db, world)
    block = chats.conversation_detail(db, row.conversation_id)["feedback"]
    assert block["is_test"] is True
    assert (block["order_name"], block["rating"], block["needs_follow_up"]) == ("TEST", "unhappy", True)

    done = feedback_replies.resolve(db, row.id, world.owner)
    assert done["step"] == "solved" and done["resolved_at"]
    block = chats.conversation_detail(db, row.conversation_id)["feedback"]
    assert block["resolved_at"] and block["needs_follow_up"] is False


def test_a_real_survey_in_the_chat_is_not_marked_as_a_test(db, world):
    chat = conversation(db)
    survey(db, conversation_id=chat.id)
    assert chats.conversation_detail(db, chat.id)["feedback"]["is_test"] is False


def test_the_test_is_audited_without_the_whole_number(db, world):
    send(db, world)
    [event] = db.scalars(select(AuditEvent).where(AuditEvent.action == "inbox.feedback_test_sent")).all()
    assert event.actor_id == world.owner.id
    assert event.after_json == {"phone_ending": HER[-4:]}
    assert HER not in str(event.after_json) and HER not in (event.subject or "")


def test_a_refused_test_is_not_audited(db, world):
    with pytest.raises(Exception):
        send(db, world, "12345")
    assert db.scalars(select(AuditEvent).where(AuditEvent.action == "inbox.feedback_test_sent")).all() == []


# ── A test that failed is never sent later ────────────────────────────────────


def _unconnected(db, world, monkeypatch):
    """WhatsApp's keys cannot be read when the send goes to build its client."""

    def refuse(_db):
        raise outbound.NotSent("WhatsApp is not connected.", kind="not_connected")

    monkeypatch.setattr(outbound, "_client", refuse)
    with pytest.raises(outbound.NotSent) as refused:
        feedback.send_test(db, HER, world.owner, claim=_yes)
    return refused


def test_a_test_that_fails_outside_the_returned_row_is_closed_not_left_pending(db, world, monkeypatch):
    refused = _unconnected(db, world, monkeypatch)
    row = the_test(db)
    assert str(refused.value) == "WhatsApp is not connected."
    assert (row.state, row.step) == ("failed", "done")
    assert row.last_error == "WhatsApp is not connected."
    assert world.asked == []


def test_a_failed_test_is_never_sent_later_once_the_feature_is_on(db, world, monkeypatch, feature_on):
    _unconnected(db, world, monkeypatch)
    row = the_test(db)
    later = utcnow() + timedelta(hours=2)
    assert feedback.requeue_stale_pending(db, later) == 0
    assert jobs(db, JobKind.INBOX_FEEDBACK_SEND) == []
    assert (row.state, row.step) == ("failed", "done")


def test_the_sweep_closes_an_orphaned_test_instead_of_queuing_it(db, world, feature_on):
    """A test left pending by a crash between its saving and its sending."""
    orphan = survey(
        db, "9" * 20, state="pending", sent_at=None, wa_message_id=None, is_test=True
    )
    real = survey(db, "7002", state="pending", sent_at=None, wa_message_id=None)
    old = utcnow() - timedelta(hours=1)
    for row in (orphan, real):
        row.updated_at = old
    db.flush()
    assert feedback.requeue_stale_pending(db) == 1  # the real one only
    assert [p["survey_id"] for _, _, p in jobs(db, JobKind.INBOX_FEEDBACK_SEND)] == [real.id]
    db.refresh(orphan)
    assert (orphan.state, orphan.step) == ("failed", "done")
    assert orphan.last_error


def test_no_other_sweep_pass_picks_a_test_up_again(db, world):
    waiting = survey(
        db, "9" * 20, state="waiting", sent_at=None, is_test=True,
        next_attempt_at=utcnow() - timedelta(hours=1),
    )
    assert feedback.waiting_to_look_at(db) == []
    assert waiting.state == "waiting"

    stuck = survey(db, "9" * 19 + "1", state="sending", is_test=True, step="rating")
    stuck_real = survey(db, "7002", state="sending")
    old = utcnow() - timedelta(hours=1)
    stuck.updated_at = stuck_real.updated_at = old
    db.flush()
    assert feedback.recover_interrupted(db) == 2
    db.refresh(stuck)
    db.refresh(stuck_real)
    assert (stuck.state, stuck.step) == ("failed", "done")  # closed outright
    assert (stuck_real.state, stuck_real.step) == ("failed", "rating")

    solved_test = survey(
        db, "9" * 19 + "2", is_test=True, rating="unhappy", step="solved",
        resolved_at=old, solved_asked_at=old,
    )
    solved_real = survey(
        db, "7003", rating="unhappy", step="solved", resolved_at=old, solved_asked_at=old
    )
    assert feedback_replies.recover_interrupted_solved(db) == 1
    assert solved_test.step == "solved" and solved_real.step == "support"


# ── The okay view and badge are the customers' ────────────────────────────────


def _okay_test(db, world):
    send(db, world)
    row = the_test(db)
    tap_rating(db, row, "okay", "wamid.K1")
    tap_list(db, row, "price", "wamid.K2")
    db.refresh(row)
    assert row.rating == "okay"
    return row


def test_a_test_answered_okay_does_not_make_the_chat_neutral(db, world):
    row = _okay_test(db, world)
    assert chats.list_conversations(db, view="neutral")["conversations"] == []
    assert feedback.markers(db, [row.conversation_id]) == {}
    assert chats.list_conversations(db, view="all")["conversations"][0]["feedback"] is None


def test_a_test_does_not_replace_her_real_latest_answer(db, world):
    chat = conversation(db)
    survey(
        db, "7002", conversation_id=chat.id, rating="okay", step="done",
        rated_at=utcnow() - timedelta(days=1),
    )
    send(db, world)
    row = the_test(db)
    tap_rating(db, row, "loved", "wamid.L1")
    tap_list(db, row, "quality", "wamid.L2")
    # Her real answer is still the latest: the chat stays in the okay view.
    assert [c["id"] for c in chats.list_conversations(db, view="neutral")["conversations"]] == [chat.id]
    assert feedback.markers(db, [chat.id]) == {chat.id: "neutral"}


def test_a_test_that_is_unhappy_still_badges_the_follow_up_view(db, world):
    row = _unhappy_test(db, world)
    assert feedback.markers(db, [row.conversation_id]) == {row.conversation_id: "follow_up"}


# ── A test does not take over a real customer's chat ──────────────────────────


def test_her_next_words_go_to_her_real_survey_not_a_newer_test(db, world):
    chat = conversation(db)
    real = survey(
        db, "7002", conversation_id=chat.id, rating="loved", step="comment",
        reason="quality", reason_at=utcnow() - timedelta(minutes=30),
    )
    send(db, world)
    test_row = the_test(db)
    test_row.rating, test_row.step = "loved", "comment"
    test_row.reason, test_row.reason_at = "quality", utcnow() - timedelta(minutes=5)
    db.flush()
    apply(db, typed("Lovely, thank you", "wamid.W1"))
    assert real.comment == "Lovely, thank you" and real.step == "done"
    assert test_row.comment is None and test_row.step == "comment"


def test_a_test_receives_her_words_when_nothing_real_is_waiting(db, world):
    send(db, world)
    test_row = the_test(db)
    test_row.rating, test_row.step = "loved", "comment"
    test_row.reason, test_row.reason_at = "quality", utcnow() - timedelta(minutes=5)
    db.flush()
    apply(db, typed("Nice", "wamid.W2"))
    assert test_row.comment == "Nice"


def test_the_chat_shows_her_real_unhappy_survey_over_a_newer_test(db, world):
    chat = conversation(db)
    real = survey(
        db, "7002", conversation_id=chat.id, rating="unhappy", step="support",
        rated_at=utcnow() - timedelta(days=2), sent_at=utcnow() - timedelta(days=2),
    )
    send(db, world)
    assert the_test(db).conversation_id == chat.id
    block = chats.conversation_detail(db, chat.id)["feedback"]
    assert block["id"] == real.id and block["is_test"] is False
    assert block["needs_follow_up"] is True
    # Also while it waits for her answer to "was it solved?".
    real.step = "solved"
    db.flush()
    assert chats.conversation_detail(db, chat.id)["feedback"]["id"] == real.id


def test_the_chat_shows_the_newest_survey_otherwise(db, world):
    chat = conversation(db)
    survey(
        db, "7002", conversation_id=chat.id, rating="loved", step="done",
        sent_at=utcnow() - timedelta(days=2),
    )
    send(db, world)
    block = chats.conversation_detail(db, chat.id)["feedback"]
    assert block["is_test"] is True
    # And a real survey that needs nothing does not hide a newer real one.
    newer = survey(
        db, "7003", conversation_id=chat.id, rating="okay", step="done",
        sent_at=utcnow() + timedelta(minutes=1),
    )
    assert chats.conversation_detail(db, chat.id)["feedback"]["id"] == newer.id


# ── The route ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def wired(client, monkeypatch):
    """The route over the real database: WhatsApp saved and sending on (both
    committed), Meta answering from memory."""
    monkeypatch.setattr("app.config.settings.settings_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr("app.config.settings.inbox_send_to_customers", True)
    monkeypatch.setattr("app.config.settings.inbox_feedback_enabled", False)
    asked: list = []
    monkeypatch.setattr(outbound, "_client", lambda _db: meta(asked))
    with SessionLocal() as session:
        connection.save_whatsapp(
            session,
            phone_number_id=NUMBER_ID,
            business_account_id="777888999000111",
            access_token=TOKEN,
            app_secret="made-up-app-secret-000000009f3c",
            verify_token="made-up-check-word-0001",
            actor_id=None,
            actor_email=None,
            checker=lambda *args: NumberInfo("+20 100 555 0100", "HBA Wear", "GREEN"),
        )
        connection.set_sending(session, True, actor_id=None, actor_email=None)
        session.commit()
    return SimpleNamespace(client=client, asked=asked)


def test_the_route_sends_a_test_and_names_the_chat(wired):
    response = wired.client.post("/api/inbox/feedback/test", json={"phone": "01005550188"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sent"] is True and body["phone"] == HER and isinstance(body["conversation_id"], int)
    assert len(wired.asked) == 1
    with SessionLocal() as session:
        row = session.scalar(select(FeedbackSurvey))
        assert (row.is_test, row.state, row.conversation_id) == (True, "sent", body["conversation_id"])
        assert session.scalar(
            select(AuditEvent.id).where(AuditEvent.action == "inbox.feedback_test_sent")
        )
    # The chat it names is there, and shows the test.
    chat = wired.client.get(f"/api/inbox/conversations/{body['conversation_id']}").json()
    assert chat["feedback"]["is_test"] is True


def test_the_route_says_why_in_plain_words(wired):
    bad = wired.client.post("/api/inbox/feedback/test", json={"phone": "12345"})
    assert bad.status_code == 422 and "Egyptian mobile" in bad.json()["detail"]
    assert wired.client.post("/api/inbox/feedback/test", json={}).status_code == 422
    assert wired.asked == []


def test_the_route_says_409_when_the_number_may_not_be_messaged(wired, monkeypatch):
    monkeypatch.setattr("app.config.settings.inbox_send_to_customers", False)
    monkeypatch.setattr("app.config.settings.inbox_test_numbers", "")
    refused = wired.client.post("/api/inbox/feedback/test", json={"phone": "01005550188"})
    assert refused.status_code == 409 and refused.json()["detail"]
    assert wired.asked == []


def test_the_route_says_409_when_whatsapp_does_not_take_it(wired, monkeypatch):
    monkeypatch.setattr(outbound, "_client", lambda _db: meta([], refuse=(400, 131026)))
    refused = wired.client.post("/api/inbox/feedback/test", json={"phone": "01005550188"})
    assert refused.status_code == 409 and refused.json()["detail"]


def test_the_test_is_in_none_of_the_routes_numbers(wired):
    assert wired.client.post("/api/inbox/feedback/test", json={"phone": "01005550188"}).status_code == 200
    with SessionLocal() as session:
        row = session.scalar(select(FeedbackSurvey))
        row.rating, row.step, row.rated_at = "unhappy", "support", utcnow()
        session.commit()
    sheet = wired.client.get("/api/inbox/feedback").json()
    assert sheet["rows"] == [] and set(sheet["summary"].values()) == {0}
    assert sheet["options"]["couriers"] == []
    download = wired.client.get("/api/inbox/feedback/download")
    assert download.status_code == 200
    cells = {str(c.value) for r in load_workbook(BytesIO(download.content)).active.iter_rows() for c in r}
    assert not cells & {"TEST", HER}
    listing = wired.client.get("/api/inbox/conversations", params={"view": "follow_up"}).json()
    assert listing["counts"]["follow_up"] == 0 and len(listing["conversations"]) == 1
    today_body = wired.client.get("/api/today").json()
    assert today_body["counts"]["chats_follow_up"] == 0


@pytest.mark.parametrize("role", ["customer_service", "operations_manager"])
def test_only_an_admin_can_send_a_test(wired, role):
    _demote_to(role)
    response = wired.client.post("/api/inbox/feedback/test", json={"phone": "01005550188"})
    assert response.status_code == 403
    assert wired.asked == []


@pytest.mark.parametrize("role", ["affiliate_manager", "content_manager", "affiliate"])
def test_a_role_without_the_inbox_cannot_send_a_test(wired, role):
    _demote_to(role)
    assert wired.client.post("/api/inbox/feedback/test", json={"phone": "01005550188"}).status_code == 403


def test_nobody_signed_out_can_send_a_test(fresh_database):
    with TestClient(app) as anonymous:
        assert anonymous.post("/api/inbox/feedback/test", json={"phone": "01005550188"}).status_code == 401


# ── Something else ────────────────────────────────────────────────────────────


def test_something_else_is_asked_what_it_was_in_place_of_the_invitation(db, world):
    """The list could not say what it was, so the last message asks her."""
    send(db, world)
    row = the_test(db)
    tap_rating(db, row, "okay", "wamid.S1")
    tap_list(db, row, "other", "wamid.S2")
    db.refresh(row)

    closing = _bodies(world.asked)[-1]
    assert row.reason == "other" and row.step == "comment"
    assert "Your honest answer helps us get better" in closing
    assert closing.endswith(feedback_messages.text(None, "tell_us"))
    assert feedback_messages.text(None, "invitation") not in closing


def test_an_unhappy_something_else_is_promised_a_person_and_asked_what_went_wrong(db, world):
    send(db, world)
    row = the_test(db)
    tap_rating(db, row, "unhappy", "wamid.S3")
    tap_list(db, row, "other", "wamid.S4")
    db.refresh(row)

    cfg = feedback.get_settings(db)
    said = _bodies(world.asked)[-1]
    assert row.step == "support"
    promise = feedback_messages.text(None, "support", name="Yahya", hours=cfg.reply_hours)
    assert said == promise + "\n\n" + feedback_messages.text(None, "tell_us")
    # Any other reason is promised a person and asked nothing more.
    price = SimpleNamespace(customer_name="Yahya", reason="price")
    assert feedback_replies.support_text(cfg, price) == promise
