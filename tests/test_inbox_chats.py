"""What the inbox's screens read and what staff do from them (ADR 0059; the
plan's phase 3). Meta is never called: a mock transport answers. Every name,
number and order here is made up.
"""

import json
from datetime import timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, text

from app.core.businesstime import utcnow
from app.models.audit import AuditEvent
from app.models.identity import UserAccount
from app.models.inbox import (
    InboxConversation,
    InboxMedia,
    InboxMessage,
    MetaWebhookEvent,
    OrderConfirmation,
)
from app.models.integration import BackgroundJob
from app.services.inbox import chats, connection, health, sending
from app.services.inbox.meta import MetaClient, NumberInfo
from app.services.inbox.outbound import NotSent

NOW = utcnow()


def _chat(db, phone, name=None, *, minutes_ago=5, unread=0, preview="Hello") -> InboxConversation:
    at = NOW - timedelta(minutes=minutes_ago)
    conversation = InboxConversation(
        phone=phone, name=name, last_message_at=at, last_inbound_at=at,
        last_preview=preview, last_direction="in", unread_count=unread,
    )
    db.add(conversation)
    db.flush()
    return conversation


def _message(db, conversation, body="Hello", *, direction="in", minutes_ago=5, **fields) -> InboxMessage:
    values = dict(
        conversation_id=conversation.id, direction=direction, kind="text", body=body,
        status="received" if direction == "in" else "sent",
        origin="customer" if direction == "in" else "automatic",
        occurred_at=NOW - timedelta(minutes=minutes_ago),
    )
    values.update(fields)
    message = InboxMessage(**values)
    db.add(message)
    db.flush()
    return message


def _order(db, order_id, conversation=None, *, state="sent", answer=None, **fields) -> OrderConfirmation:
    values = dict(
        shopify_order_id=order_id, order_name=f"#{order_id}", state=state, answer=answer,
        conversation_id=conversation.id if conversation else None,
        phone=conversation.phone if conversation else "201005550188",
        customer_name="Nour", total_text="1450.00", placed_at=NOW - timedelta(hours=2),
    )
    values.update(fields)
    row = OrderConfirmation(**values)
    db.add(row)
    db.flush()
    return row


def _staff(db) -> UserAccount:
    user = UserAccount(email="mariam@example.com", password_hash="x", status="active", display_name="Mariam")
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def may_send(db, monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.settings_encryption_key", Fernet.generate_key().decode()
    )
    connection.save_whatsapp(
        db, phone_number_id="100200300400500", business_account_id="777888999000111",
        access_token="EAAG-made-up-access-key-0000a1b2",
        app_secret="made-up-app-secret-000000009f3c", verify_token="made-up-check-word-0001",
        actor_id=None, actor_email=None,
        checker=lambda *args: NumberInfo("+20 100 555 0100", "HBA Wear", "GREEN"),
    )
    connection.set_sending(db, True, actor_id=None, actor_email=None)
    monkeypatch.setattr("app.config.settings.inbox_send_to_customers", True)


def _meta(asked: list) -> MetaClient:
    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(json.loads(request.read()))
        return httpx.Response(200, json={"messages": [{"id": f"wamid.SENT{len(asked)}"}]})

    return MetaClient(
        "EAAG-made-up-access-key-0000a1b2", "100200300400500",
        api_version="v23.0", transport=httpx.MockTransport(handler),
    )


# ── The list ──────────────────────────────────────────────────────────────────


def test_the_list_is_newest_first_with_what_the_row_shows(db):
    _chat(db, "201005550111", "Salma", minutes_ago=30)
    newest = _chat(db, "201005550188", "Nour", minutes_ago=2, unread=2, preview="Voice note")
    listed = chats.list_conversations(db)["conversations"]
    assert [row["name"] for row in listed] == ["Nour", "Salma"]
    assert listed[0] == {
        "id": newest.id, "phone": "201005550188", "name": "Nour",
        "last_message_at": newest.last_message_at.isoformat(), "last_preview": "Voice note",
        "last_direction": "in", "unread_count": 2, "window_open": True,
        "window_closes_at": (newest.last_inbound_at + timedelta(hours=24)).isoformat(),
        "answer": None,
    }


