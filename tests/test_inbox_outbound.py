"""Every message the platform sends (ADR 0059; the plan's phase 3).

The confirmation and the two automatic replies. Meta is never called: a mock
transport answers and records what was asked. Every order, name and number
here is made up.
"""

import json
from datetime import timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from app.core.businesstime import utcnow
from app.db import SessionLocal
from app.models.inbox import InboxConversation, InboxMessage, OrderConfirmation
from app.services.inbox import connection, outbound, sending
from app.services.inbox.meta import MetaClient, NumberInfo
from app.services.inbox.outbound import (
    INTERRUPTED,
    MAX_ATTEMPTS,
    NotSent,
    auto_reply,
    recover_interrupted,
    send_confirmation,
    send_text,
    window_open,
)
from app.services.jobs import PermanentFailure

HER = "201005550188"
TOKEN = "EAAG-made-up-access-key-0000a1b2"
NUMBER_ID = "100200300400500"


@pytest.fixture()
def connected(db, monkeypatch):
    """WhatsApp connected, sending still off, server not told it may send."""
    monkeypatch.setattr(
        "app.config.settings.settings_encryption_key", Fernet.generate_key().decode()
    )
    monkeypatch.setattr("app.config.settings.inbox_send_to_customers", False)
    monkeypatch.setattr("app.config.settings.inbox_test_numbers", "")
    connection.save_whatsapp(
        db,
        phone_number_id=NUMBER_ID,
        business_account_id="777888999000111",
        access_token=TOKEN,
        app_secret="made-up-app-secret-000000009f3c",
        verify_token="made-up-check-word-0001",
        actor_id=None,
        actor_email=None,
        checker=lambda *args: NumberInfo("+20 100 555 0100", "HBA Wear", "GREEN"),
    )


@pytest.fixture()
def may_send(db, connected, monkeypatch):
    """The one configuration in which a customer is messaged."""
    connection.set_sending(db, True, actor_id=None, actor_email=None)
    monkeypatch.setattr("app.config.settings.inbox_send_to_customers", True)


def _meta(asked: list, *, refuse: tuple[int, int] | None = None, fail_network=False) -> MetaClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if fail_network:
            raise httpx.ConnectError("down")
        asked.append(json.loads(request.read()))
        if refuse:
            status, code = refuse
            return httpx.Response(status, json={"error": {"code": code, "message": f"to {HER}"}})
        return httpx.Response(200, json={"messages": [{"id": f"wamid.SENT{len(asked)}"}]})

    return MetaClient(TOKEN, NUMBER_ID, api_version="v23.0", transport=httpx.MockTransport(handler))


def _conversation(db, *, wrote_ago: timedelta | None = timedelta(minutes=5)) -> InboxConversation:
    conversation = InboxConversation(
        phone=HER, last_inbound_at=utcnow() - wrote_ago if wrote_ago is not None else None
    )
    db.add(conversation)
    db.flush()
    return conversation


def _pending(db, order_id="5001") -> OrderConfirmation:
    row = OrderConfirmation(
        shopify_order_id=order_id, order_name="#31044", state="pending",
        phone=HER, customer_name="Nour", total_text="1450.00",
    )
    db.add(row)
    db.flush()
    return row


def _yes(order_id: str) -> bool:
    return True


def _jobs(db) -> list[tuple]:
    db.flush()
    return db.execute(
        text("SELECT kind, dedupe_key FROM background_job ORDER BY id")
    ).all()


# ── The 24 hours ──────────────────────────────────────────────────────────────


def test_a_free_reply_is_allowed_for_24_hours_after_she_wrote():
    def wrote(ago):
        return InboxConversation(phone=HER, last_inbound_at=utcnow() - ago if ago else None)

    assert window_open(wrote(timedelta(hours=23, minutes=59))) is True
    assert window_open(wrote(timedelta(hours=24, minutes=1))) is False
    assert window_open(wrote(None)) is False


# ── A free message ────────────────────────────────────────────────────────────


