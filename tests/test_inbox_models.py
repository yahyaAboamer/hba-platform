"""The inbox's tables (ADR 0059).

Like `test_identity_models`, these exercise the database's own rules, which
hold however a row is written.
"""

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.core.businesstime import utcnow
from app.db import engine
from app.shared.models.identity import RoleAssignment, UserAccount
from app.modules.inbox.models import (
    InboxConnection,
    InboxConversation,
    InboxMedia,
    InboxMessage,
    MetaWebhookEvent,
    OrderConfirmation,
)

PHONE = "201005550188"


def _conversation(db, phone=PHONE):
    conversation = InboxConversation(phone=phone, name="Nour")
    db.add(conversation)
    db.flush()
    return conversation


def _message(db, conversation, **fields):
    values = dict(
        conversation_id=conversation.id,
        direction="in",
        kind="text",
        body="Hello",
        status="received",
        origin="customer",
        occurred_at=utcnow(),
    )
    values.update(fields)
    message = InboxMessage(**values)
    db.add(message)
    db.flush()
    return message


# ── Chats ─────────────────────────────────────────────────────────────────────


def test_one_phone_is_one_conversation(db):
    _conversation(db)
    db.add(InboxConversation(phone=PHONE))
    with pytest.raises(IntegrityError):
        db.flush()


def test_a_repeated_callback_cannot_store_a_message_twice(db):
    conversation = _conversation(db)
    _message(db, conversation, wa_message_id="wamid.ONE")
    with pytest.raises(IntegrityError):
        _message(db, conversation, wa_message_id="wamid.ONE")


def test_an_import_run_twice_cannot_double_a_message(db):
    conversation = _conversation(db)
    _message(db, conversation, origin="imported", source_ref="n8n:41")
    with pytest.raises(IntegrityError):
        _message(db, conversation, origin="imported", source_ref="n8n:41")


@pytest.mark.parametrize(
    "fields",
    [
        {"direction": "up"},
        {"kind": "telepathy"},
        {"status": "lost"},
        {"origin": "nobody"},
    ],
)
def test_a_message_outside_the_known_values_is_refused(db, fields):
    conversation = _conversation(db)
    with pytest.raises(IntegrityError):
        _message(db, conversation, **fields)


def test_only_a_staff_message_carries_a_sender(db):
    """An automatic reply or a customer's message has nobody's name on it."""
    conversation = _conversation(db)
    user = UserAccount(email="mariam@example.com", password_hash="x", status="active")
    db.add(user)
    db.flush()
    db.add(RoleAssignment(user_account_id=user.id, role="customer_service"))
    _message(db, conversation, direction="out", status="sent", origin="staff", sent_by=user.id)
    with pytest.raises(IntegrityError):
        _message(
            db, conversation, direction="out", status="sent", origin="automatic", sent_by=user.id
        )


def test_deleting_a_conversation_takes_its_messages_and_files(db):
    conversation = _conversation(db)
    message = _message(db, conversation, kind="image")
    db.add(InboxMedia(message_id=message.id, wa_media_id="111", state="pending"))
    db.flush()
    db.delete(conversation)
    db.flush()
    db.expire_all()
    assert db.query(InboxMessage).count() == 0
    assert db.query(InboxMedia).count() == 0


# ── Files ─────────────────────────────────────────────────────────────────────


def test_a_stored_file_must_say_where_it_is(db):
    message = _message(db, _conversation(db), kind="image")
    db.add(InboxMedia(message_id=message.id, state="stored"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_a_file_that_is_not_stored_has_no_place(db):
    message = _message(db, _conversation(db), kind="image")
    db.add(InboxMedia(message_id=message.id, state="gone", storage_key="inbox/1/photo.jpg"))
    with pytest.raises(IntegrityError):
        db.flush()


# ── Confirmations ─────────────────────────────────────────────────────────────


def test_an_order_has_one_confirmation(db):
    """What stops a second message, however often the webhook arrives."""
    db.add(OrderConfirmation(shopify_order_id="5001", state="sent"))
    db.flush()
    db.add(OrderConfirmation(shopify_order_id="5001", state="pending"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_a_paid_order_is_finished_not_failed(db):
    """n8n called these failed; here it is a state of its own."""
    db.add(OrderConfirmation(shopify_order_id="5002", state="not_needed"))
    db.flush()


@pytest.mark.parametrize("fields", [{"state": "maybe"}, {"answer": "perhaps"}])
def test_a_confirmation_outside_the_known_values_is_refused(db, fields):
    values = {"shopify_order_id": "5003", "state": "pending"} | fields
    db.add(OrderConfirmation(**values))
    with pytest.raises(IntegrityError):
        db.flush()


# ── Callbacks and the connection ──────────────────────────────────────────────


def test_a_callback_meta_repeats_is_stored_once(db):
    db.add(MetaWebhookEvent(digest="a" * 64, payload={"entry": []}))
    db.flush()
    db.add(MetaWebhookEvent(digest="a" * 64, payload={"entry": []}))
    with pytest.raises(IntegrityError):
        db.flush()


def test_there_is_one_whatsapp_connection_and_it_starts_with_sending_off(db):
    values = dict(
        phone_number_id="1",
        business_account_id="2",
        access_token_encrypted="x",
        app_secret_encrypted="x",
        verify_token_encrypted="x",
        access_token_hint="",
        app_secret_hint="",
        verified_at=utcnow(),
    )
    row = InboxConnection(id=1, **values)
    db.add(row)
    db.flush()
    db.refresh(row)
    assert row.sending_enabled is False
    db.add(InboxConnection(id=2, **values))
    with pytest.raises(IntegrityError):
        db.flush()


# ── Customer data stays here ──────────────────────────────────────────────────


def test_customer_details_live_only_in_the_inbox_tables():
    """ADR 0059, point 9. The inbox holds a phone and a name; the order
    tables and Operations still hold neither."""
    inspector = inspect(engine)
    personal = {"phone", "name", "customer_name", "body", "display_number", "verified_name"}
    holding = {
        table
        for table in inspector.get_table_names()
        if table.startswith(("order_index", "attributed_order", "ops_"))
        and personal & {column["name"] for column in inspector.get_columns(table)}
    }
    assert holding == set()