def test_every_conversation_is_reachable_a_page_at_a_time(db):
    """The old inbox stopped at 200. Here there is always a next page."""
    for index in range(7):
        _chat(db, f"20100555{index:04d}", f"Customer {index}", minutes_ago=index)
    seen, marker = [], None
    for _ in range(10):
        page = chats.list_conversations(db, before=marker, limit=3)
        seen += [row["name"] for row in page["conversations"]]
        marker = page["next"]
        if marker is None:
            break
    assert seen == [f"Customer {index}" for index in range(7)]


def test_two_chats_at_the_same_instant_are_neither_skipped_nor_repeated(db):
    for index in range(4):
        _chat(db, f"20100555{index:04d}", f"C{index}", minutes_ago=5)
    first = chats.list_conversations(db, limit=2)
    second = chats.list_conversations(db, before=first["next"], limit=2)
    names = [row["name"] for row in first["conversations"] + second["conversations"]]
    assert sorted(names) == ["C0", "C1", "C2", "C3"]


def test_the_views_narrow_the_list(db):
    plain = _chat(db, "201005550101", "Plain", minutes_ago=1)
    unread = _chat(db, "201005550102", "Unread", minutes_ago=2, unread=1)
    edit = _chat(db, "201005550103", "Edit", minutes_ago=3)
    cancelled = _chat(db, "201005550104", "Cancelled", minutes_ago=4)
    _order(db, "1", edit, answer="edit")
    _order(db, "2", cancelled, answer="cancelled")
    _order(db, "3", plain, answer="confirmed")

    def names(view):
        return [row["name"] for row in chats.list_conversations(db, view=view)["conversations"]]

    assert names("all") == ["Plain", "Unread", "Edit", "Cancelled"]
    assert names("unread") == ["Unread"]
    assert names("edit") == ["Edit"]
    assert names("cancelled") == ["Cancelled"]
    assert chats.counts(db) == {"all": 4, "unread": 1, "edit": 1}
    with pytest.raises(chats.Refused):
        chats.list_conversations(db, view="everything")


def test_the_flag_follows_her_most_recent_order(db):
    conversation = _chat(db, "201005550188", "Nour")
    _order(db, "1", conversation, answer="edit", created_at=NOW - timedelta(days=3))
    _order(db, "2", conversation, answer="confirmed", created_at=NOW)
    assert chats.list_conversations(db)["conversations"][0]["answer"] == "confirmed"
    assert chats.list_conversations(db, view="edit")["conversations"] == []


@pytest.mark.parametrize(
    ("q", "found"),
    [
        ("nour", ["Nour Adel"]),
        ("0100 555 0188", ["Nour Adel"]),
        ("+20 100 555 0188", ["Nour Adel"]),
        ("5550188", ["Nour Adel"]),
        ("#31044", ["Nour Adel"]),
        ("31044", ["Nour Adel"]),
        ("salma", ["Salma Hany"]),
        ("#99999", []),
        ("%", []),
        ("_", []),
    ],
)
def test_search_is_by_name_phone_or_order_number(db, q, found):
    nour = _chat(db, "201005550188", "Nour Adel", minutes_ago=1)
    _chat(db, "201105550199", "Salma Hany", minutes_ago=2)
    _order(db, "5001", nour, order_name="#31044")
    assert [row["name"] for row in chats.list_conversations(db, q=q)["conversations"]] == found


def test_a_page_marker_that_is_not_ours_is_refused(db):
    with pytest.raises(chats.Refused):
        chats.list_conversations(db, before="'; drop table")


# ── One chat ──────────────────────────────────────────────────────────────────