def test_a_message_goes_out_and_into_the_chat(db, may_send):
    asked: list = []
    conversation = _conversation(db)
    message = send_text(db, conversation, "Of course.", origin="automatic", client=_meta(asked))

    assert asked[0]["to"] == HER and asked[0]["text"]["body"] == "Of course."
    assert (message.direction, message.status, message.wa_message_id) == ("out", "sent", "wamid.SENT1")
    assert conversation.last_preview == "Of course."
    assert conversation.last_direction == "out"


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        ("nothing", sending.NOT_CONNECTED),
        ("connected", sending.SENDING_OFF),
        ("on_but_not_told", sending.NOT_A_TEST_NUMBER),
    ],
)
def test_nobody_is_messaged_unless_this_server_may(db, monkeypatch, request, setup, reason):
    """Refused, nothing is asked of WhatsApp and nothing is recorded as sent."""
    if setup != "nothing":
        request.getfixturevalue("connected")
    if setup == "on_but_not_told":
        connection.set_sending(db, True, actor_id=None, actor_email=None)
    asked: list = []
    with pytest.raises(NotSent, match=reason[:20]):
        send_text(db, _conversation(db), "Hello", origin="automatic", client=_meta(asked))
    assert asked == []
    assert db.query(InboxMessage).count() == 0


def test_a_test_number_is_messaged_on_a_server_not_told_it_may_message_customers(
    db, connected, monkeypatch
):
    connection.set_sending(db, True, actor_id=None, actor_email=None)
    monkeypatch.setattr("app.config.settings.inbox_test_numbers", "0100 555 0188")
    asked: list = []
    send_text(db, _conversation(db), "Test", origin="automatic", client=_meta(asked))
    assert len(asked) == 1


def test_outside_the_24_hours_a_free_message_is_refused_before_asking(db, may_send):
    asked: list = []
    with pytest.raises(NotSent) as refused:
        send_text(
            db, _conversation(db, wrote_ago=timedelta(hours=30)), "Hello",
            origin="staff", client=_meta(asked),
        )
    assert refused.value.kind == "window_closed"
    assert asked == []


def test_a_message_whatsapp_refuses_is_shown_as_failed_with_the_reason(db, may_send):
    message = send_text(
        db, _conversation(db), "Hello", origin="staff", client=_meta([], refuse=(400, 131026))
    )
    assert (message.status, message.wa_message_id) == ("failed", None)
    assert message.error == "WhatsApp could not reach this number (code 131026)"
    assert HER not in message.error


def test_an_automatic_message_whatsapp_did_not_answer_is_left_for_the_job_to_retry(db, may_send):
    from app.services.inbox.meta import MetaError

    with pytest.raises(MetaError):
        send_text(db, _conversation(db), "Hello", origin="automatic", client=_meta([], fail_network=True))
    assert db.query(InboxMessage).count() == 0


# ── The reply to a tap ────────────────────────────────────────────────────────


def _tap(db, payload, *, ago=timedelta(seconds=5), wamid="wamid.TAP1") -> InboxMessage:
    conversation = _conversation(db, wrote_ago=ago)
    tap = InboxMessage(
        conversation_id=conversation.id, direction="in", kind="button", body="Edit",
        wa_message_id=wamid, status="received", origin="customer",
        extra={"payload": payload}, occurred_at=utcnow() - ago,
    )
    db.add(tap)
    db.flush()
    return tap


@pytest.mark.parametrize(
    ("payload", "words"),
    [
        ("edit_5001", "What would you like to change? ✏️ Type it here and our team will help you."),
        ("cancel_5001", "We received your cancellation request ❌"),
    ],
)
def test_a_tap_on_edit_or_cancel_is_answered(db, may_send, payload, words):
    asked: list = []
    reply = auto_reply(db, _tap(db, payload).id, client=_meta(asked))
    assert asked[0]["text"]["body"] == words
    assert (reply.origin, reply.status, reply.body) == ("automatic", "sent", words)
    assert reply.sent_by is None


def test_a_cancel_is_not_said_to_have_happened(db, may_send):
    """The order is only tagged until somebody acts on it."""
    reply = auto_reply(db, _tap(db, "cancel_5001").id, client=_meta([]))
    assert "has been cancelled" not in reply.body
    assert "request" in reply.body


def test_a_tap_on_confirm_gets_no_reply(db, may_send):
    asked: list = []
    assert auto_reply(db, _tap(db, "confirm_5001").id, client=_meta(asked)) is None
    assert asked == []


