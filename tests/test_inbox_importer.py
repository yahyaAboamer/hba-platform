"""The old chats brought over from n8n (ADR 0059; the plan's phase 5). The
rows here have the shape n8n's tables had on 12 October 2026. Every name,
number, order and message is made up.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.businesstime import utcnow
from app.models.inbox import InboxConversation, InboxMedia, InboxMessage, OrderConfirmation
from app.models.integration import BackgroundJob
from app.services.jobs import JobKind
from app.services.inbox import chats, importer
from app.services.inbox.importer import OldMessage, OldOrder, OldSend

NOW = utcnow()
NOUR = "201005550188"


def ms(minutes_ago: float) -> int:
    return int((NOW - timedelta(minutes=minutes_ago)).timestamp() * 1000)


def msg(id, text, *, direction="in", minutes_ago=60, phone=NOUR, name="Nour", read=True, media_id="", media_type=""):
    return OldMessage(id, phone, name, direction, text, ms(minutes_ago), read, media_id, media_type)


ORDER = OldOrder("5001", "#31044", "Nour", "1450.00", NOW - timedelta(minutes=125))


def nour_confirms() -> tuple[list, list, dict]:
    """An order sent, confirmed, thanked; then a question, a photo and a reaction."""
    messages = [
        msg(1, "Hi Nour, your order #31044 for 1450.00 EGP ...", direction="out", minutes_ago=119.9, name="Nour Adel"),
        msg(2, "👆 Confirm order", minutes_ago=110),
        msg(3, "Your order is confirmed ✅ Thank you!", direction="out", minutes_ago=110),
        msg(4, "When will it arrive?", minutes_ago=90, read=False),
        msg(5, "2 to 5 days", direction="out", minutes_ago=80),
        msg(6, "📷 Photo", minutes_ago=70, media_id="9001", media_type="image"),
        msg(7, "[reaction message]", minutes_ago=60),
    ]
    sends = [OldSend("wamid.SEND1", "5001", NOUR, ms(120))]
    return messages, sends, {"5001": ORDER}


def test_an_order_n8n_confirmed_is_recorded_as_sent_with_her_answer(db):
    report = importer.import_all(db, *nour_confirms(), now=NOW)
    row = db.scalar(select(OrderConfirmation).where(OrderConfirmation.shopify_order_id == "5001"))
    assert (row.state, row.answer, row.wa_message_id, row.phone) == ("sent", "confirmed", "wamid.SEND1", NOUR)
    assert (row.order_name, row.customer_name, row.total_text) == ("#31044", "Nour", "1450.00")
    assert report["orders_created"] == 1
    # Nothing is tagged again: n8n tagged it.
    kinds = set(db.scalars(select(BackgroundJob.kind)))
    assert JobKind.INBOX_TAG_ORDER not in kinds
    # The photo is fetched as one arriving now would be.
    assert JobKind.INBOX_FETCH_MEDIA in kinds


def test_the_chat_reads_as_it_did_with_the_tap_and_the_confirmation_in_place(db):
    importer.import_all(db, *nour_confirms(), now=NOW)
    conversation = db.scalar(select(InboxConversation).where(InboxConversation.phone == NOUR))
    # Her own name, where she wrote, over the one on our messages.
    assert conversation.name == "Nour"
    assert conversation.unread_count == 1
    assert (conversation.last_direction, conversation.last_preview) == ("in", "Photo")

    shown = chats.list_messages(db, conversation.id)["messages"]
    kinds = [(m["kind"], m["origin"]) for m in shown]
    assert kinds == [
        ("template", "automatic"),
        ("button", "customer"),
        ("text", "automatic"),
        ("text", "customer"),
        ("text", "imported"),
        ("image", "customer"),
        ("reaction", "customer"),
    ]
    template, tap = shown[0], shown[1]
    assert (template["buttons"], template["order_id"]) == (["Confirm", "Edit", "Cancel"], "5001")
    assert (tap["tapped"], tap["order_id"]) == ("confirmed", "5001")
    # A photo with no words of its own has none here, and waits to be copied.
    assert shown[5]["body"] is None
    assert shown[5]["media"]["state"] == "pending"


def test_running_it_again_doubles_nothing(db):
    importer.import_all(db, *nour_confirms(), now=NOW)
    again = importer.import_all(db, *nour_confirms(), now=NOW)
    assert again["messages_already_imported"] == 7
    assert again["orders_already_imported"] == 1
    assert db.scalar(select(InboxConversation).where(InboxConversation.phone == NOUR)).unread_count == 1
    assert len(db.scalars(select(InboxMessage)).all()) == 7


def test_a_not_delivered_note_marks_the_order_and_is_not_her_message(db):
    messages = [
        msg(1, "Hi Salma, your order ...", direction="out", minutes_ago=59.9, phone="201005550143"),
        msg(2, "⚠️ Not delivered — this number has no WhatsApp. Call the customer", minutes_ago=59, phone="201005550143"),
    ]
    sends = [OldSend("wamid.SEND2", "5002", "201005550143", ms(60))]
    report = importer.import_all(db, messages, sends, {}, now=NOW)
    row = db.scalar(select(OrderConfirmation).where(OrderConfirmation.shopify_order_id == "5002"))
    assert row.state == "no_whatsapp"
    assert report["notes_kept_as_order_state"] == 1
    assert len(db.scalars(select(InboxMessage)).all()) == 1


def test_a_tap_counts_for_the_order_sent_before_it_and_the_last_tap_wins(db):
    messages = [
        msg(1, "👆 Edit order", minutes_ago=200),
        msg(2, "👆 Cancel order", minutes_ago=100),
        msg(3, "👆 Confirm order", minutes_ago=90),
    ]
    sends = [OldSend("wamid.A", "6001", NOUR, ms(300)), OldSend("wamid.B", "6002", NOUR, ms(150))]
    importer.import_all(db, messages, sends, {}, now=NOW)
    answers = dict(db.execute(select(OrderConfirmation.shopify_order_id, OrderConfirmation.answer)).all())
    assert answers == {"6001": "edit", "6002": "confirmed"}


def test_an_order_the_platform_recorded_silently_is_moved_to_sent(db):
    db.add(OrderConfirmation(shopify_order_id="5001", state="would_send", phone=NOUR, order_name="#31044"))
    db.flush()
    report = importer.import_all(db, *nour_confirms(), now=NOW)
    row = db.scalar(select(OrderConfirmation).where(OrderConfirmation.shopify_order_id == "5001"))
    assert (row.state, row.wa_message_id) == ("sent", "wamid.SEND1")
    assert report["orders_moved_from_would_send"] == 1


def test_an_order_the_platform_sent_itself_is_left_alone(db):
    db.add(OrderConfirmation(shopify_order_id="5001", state="sent", phone=NOUR, wa_message_id="wamid.OURS"))
    db.flush()
    report = importer.import_all(db, *nour_confirms(), now=NOW)
    row = db.scalar(select(OrderConfirmation).where(OrderConfirmation.shopify_order_id == "5001"))
    assert row.wa_message_id == "wamid.OURS"
    assert report["orders_already_sent_here"] == 1


def test_an_old_file_is_gone_and_a_recent_one_waits_to_be_copied(db):
    messages = [
        msg(1, "🎤 Voice note", minutes_ago=60 * 24 * 40, media_id="old", media_type="audio"),
        msg(2, "This colour?", minutes_ago=60, media_id="new", media_type="image"),
    ]
    report = importer.import_all(db, messages, [], {}, now=NOW)
    states = dict(db.execute(select(InboxMedia.wa_media_id, InboxMedia.state)).all())
    assert states == {"old": "gone", "new": "pending"}
    assert (report["media_gone"], report["media_to_fetch"]) == (1, 1)
    voice, photo = db.scalars(select(InboxMessage).order_by(InboxMessage.occurred_at)).all()
    assert (voice.kind, voice.body, voice.extra) == ("audio", None, {"voice": True})
    # A caption is kept.
    assert photo.body == "This colour?"


@pytest.mark.parametrize(("raw", "phone"), [("2001005550188", "201005550188"), ("201005550188", "201005550188"), ("96650000000", "96650000000")])
def test_the_extra_zero_n8n_kept_after_the_country_code_is_dropped(raw, phone):
    assert importer.phone_of(raw) == phone


def test_shopifys_order_is_cut_down_to_what_the_message_said():
    order = importer.order_from_payload(
        5001,
        {"name": "#31044", "total_price": "1450.0", "created_at": "2026-10-11T12:00:00+03:00",
         "customer": {"first_name": " Nour ", "last_name": "Adel", "email": "x@example.com"}},
    )
    assert (order.name, order.first_name, order.total) == ("#31044", "Nour", "1450.00")
    assert order.placed_at.isoformat() == "2026-10-11T09:00:00+00:00"
    assert importer.order_from_payload("5002", {}).first_name == "there"


def test_the_check_counts_each_chat_against_n8n_leaving_out_its_notes(db):
    messages, sends, orders = nour_confirms()
    messages.append(msg(8, "⚠️ Not delivered — this number has no WhatsApp.", minutes_ago=50))
    importer.import_all(db, messages, sends, orders, now=NOW)
    assert importer.check(db, messages) == {
        "n8n_conversations": 1, "imported_conversations": 1,
        "n8n_messages": 7, "imported_messages": 7, "conversations_that_differ": 0,
    }
    # A message n8n has that was not brought over is a difference.
    messages.append(msg(9, "One more", minutes_ago=40))
    assert importer.check(db, messages)["conversations_that_differ"] == 1


def test_railways_address_is_read_with_the_driver_this_server_has():
    assert importer.source_url("postgresql://u:p@h:1/d") == "postgresql+psycopg://u:p@h:1/d"
    assert importer.source_url("postgres://u:p@h:1/d") == "postgresql+psycopg://u:p@h:1/d"