def test_a_chat_reads_oldest_to_newest_and_pages_backwards(db):
    conversation = _chat(db, "201005550188", "Nour")
    for index in range(6):
        _message(db, conversation, f"m{index}", minutes_ago=60 - index)
    last = chats.list_messages(db, conversation.id, limit=4)
    assert [m["body"] for m in last["messages"]] == ["m2", "m3", "m4", "m5"]
    earlier = chats.list_messages(db, conversation.id, before=last["earlier"], limit=4)
    assert [m["body"] for m in earlier["messages"]] == ["m0", "m1"]
    assert earlier["earlier"] is None


def test_a_message_says_who_sent_it(db):
    conversation = _chat(db, "201005550188", "Nour")
    mariam = _staff(db)
    _message(db, conversation, "Hi", minutes_ago=4)
    _message(db, conversation, "Automatic", direction="out", minutes_ago=3)
    _message(db, conversation, "Of course", direction="out", origin="staff", sent_by=mariam.id, minutes_ago=2)
    _message(db, conversation, "Old reply", direction="out", origin="imported", minutes_ago=1)
    senders = [(m["origin"], m["sender"]) for m in chats.list_messages(db, conversation.id)["messages"]]
    assert senders == [("customer", None), ("automatic", None), ("staff", "Mariam"), ("imported", None)]


def test_a_reply_shows_what_it_answers_and_a_file_shows_where_it_stands(db):
    conversation = _chat(db, "201005550188", "Nour")
    photo = _message(db, conversation, "This one", kind="image", wa_message_id="wamid.PHOTO", minutes_ago=3)
    db.add(InboxMedia(message_id=photo.id, wa_media_id="9001", mime_type="image/jpeg", state="pending"))
    stored = _message(db, conversation, None, kind="document", wa_message_id="wamid.DOC", minutes_ago=2)
    db.add(InboxMedia(message_id=stored.id, mime_type="application/pdf", filename="receipt.pdf",
                      state="stored", storage_key="inbox/1/receipt.pdf"))
    _message(db, conversation, "Beige?", direction="out", reply_to_wa_id="wamid.PHOTO", minutes_ago=1)
    db.flush()

    first, second, third = chats.list_messages(db, conversation.id)["messages"]
    assert (first["media"]["state"], first["media"]["url"]) == ("pending", None)
    assert second["media"]["url"] == f"/api/inbox/media/{second['media']['id']}"
    assert "storage_key" not in second["media"]
    assert third["reply_to"] == {"id": photo.id, "direction": "in", "kind": "image", "body": "This one"}


def test_a_tap_shows_as_her_answer_only_if_it_was_believed(db):
    conversation = _chat(db, "201005550188", "Nour")
    _message(db, conversation, "Edit", kind="button", extra={"payload": "edit_5001"},
             shopify_order_id="5001", minutes_ago=2)
    _message(db, conversation, "Cancel", kind="button",
             extra={"payload": "cancel_9999", "unmatched": True}, minutes_ago=1)
    believed, not_believed = chats.list_messages(db, conversation.id)["messages"]
    assert (believed["tapped"], not_believed["tapped"]) == ("edit", None)


def test_the_chat_carries_her_orders_newest_first(db):
    conversation = _chat(db, "201005550188", "Nour")
    _order(db, "1", conversation, answer="confirmed", created_at=NOW - timedelta(days=30))
    _order(db, "2", conversation, answer="edit", created_at=NOW)
    detail = chats.conversation_detail(db, conversation.id)
    assert [order["order"] for order in detail["orders"]] == ["#2", "#1"]
    assert detail["orders"][0]["tag"] == "Edit ✏️"
    assert detail["answer"] == "edit"
    with pytest.raises(chats.NotFound):
        chats.conversation_detail(db, 987654)


def test_marking_read_clears_the_count_and_names_her_last_message(db):
    conversation = _chat(db, "201005550188", "Nour", unread=3)
    _message(db, conversation, "first", wa_message_id="wamid.A", minutes_ago=5)
    _message(db, conversation, "last", wa_message_id="wamid.B", minutes_ago=1)
    _message(db, conversation, "ours", direction="out", wa_message_id="wamid.OURS", minutes_ago=0)
    assert chats.mark_read(db, conversation.id) == "wamid.B"
    assert conversation.unread_count == 0