def test_a_tap_is_answered_once_however_often_the_job_runs(db, may_send):
    asked: list = []
    tap = _tap(db, "edit_5001")
    assert auto_reply(db, tap.id, client=_meta(asked)) is not None
    assert auto_reply(db, tap.id, client=_meta(asked)) is None
    assert len(asked) == 1


def test_a_tap_that_is_no_longer_fresh_is_not_answered(db, may_send):
    """A callback applied an hour late must not answer out of the blue."""
    asked: list = []
    assert auto_reply(db, _tap(db, "edit_5001", ago=timedelta(hours=1)).id, client=_meta(asked)) is None
    assert asked == []


def test_a_tap_is_not_answered_on_a_server_that_may_not_message_her(db, connected):
    asked: list = []
    assert auto_reply(db, _tap(db, "edit_5001").id, client=_meta(asked)) is None
    assert asked == []
    assert db.query(InboxMessage).filter_by(direction="out").count() == 0


def test_a_message_that_is_not_a_tap_is_not_answered(db, may_send):
    conversation = _conversation(db)
    text_message = InboxMessage(
        conversation_id=conversation.id, direction="in", kind="text", body="edit_5001",
        wa_message_id="wamid.T", status="received", origin="customer", occurred_at=utcnow(),
    )
    db.add(text_message)
    db.flush()
    assert auto_reply(db, text_message.id, client=_meta([])) is None
    assert auto_reply(db, 987654, client=_meta([])) is None


# ── An order's confirmation ───────────────────────────────────────────────────


def test_the_confirmation_is_the_approved_message_as_n8n_sent_it(db, may_send):
    asked: list = []
    _pending(db)
    send_confirmation(db, "5001", client=_meta(asked), claim=_yes)

    sent = asked[0]
    assert (sent["to"], sent["type"]) == (HER, "template")
    template = sent["template"]
    assert (template["name"], template["language"]) == ("order_confirmation", {"code": "en"})
    body, *buttons = template["components"]
    assert [p["text"] for p in body["parameters"]] == ["#31044", "Nour", "1450.00"]
    assert [(b["index"], b["parameters"][0]["payload"]) for b in buttons] == [
        ("0", "confirm_5001"), ("1", "edit_5001"), ("2", "cancel_5001"),
    ]


def test_a_sent_confirmation_is_on_the_order_in_the_chat_and_queued_for_its_tag(db, may_send):
    row = _pending(db)
    send_confirmation(db, "5001", client=_meta([]), claim=_yes)

    assert (row.state, row.wa_message_id, row.attempts, row.last_error) == (
        "sent", "wamid.SENT1", 1, None,
    )
    assert row.sent_at is not None
    conversation = db.query(InboxConversation).one()
    assert (conversation.phone, conversation.name, row.conversation_id) == (HER, "Nour", conversation.id)
    message = db.query(InboxMessage).one()
    assert (message.kind, message.origin, message.template_name, message.shopify_order_id) == (
        "template", "automatic", "order_confirmation", "5001",
    )
    assert message.body == "Order confirmation · #31044"
    assert ("inbox_tag_order", "inbox_tag_order:5001:WA Sent 📤") in _jobs(db)


def test_an_order_is_sent_only_while_it_is_waiting(db, may_send):
    asked: list = []
    for state in ("sent", "would_send", "sending", "failed", "not_needed", "no_whatsapp"):
        row = _pending(db, order_id=f"6{state}")
        row.state = state
        db.flush()
        send_confirmation(db, row.shopify_order_id, client=_meta(asked), claim=_yes)
        assert row.state == state
    assert asked == []
    assert send_confirmation(db, "9999", client=_meta(asked), claim=_yes) is None


def test_an_order_somebody_else_claimed_is_not_sent(db, may_send):
    asked: list = []
    _pending(db)
    send_confirmation(db, "5001", client=_meta(asked), claim=lambda order_id: False)
    assert asked == []


def test_if_sending_was_turned_off_meanwhile_the_order_only_records(db, connected):
    asked: list = []
    row = _pending(db)
    send_confirmation(db, "5001", client=_meta(asked), claim=_yes)
    assert row.state == "would_send"
    assert asked == []


