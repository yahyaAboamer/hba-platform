"""Applying a callback from Meta (ADR 0059, point 13; the plan's phase 3).

The callbacks here are in the shape Meta sends them, with made-up numbers,
names and messages. Nothing is sent and Meta is never called.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.businesstime import utcnow
from app.models.inbox import (
    InboxConnection,
    InboxConversation,
    InboxMedia,
    InboxMessage,
    MetaWebhookEvent,
    OrderConfirmation,
)
from app.services.inbox import events
from app.services.inbox.events import apply_event
from app.services.jobs import PermanentFailure

NUMBER_ID = "100200300400500"
HER = "201005550188"
T0 = 1760180000  # seconds since 1970, as WhatsApp sends it


@pytest.fixture()
def connected(db):
    db.add(
        InboxConnection(
            id=1,
            phone_number_id=NUMBER_ID,
            business_account_id="777888999000111",
            access_token_encrypted="x",
            app_secret_encrypted="x",
            verify_token_encrypted="x",
            access_token_hint="",
            app_secret_hint="",
            verified_at=utcnow(),
        )
    )
    db.flush()


def _callback(*, messages=None, statuses=None, name="Nour Adel", number_id=NUMBER_ID, field="messages"):
    value = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "201005550100", "phone_number_id": number_id},
    }
    if messages is not None:
        value["contacts"] = [{"profile": {"name": name}, "wa_id": HER}]
        value["messages"] = messages
    if statuses is not None:
        value["statuses"] = statuses
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": field, "value": value}]}]}


def _text(body="Hello", wamid="wamid.IN1", at=T0, **extra):
    return {"from": HER, "id": wamid, "timestamp": str(at), "type": "text", "text": {"body": body}, **extra}


def _tap(payload, wamid="wamid.TAP1", at=T0, text="Confirm"):
    return {
        "from": HER, "id": wamid, "timestamp": str(at), "type": "button",
        "button": {"payload": payload, "text": text},
        "context": {"from": "201005550100", "id": "wamid.OURS"},
    }


def _ours(db, wamid="wamid.OUT1", status="sent"):
    conversation = InboxConversation(phone=HER)
    db.add(conversation)
    db.flush()
    message = InboxMessage(
        conversation_id=conversation.id, direction="out", kind="text", body="Hi",
        wa_message_id=wamid, status=status, origin="automatic", occurred_at=utcnow(),
    )
    db.add(message)
    db.flush()
    return message


def _status(state, wamid="wamid.OUT1", code=None):
    status = {"id": wamid, "status": state, "timestamp": str(T0), "recipient_id": HER}
    if code is not None:
        status["errors"] = [{"code": code, "title": "Message undeliverable", "message": f"to {HER}"}]
    return status


# ── A customer's message ──────────────────────────────────────────────────────


def test_her_first_message_opens_a_conversation(db, connected):
    done = apply_event(db, _callback(messages=[_text("Is the beige available?")]))
    assert done == {"messages": 1, "statuses": 0, "ignored": 0}

    conversation = db.query(InboxConversation).one()
    assert (conversation.phone, conversation.name) == (HER, "Nour Adel")
    assert conversation.unread_count == 1
    assert conversation.last_preview == "Is the beige available?"
    assert conversation.last_direction == "in"
    assert conversation.last_inbound_at == datetime.fromtimestamp(T0, tz=timezone.utc)

    message = db.query(InboxMessage).one()
    assert (message.direction, message.kind, message.status, message.origin) == (
        "in", "text", "received", "customer",
    )
    assert message.body == "Is the beige available?"
    assert message.sent_by is None


def test_a_second_message_joins_the_same_conversation(db, connected):
    apply_event(db, _callback(messages=[_text("One", "wamid.A", T0)]))
    apply_event(db, _callback(messages=[_text("Two", "wamid.B", T0 + 60)]))
    conversation = db.query(InboxConversation).one()
    db.refresh(conversation)
    assert conversation.unread_count == 2
    assert conversation.last_preview == "Two"
    assert db.query(InboxMessage).count() == 2


def test_the_same_message_in_two_callbacks_is_stored_once(db, connected):
    """Meta repeats. The second copy must not double the unread count either."""
    apply_event(db, _callback(messages=[_text()]))
    again = apply_event(db, _callback(messages=[_text()]))
    assert again["messages"] == 0
    assert db.query(InboxMessage).count() == 1
    conversation = db.query(InboxConversation).one()
    db.refresh(conversation)
    assert conversation.unread_count == 1


def test_an_older_message_arriving_late_does_not_head_the_list(db, connected):
    apply_event(db, _callback(messages=[_text("Newer", "wamid.B", T0 + 60)]))
    apply_event(db, _callback(messages=[_text("Older", "wamid.A", T0)]))
    conversation = db.query(InboxConversation).one()
    db.refresh(conversation)
    assert conversation.last_preview == "Newer"
    assert conversation.last_inbound_at == datetime.fromtimestamp(T0 + 60, tz=timezone.utc)


def test_the_name_on_record_is_not_replaced_by_her_profile_name(db, connected):
    db.add(InboxConversation(phone=HER, name="Nour (order #31044)"))
    db.flush()
    apply_event(db, _callback(messages=[_text()], name="nourrr 🌸"))
    assert db.query(InboxConversation).one().name == "Nour (order #31044)"


def test_a_reply_names_the_message_it_answers(db, connected):
    apply_event(db, _callback(messages=[_text(context={"id": "wamid.OURS"})]))
    assert db.query(InboxMessage).one().reply_to_wa_id == "wamid.OURS"


@pytest.mark.parametrize(
    ("kind", "media", "preview"),
    [
        ("image", {"id": "9001", "mime_type": "image/jpeg", "sha256": "abc", "caption": "This one"}, "This one"),
        ("image", {"id": "9001", "mime_type": "image/jpeg"}, "Photo"),
        ("audio", {"id": "9002", "mime_type": "audio/ogg; codecs=opus", "voice": True}, "Voice note"),
        ("video", {"id": "9003", "mime_type": "video/mp4"}, "Video"),
        ("document", {"id": "9004", "mime_type": "application/pdf", "filename": "receipt.pdf"}, "File"),
        ("sticker", {"id": "9005", "mime_type": "image/webp"}, "Sticker"),
    ],
)
def test_a_file_is_recorded_as_waiting_to_be_copied(db, connected, kind, media, preview):
    message = {"from": HER, "id": "wamid.M", "timestamp": str(T0), "type": kind, kind: media}
    apply_event(db, _callback(messages=[message]))

    stored = db.query(InboxMessage).one()
    assert stored.kind == kind
    file = db.query(InboxMedia).one()
    assert (file.message_id, file.wa_media_id, file.state) == (stored.id, media["id"], "pending")
    assert file.mime_type == media["mime_type"]
    assert file.storage_key is None
    assert db.query(InboxConversation).one().last_preview == preview


def test_a_voice_note_is_marked_as_one(db, connected):
    message = {"from": HER, "id": "wamid.V", "timestamp": str(T0), "type": "audio", "audio": {"id": "9002", "voice": True}}
    apply_event(db, _callback(messages=[message]))
    assert db.query(InboxMessage).one().extra == {"voice": True}


def test_a_kind_this_inbox_cannot_show_is_kept_not_dropped(db, connected):
    """She wrote something. It shows as that, and still counts as unread."""
    message = {"from": HER, "id": "wamid.L", "timestamp": str(T0), "type": "location", "location": {"latitude": 30.0, "longitude": 31.2}}
    apply_event(db, _callback(messages=[message]))
    stored = db.query(InboxMessage).one()
    assert (stored.kind, stored.extra) == ("unsupported", {"type": "location"})
    conversation = db.query(InboxConversation).one()
    assert conversation.last_preview == "A message this inbox cannot show"


def test_a_reaction_is_kept_but_is_not_a_message_to_answer(db, connected):
    apply_event(db, _callback(messages=[_text("Thanks", "wamid.A", T0)]))
    reaction = {"from": HER, "id": "wamid.R", "timestamp": str(T0 + 30), "type": "reaction", "reaction": {"message_id": "wamid.OURS", "emoji": "❤️"}}
    apply_event(db, _callback(messages=[reaction]))

    stored = db.query(InboxMessage).filter_by(kind="reaction").one()
    assert (stored.body, stored.reply_to_wa_id) == ("❤️", "wamid.OURS")
    conversation = db.query(InboxConversation).one()
    db.refresh(conversation)
    assert conversation.unread_count == 1
    assert conversation.last_preview == "Thanks"
    # It is still her writing: the 24 hours run from it.
    assert conversation.last_inbound_at == datetime.fromtimestamp(T0 + 30, tz=timezone.utc)


def test_a_message_with_a_nul_in_it_does_not_fail_the_job(db, connected):
    apply_event(db, _callback(messages=[_text("Hel\x00lo")]))
    assert db.query(InboxMessage).one().body == "Hello"


# ── A tap on the confirmation ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("payload", "answer", "preview"),
    [
        ("confirm_5001", "confirmed", "Tapped Confirm"),
        ("edit_5001", "edit", "Tapped Edit"),
        ("cancel_5001", "cancelled", "Tapped Cancel"),
    ],
)
def test_a_tap_is_recorded_as_her_answer(db, connected, payload, answer, preview):
    db.add(OrderConfirmation(shopify_order_id="5001", state="sent", wa_message_id="wamid.OURS"))
    db.flush()
    apply_event(db, _callback(messages=[_tap(payload)]))

    order = db.query(OrderConfirmation).one()
    conversation = db.query(InboxConversation).one()
    assert order.answer == answer
    assert order.answered_at == datetime.fromtimestamp(T0, tz=timezone.utc)
    assert order.conversation_id == conversation.id
    message = db.query(InboxMessage).one()
    assert (message.kind, message.shopify_order_id) == ("button", "5001")
    assert conversation.last_preview == preview


def _queued(db) -> list[tuple]:
    from sqlalchemy import text

    db.flush()
    return db.execute(text("SELECT kind, dedupe_key FROM background_job ORDER BY id")).all()


def test_an_answer_queues_the_orders_tag_and_the_reply(db, connected):
    """Queued, not done here: Shopify or WhatsApp being down must not lose
    her answer."""
    apply_event(db, _callback(messages=[_tap("edit_5001")]))
    tap = db.query(InboxMessage).one()
    assert _queued(db) == [
        ("inbox_tag_order", "inbox_tag_order:5001:Edit ✏️"),
        ("inbox_auto_reply", f"inbox_auto_reply:{tap.id}"),
    ]


def test_a_message_that_is_not_an_answer_queues_nothing(db, connected):
    apply_event(db, _callback(messages=[_text()]))
    assert _queued(db) == []


def test_a_confirmation_that_could_not_reach_her_queues_the_no_whatsapp_tag(db, connected):
    _ours(db, wamid="wamid.CONF")
    db.add(OrderConfirmation(shopify_order_id="5001", state="sent", wa_message_id="wamid.CONF"))
    db.flush()
    apply_event(db, _callback(statuses=[_status("failed", "wamid.CONF", 131026)]))
    assert _queued(db) == [("inbox_tag_order", "inbox_tag_order:5001:No WhatsApp 📵")]


def test_the_same_tap_works_as_a_newer_kind_of_button(db, connected):
    interactive = {
        "from": HER, "id": "wamid.I", "timestamp": str(T0), "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": {"id": "cancel_5001", "title": "Cancel"}},
    }
    apply_event(db, _callback(messages=[interactive]))
    assert db.query(OrderConfirmation).one().answer == "cancelled"


def test_the_latest_tap_wins(db, connected):
    apply_event(db, _callback(messages=[_tap("confirm_5001", "wamid.T1", T0)]))
    apply_event(db, _callback(messages=[_tap("cancel_5001", "wamid.T2", T0 + 300)]))
    # And an older one arriving late does not undo it.
    apply_event(db, _callback(messages=[_tap("edit_5001", "wamid.T0", T0 - 300)]))
    order = db.query(OrderConfirmation).one()
    db.refresh(order)
    assert order.answer == "cancelled"


def test_a_tap_on_a_message_n8n_sent_is_still_an_answer(db, connected):
    """After the switch, customers will tap confirmations the platform never
    sent. Each still has to count."""
    apply_event(db, _callback(messages=[_tap("confirm_7007")]))
    order = db.query(OrderConfirmation).one()
    assert (order.shopify_order_id, order.state, order.answer, order.phone) == (
        "7007", "sent", "confirmed", HER,
    )


def test_a_tap_shows_the_order_was_sent_even_if_we_only_recorded_would_send(db, connected):
    db.add(OrderConfirmation(shopify_order_id="5001", state="would_send"))
    db.flush()
    apply_event(db, _callback(messages=[_tap("confirm_5001")]))
    order = db.query(OrderConfirmation).one()
    db.refresh(order)
    assert (order.state, order.answer) == ("sent", "confirmed")


@pytest.mark.parametrize("payload", ["confirm_", "delete_5001", "confirm_abc", "confirm_5001; drop", ""])
def test_a_button_that_is_not_one_of_ours_changes_no_order(db, connected, payload):
    apply_event(db, _callback(messages=[_tap(payload)]))
    assert db.query(OrderConfirmation).count() == 0
    assert db.query(InboxMessage).one().kind == "button"


# ── Ticks ─────────────────────────────────────────────────────────────────────


def test_a_tick_moves_our_message_forward(db, connected):
    message = _ours(db)
    for state in ("delivered", "read"):
        apply_event(db, _callback(statuses=[_status(state)]))
        db.refresh(message)
        assert message.status == state


def test_a_tick_never_moves_a_message_backwards(db, connected):
    """Meta does not promise order: "delivered" can arrive after "read"."""
    message = _ours(db, status="read")
    done = apply_event(db, _callback(statuses=[_status("delivered"), _status("sent")]))
    db.refresh(message)
    assert message.status == "read"
    assert done["statuses"] == 0


def test_a_failure_is_said_in_our_words_and_names_no_number(db, connected):
    message = _ours(db)
    apply_event(db, _callback(statuses=[_status("failed", code=131047)]))
    db.refresh(message)
    assert message.status == "failed"
    assert message.error == "More than 24 hours have passed since the customer's last message (code 131047)"
    assert HER not in message.error


def test_a_failed_message_is_not_revived_by_a_late_tick(db, connected):
    message = _ours(db)
    apply_event(db, _callback(statuses=[_status("failed", code=131026)]))
    apply_event(db, _callback(statuses=[_status("delivered")]))
    db.refresh(message)
    assert message.status == "failed"


@pytest.mark.parametrize(
    ("code", "state"),
    [(131026, "no_whatsapp"), (131047, "failed"), (None, "failed")],
)
def test_a_confirmation_that_could_not_be_delivered_says_so_on_the_order(db, connected, code, state):
    """131026 is "this number cannot be reached": somebody has to call."""
    _ours(db, wamid="wamid.CONF")
    db.add(OrderConfirmation(shopify_order_id="5001", state="sent", wa_message_id="wamid.CONF"))
    db.flush()
    apply_event(db, _callback(statuses=[_status("failed", "wamid.CONF", code)]))
    order = db.query(OrderConfirmation).one()
    db.refresh(order)
    assert order.state == state
    assert order.last_error


def test_a_tick_for_a_message_we_do_not_hold_is_ignored(db, connected):
    """One n8n sent. Not an error, and nothing to store."""
    done = apply_event(db, _callback(statuses=[_status("delivered", "wamid.N8N")]))
    assert done["statuses"] == 0
    assert db.query(InboxMessage).count() == 0


def test_a_tick_cannot_change_a_customers_own_message(db, connected):
    apply_event(db, _callback(messages=[_text(wamid="wamid.HERS")]))
    apply_event(db, _callback(statuses=[_status("failed", "wamid.HERS", 131026)]))
    assert db.query(InboxMessage).one().status == "received"


# ── What is ignored ───────────────────────────────────────────────────────────


def test_a_callback_for_another_number_is_not_ours_to_keep(db, connected):
    done = apply_event(db, _callback(messages=[_text()], number_id="999888777666555"))
    assert done == {"messages": 0, "statuses": 0, "ignored": 1}
    assert db.query(InboxConversation).count() == 0


def test_nothing_is_applied_before_whatsapp_is_connected(db):
    assert apply_event(db, _callback(messages=[_text()]))["messages"] == 0
    assert db.query(InboxConversation).count() == 0


def test_a_change_that_is_not_about_messages_is_ignored(db, connected):
    done = apply_event(db, _callback(messages=[_text()], field="message_template_status_update"))
    assert done["ignored"] == 1
    assert db.query(InboxMessage).count() == 0


@pytest.mark.parametrize(
    "payload",
    [None, [], "text", {}, {"entry": None}, {"entry": [None]}, {"entry": [{"changes": [None]}]},
     {"entry": [{"changes": [{"field": "messages", "value": None}]}]}],
)
def test_a_callback_in_no_shape_we_know_applies_nothing_and_does_not_crash(db, connected, payload):
    assert apply_event(db, payload)["messages"] == 0


@pytest.mark.parametrize(
    "message",
    [
        {"id": "wamid.X", "timestamp": str(T0), "type": "text", "text": {"body": "no sender"}},
        {"from": HER, "timestamp": str(T0), "type": "text", "text": {"body": "no id"}},
        {"from": "not a number", "id": "wamid.X", "timestamp": str(T0), "type": "text", "text": {"body": "x"}},
    ],
)
def test_a_message_without_a_sender_or_an_id_is_not_stored(db, connected, message):
    assert apply_event(db, _callback(messages=[message]))["messages"] == 0
    assert db.query(InboxMessage).count() == 0


def test_a_missing_time_falls_back_to_now(db, connected):
    apply_event(db, _callback(messages=[{"from": HER, "id": "wamid.X", "type": "text", "text": {"body": "x"}}]))
    assert utcnow() - db.query(InboxMessage).one().occurred_at < timedelta(minutes=1)


# ── The job ───────────────────────────────────────────────────────────────────


def _stored(db, payload):
    event = MetaWebhookEvent(digest="d" * 64, payload=payload)
    db.add(event)
    db.flush()
    return event


def test_the_job_applies_a_stored_callback_and_marks_it_done(db, connected):
    event = _stored(db, _callback(messages=[_text()]))
    events._handle_apply_event(db, {"event_id": event.id})
    db.flush()
    db.refresh(event)
    assert event.processed_at is not None
    assert event.attempts == 1
    assert db.query(InboxMessage).count() == 1


def test_the_job_run_twice_applies_once(db, connected):
    """A lease that ran out, and a second worker taking the same job."""
    event = _stored(db, _callback(messages=[_text()]))
    events._handle_apply_event(db, {"event_id": event.id})
    db.flush()
    events._handle_apply_event(db, {"event_id": event.id})
    db.flush()
    db.refresh(event)
    assert event.attempts == 1
    assert db.query(InboxConversation).one().unread_count == 1


def test_the_job_for_a_callback_that_is_gone_finishes_quietly(db, connected):
    events._handle_apply_event(db, {"event_id": 987654})


def test_the_job_needs_an_event_id(db):
    with pytest.raises(PermanentFailure, match="requires an event_id"):
        events._handle_apply_event(db, {})


def test_applying_a_callback_sends_nothing_and_tags_nothing():
    """What follows from an answer is separate work; this module only records."""
    import inspect

    source = inspect.getsource(events)
    for reach in ("MetaClient", "send_text", "send_template", "tagsAdd", "ShopifyClient"):
        assert reach not in source