# ── What staff do ─────────────────────────────────────────────────────────────


def test_a_reply_goes_out_under_the_staff_members_name(db, may_send):
    asked: list = []
    conversation = _chat(db, "201005550188", "Nour")
    hers = _message(db, conversation, "This one", wa_message_id="wamid.HERS")
    mariam = _staff(db)
    sent = chats.reply(db, conversation.id, "  Of course.  ", actor_id=mariam.id,
                       reply_to=hers.id, client=_meta(asked))
    assert asked[0]["text"]["body"] == "Of course."
    assert asked[0]["context"] == {"message_id": "wamid.HERS"}
    assert (sent["origin"], sent["sender"], sent["status"]) == ("staff", "Mariam", "sent")


@pytest.mark.parametrize(("body", "words"), [("", "Type a message"), ("   ", "Type a message"), ("x" * 4097, "longer than WhatsApp allows")])
def test_a_reply_that_cannot_be_sent_as_typed_is_refused_before_asking(db, may_send, body, words):
    asked: list = []
    conversation = _chat(db, "201005550188", "Nour")
    with pytest.raises(chats.Refused, match=words):
        chats.reply(db, conversation.id, body, actor_id=_staff(db).id, client=_meta(asked))
    assert asked == []


def test_a_reply_cannot_quote_another_chats_message(db, may_send):
    mine = _chat(db, "201005550188", "Nour")
    other = _chat(db, "201105550199", "Salma")
    theirs = _message(db, other, "private", wa_message_id="wamid.THEIRS")
    with pytest.raises(chats.Refused, match="not one in this chat"):
        chats.reply(db, mine.id, "Hi", actor_id=_staff(db).id, reply_to=theirs.id, client=_meta([]))


def test_staff_are_held_to_the_same_rule_on_who_may_be_messaged(db):
    """No WhatsApp connection here: the screen cannot send round the rule."""
    asked: list = []
    conversation = _chat(db, "201005550188", "Nour")
    with pytest.raises(NotSent, match=sending.NOT_CONNECTED):
        chats.reply(db, conversation.id, "Hi", actor_id=_staff(db).id, client=_meta(asked))
    assert asked == []


def test_a_reaction_goes_to_her_message_and_does_not_head_the_list(db, may_send):
    asked: list = []
    conversation = _chat(db, "201005550188", "Nour", preview="Thanks")
    hers = _message(db, conversation, "Thanks", wa_message_id="wamid.HERS")
    sent = chats.react(db, conversation.id, hers.id, "❤️", actor_id=_staff(db).id, client=_meta(asked))
    assert asked[0]["reaction"] == {"message_id": "wamid.HERS", "emoji": "❤️"}
    assert (sent["kind"], sent["body"]) == ("reaction", "❤️")
    assert conversation.last_preview == "Thanks"


# ── Send again, and setting her answer ────────────────────────────────────────


def _queued(db) -> list[str]:
    db.flush()
    return [row[0] for row in db.execute(text("SELECT kind FROM background_job ORDER BY id")).all()]


def test_an_order_that_failed_is_queued_again_and_the_act_is_audited(db, may_send):
    row = _order(db, "5001", state="failed", last_error="WhatsApp did not answer", attempts=5)
    mariam = _staff(db)
    order = chats.send_again(db, "5001", actor_id=mariam.id, actor_email=mariam.email)
    assert (row.state, row.attempts, row.last_error) == ("pending", 0, None)
    assert order["state"] == "pending"
    assert _queued(db) == ["inbox_send_confirmation"]
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "inbox.confirmation_resent"))
    assert (event.subject, event.actor_id) == ("order:5001", mariam.id)
    assert event.after_json == {"state": "pending", "order": "#5001"}