def test_a_number_with_no_whatsapp_is_said_so_and_not_tried_again(db, may_send):
    row = _pending(db)
    send_confirmation(db, "5001", client=_meta([], refuse=(400, 131026)), claim=_yes)
    assert row.state == "no_whatsapp"
    assert row.last_error == "WhatsApp could not reach this number (code 131026)"
    assert ("inbox_tag_order", "inbox_tag_order:5001:No WhatsApp 📵") in _jobs(db)
    assert not any(kind == "inbox_send_confirmation" for kind, _ in _jobs(db))


def test_when_whatsapp_does_not_answer_it_is_tried_again_later(db, may_send):
    row = _pending(db)
    send_confirmation(db, "5001", client=_meta([], fail_network=True), claim=_yes)
    assert (row.state, row.attempts) == ("pending", 1)
    assert row.next_attempt_at > utcnow()
    assert ("inbox_send_confirmation", "inbox_send_confirmation:5001:1") in _jobs(db)
    assert db.query(InboxMessage).count() == 0


def test_after_five_tries_it_is_failed_and_shown(db, may_send):
    row = _pending(db)
    for _ in range(MAX_ATTEMPTS):
        row.state = "pending"
        send_confirmation(db, "5001", client=_meta([], fail_network=True), claim=_yes)
    assert (row.state, row.attempts) == ("failed", MAX_ATTEMPTS)
    assert "did not answer" in row.last_error


def test_a_refusal_that_retrying_cannot_fix_fails_at_once(db, may_send):
    row = _pending(db)
    send_confirmation(db, "5001", client=_meta([], refuse=(400, 132001)), claim=_yes)
    assert (row.state, row.attempts) == ("failed", 1)
    assert "no approved message by that name" in row.last_error


def test_an_order_with_no_first_name_is_greeted_as_the_old_message_did(db, may_send):
    asked: list = []
    row = _pending(db)
    row.customer_name = "there"
    send_confirmation(db, "5001", client=_meta(asked), claim=_yes)
    assert asked[0]["template"]["components"][0]["parameters"][1]["text"] == "there"
    # "there" is a greeting, not her name.
    assert db.query(InboxConversation).one().name is None


# ── Sent at most once ─────────────────────────────────────────────────────────


def test_an_order_is_claimed_once(fresh_database):
    """What makes a crash after WhatsApp accepted the message harmless."""
    with SessionLocal() as db:
        db.add(OrderConfirmation(shopify_order_id="5001", state="pending", phone=HER))
        db.commit()
    assert outbound._claim("5001") is True
    assert outbound._claim("5001") is False
    with SessionLocal() as db:
        assert db.query(OrderConfirmation).one().state == "sending"


def test_an_order_left_sending_by_a_crash_is_failed_never_sent_again(db, may_send):
    asked: list = []
    row = _pending(db)
    row.state = "sending"
    row.updated_at = utcnow() - timedelta(minutes=30)
    db.flush()
    assert recover_interrupted(db) == 1
    db.refresh(row)
    assert (row.state, row.last_error) == ("failed", INTERRUPTED)
    send_confirmation(db, "5001", client=_meta(asked), claim=_yes)
    assert asked == []


def test_an_order_being_sent_right_now_is_left_alone(db):
    row = _pending(db)
    row.state = "sending"
    row.updated_at = utcnow() - timedelta(seconds=20)
    db.flush()
    assert recover_interrupted(db) == 0


# ── The jobs ──────────────────────────────────────────────────────────────────


def test_the_jobs_need_their_ids(db):
    with pytest.raises(PermanentFailure, match="requires an order_id"):
        outbound._handle_send_confirmation(db, {})
    with pytest.raises(PermanentFailure, match="requires a message_id"):
        outbound._handle_auto_reply(db, {})


def test_keys_this_server_cannot_read_fail_the_job_at_once(db, may_send, monkeypatch):
    _pending(db)
    monkeypatch.setattr(
        "app.config.settings.settings_encryption_key", Fernet.generate_key().decode()
    )
    with pytest.raises(PermanentFailure, match="Cannot send order 5001"):
        outbound._handle_send_confirmation(db, {"order_id": "5001"})
    assert db.query(OrderConfirmation).one().state == "pending"