@pytest.mark.parametrize(
    "fields",
    [
        {"state": "sent"},
        {"state": "pending"},
        {"state": "sending"},
        {"state": "failed", "wa_message_id": "wamid.ALREADY"},
    ],
)
def test_an_order_that_has_or_may_have_its_message_is_never_sent_again(db, may_send, fields):
    """How a second message would start. Refused, and nothing is queued."""
    _order(db, "5001", **fields)
    with pytest.raises(chats.Refused, match="already has its confirmation"):
        chats.send_again(db, "5001", actor_id=_staff(db).id, actor_email=None)
    assert _queued(db) == []


@pytest.mark.parametrize("state", ["no_whatsapp", "no_phone", "bad_phone", "not_needed"])
def test_an_order_that_cannot_be_messaged_is_refused(db, may_send, state):
    _order(db, "5001", state=state, phone=None if state == "no_phone" else "201005550188")
    with pytest.raises(chats.Refused, match="cannot be messaged"):
        chats.send_again(db, "5001", actor_id=_staff(db).id, actor_email=None)
    assert _queued(db) == []


def test_send_again_is_held_to_the_rule_on_who_may_be_messaged(db):
    _order(db, "5001", state="failed")
    with pytest.raises(chats.Refused, match=sending.NOT_CONNECTED):
        chats.send_again(db, "5001", actor_id=_staff(db).id, actor_email=None)
    with pytest.raises(chats.NotFound):
        chats.send_again(db, "9999", actor_id=1, actor_email=None)


def test_staff_can_record_her_answer_which_changes_the_tag_and_is_audited(db):
    row = _order(db, "5001", state="sent")
    mariam = _staff(db)
    order = chats.set_answer(db, "5001", "confirmed", actor_id=mariam.id, actor_email=mariam.email)
    assert (row.answer, order["tag"]) == ("confirmed", "Confirmed ✅")
    assert _queued(db) == ["inbox_tag_order"]
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "inbox.answer_set"))
    assert (event.before_json, event.after_json) == (
        {"answer": None}, {"answer": "confirmed", "order": "#5001"},
    )
    with pytest.raises(chats.Refused):
        chats.set_answer(db, "5001", "refunded", actor_id=mariam.id, actor_email=None)


# ── The Confirmations screen ──────────────────────────────────────────────────


def test_the_cards_count_cash_on_delivery_orders_by_where_they_stand(db):
    _order(db, "1", state="sent")
    _order(db, "2", state="sent", answer="confirmed")
    _order(db, "3", state="sent", answer="edit")
    _order(db, "4", state="sent", answer="cancelled")
    _order(db, "5", state="failed", last_error="WhatsApp did not answer")
    _order(db, "6", state="would_send")
    _order(db, "7", state="no_whatsapp")
    _order(db, "8", state="not_needed")
    _order(db, "9", state="sent", placed_at=NOW - timedelta(days=30))

    body = chats.confirmations(db, tile="not_sent")
    assert body["total"] == 7
    assert body["tiles"] == {
        "waiting": 1, "edit": 1, "cancelled": 1, "not_sent": 2, "no_whatsapp": 1, "confirmed": 1,
    }
    listed = {order["order"]: order for order in body["orders"]}
    assert set(listed) == {"#5", "#6"}
    assert listed["#5"]["why"] == "WhatsApp did not answer"
    assert listed["#6"]["why"] == chats.SENDING_WAS_OFF
    assert listed["#5"]["can_send_again"] is True
    assert listed["#5"]["customer"] == "Nour"


# ── Operations' WhatsApp tab ──────────────────────────────────────────────────


def test_operations_sees_what_went_wrong_and_no_customer_details(db):
    _order(db, "1", state="failed", last_error="WhatsApp did not answer")
    _order(db, "2", state="no_whatsapp")
    _order(db, "3", state="no_phone", phone=None)
    _order(db, "4", state="bad_phone")
    _order(db, "5", state="sent", sent_at=NOW - timedelta(hours=30))
    _order(db, "6", state="sent", sent_at=NOW - timedelta(hours=2))
    _order(db, "7", state="sent", answer="confirmed", sent_at=NOW - timedelta(hours=30))
    db.add(BackgroundJob(kind="inbox_tag_order", payload={"order_id": "7"}, status="failed"))
    db.flush()

    body = health.summary(db, card="failed")
    assert body["cards"] == {
        "failed": 1, "no_whatsapp": 1, "never_messaged": 2, "answers_not_recorded": 1, "waiting": 1,
    }
    assert body["connected"] is False and body["last_heard_at"] is None
    # Placed two hours ago: today, or yesterday if Cairo's midnight fell between.
    assert body["orders"][0].pop("waiting_days") in (0, 1)
    assert body["orders"] == [{
        "order_id": "1", "order": "#1", "placed_at": (NOW - timedelta(hours=2)).isoformat(),
        "why": "WhatsApp did not answer", "state": "failed", "answer": None, "tag": None,
    }]
    everything = json.dumps([health.summary(db, card=card) for card in health.CARDS])
    assert "201005550188" not in everything
    assert "Nour" not in everything
    assert [o["order"] for o in health.summary(db, card="answers_not_recorded")["orders"]] == ["#7"]


def test_operations_shows_how_long_an_order_has_waited_and_the_tag_it_carries(db):
    _order(db, "1", state="no_whatsapp", placed_at=NOW - timedelta(days=3))
    _order(db, "2", state="sent", sent_at=NOW - timedelta(hours=30), placed_at=NOW - timedelta(days=2))

    [called] = health.summary(db, card="no_whatsapp")["orders"]
    assert called["waiting_days"] == 3
    assert called["tag"] == "No WhatsApp 📵"
    assert health.summary(db, card="waiting")["orders"][0]["tag"] == "WA Sent 📤"


def test_whatsapp_is_quiet_only_when_something_sent_went_unanswered(db):
    """Nothing arriving at night is not a fault. A send WhatsApp never
    acknowledged is."""
    nour = _chat(db, "201005550188", "Nour")
    assert health.summary(db)["quiet_since"] is None

    # Sent a moment ago: too soon to say.
    sent = _message(db, nour, "Hello", direction="out", minutes_ago=2, wa_message_id="wamid.A")
    assert health.summary(db)["quiet_since"] is None

    # Sent forty minutes ago, and nothing has ever been heard.
    sent.occurred_at = NOW - timedelta(minutes=40)
    db.flush()
    assert health.summary(db)["quiet_since"] == (NOW - timedelta(minutes=40)).isoformat()

    # Heard from before that send, and not since.
    db.add(MetaWebhookEvent(
        digest="a" * 64, payload={}, received_at=NOW - timedelta(minutes=50),
    ))
    db.flush()
    assert health.summary(db)["quiet_since"] == (NOW - timedelta(minutes=50)).isoformat()

    # Heard from after it: all is well.
    db.add(MetaWebhookEvent(
        digest="b" * 64, payload={}, received_at=NOW - timedelta(minutes=39),
    ))
    db.flush()
    assert health.summary(db)["quiet_since"] is None


def test_a_message_that_never_reached_whatsapp_does_not_call_it_quiet(db):
    nour = _chat(db, "201005550188", "Nour")
    _message(db, nour, "Hello", direction="out", minutes_ago=40, status="failed")
    assert health.summary(db)["quiet_since"] is None


def test_each_order_links_to_shopify_where_it_is_changed(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.shopify_shop_domain", "hbawear.myshopify.com")
    nour = _chat(db, "201005550188", "Nour")
    _order(db, "5001", nour, state="no_whatsapp")

    link = "https://hbawear.myshopify.com/admin/orders/5001"
    assert chats.conversation_detail(db, nour.id)["orders"][0]["admin_url"] == link
    [listed] = chats.confirmations(db, tile="no_whatsapp")["orders"]
    assert listed["admin_url"] == link
    # A number with no WhatsApp is a call: the Confirmations screen shows it.
    assert listed["phone"] == "201005550188"


def test_no_link_is_invented_when_no_store_is_connected(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.shopify_shop_domain", "")
    _order(db, "5001", state="failed")
    assert chats.confirmations(db, tile="not_sent")["orders"][0]["admin_url"] is None


# ── The approved messages, once her 24 hours have passed ──────────────────────

REACH_YOU = {
    "name": "we_tried_to_reach_you", "language": "en", "status": "APPROVED", "category": "UTILITY",
    "components": [{"type": "BODY", "text": "We tried to reach you about your order."}],
}
CONFIRMATION = {
    "name": "order_confirmation", "language": "en", "status": "APPROVED", "category": "UTILITY",
    "components": [
        {"type": "BODY", "text": "Hi {{1}}, thank you for your order {{2}}. Your total is {{3}}."},
        {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Confirm"}]},
    ],
}
WITH_A_PICTURE = {
    "name": "new_collection", "language": "en", "status": "APPROVED", "category": "MARKETING",
    "components": [{"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "New in."}],
}
NOT_APPROVED = {**REACH_YOU, "name": "still_in_review", "status": "PENDING"}


def test_only_an_approved_message_that_needs_nothing_filled_in_can_be_picked():
    listed = {t["name"]: t for t in chats.describe_templates(
        [REACH_YOU, CONFIRMATION, WITH_A_PICTURE, NOT_APPROVED, "not a template"]
    )}
    assert set(listed) == {"we_tried_to_reach_you", "order_confirmation", "new_collection"}
    assert listed["we_tried_to_reach_you"] == {
        "name": "we_tried_to_reach_you", "language": "en", "category": "UTILITY",
        "body": "We tried to reach you about your order.", "sendable": True, "why_not": None,
    }
    # The confirmation is filled in from an order, and goes out on its own.
    assert listed["order_confirmation"]["sendable"] is False
    assert "order" in listed["order_confirmation"]["why_not"]
    assert listed["new_collection"]["sendable"] is False


def test_an_approved_message_reaches_her_after_her_24_hours_under_the_senders_name(db, may_send):
    asked: list = []
    silent = _chat(db, "201005550188", "Nour", minutes_ago=60 * 30)
    mariam = _staff(db)

    sent = chats.send_template(
        db, silent.id, "we_tried_to_reach_you", "en",
        found=[REACH_YOU, CONFIRMATION], actor_id=mariam.id, client=_meta(asked),
    )

    assert asked[0]["type"] == "template"
    assert asked[0]["template"] == {"name": "we_tried_to_reach_you", "language": {"code": "en"}}
    assert (sent["kind"], sent["origin"], sent["sender"], sent["status"]) == (
        "template", "staff", "Mariam", "sent",
    )
    assert sent["body"] == "We tried to reach you about your order."
    assert sent["template"] == "we_tried_to_reach_you"
    db.refresh(silent)
    assert silent.last_preview == "We tried to reach you about your order."


@pytest.mark.parametrize(("name", "words"), [
    ("order_confirmation", "cannot be sent from here"),
    ("still_in_review", "not one of the approved messages"),
    ("made_up", "not one of the approved messages"),
])
def test_a_message_that_is_not_approved_or_needs_filling_in_is_never_sent(db, may_send, name, words):
    asked: list = []
    silent = _chat(db, "201005550188", "Nour", minutes_ago=60 * 30)
    with pytest.raises(chats.Refused, match=words):
        chats.send_template(
            db, silent.id, name, "en", found=[REACH_YOU, CONFIRMATION, NOT_APPROVED],
            actor_id=_staff(db).id, client=_meta(asked),
        )
    assert asked == []


def test_an_approved_message_is_held_to_the_rule_on_who_may_be_messaged(db):
    silent = _chat(db, "201005550188", "Nour", minutes_ago=60 * 30)
    with pytest.raises(NotSent):
        chats.send_template(
            db, silent.id, "we_tried_to_reach_you", "en", found=[REACH_YOU],
            actor_id=_staff(db).id, client=_meta([]),
        )
