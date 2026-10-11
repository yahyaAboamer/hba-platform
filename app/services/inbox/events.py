"""Applying a callback from Meta: a customer's message, a tap, a tick
(ADR 0059, point 13).

The receiver (``app.api.webhooks``) checks the signature, writes the callback
down and answers at once. This is the work that follows, in the inbox lane.

**Applied once, however often Meta repeats it.** Three things make that true,
and each is the database's, not this code's good behaviour:

- the callback itself is stored by the SHA-256 of its bytes, so a repeat is
  never stored;
- a message is stored by WhatsApp's own id, so the same message inside a
  *different* callback is still stored once;
- a tick only ever moves a message forward: sent, delivered, read.

**Only our own number.** One Meta app can serve several numbers, and every
callback names the one it is about. Anything for another number is ignored.

Nothing here sends, tags an order or fetches a file. A tap is recorded as
the customer's answer; what follows from an answer - the order's tag, the
reply to a tap - is queued as work of its own.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.models.inbox import (
    InboxConnection,
    InboxConversation,
    InboxMedia,
    InboxMessage,
    MetaWebhookEvent,
    OrderConfirmation,
)
from app.services.inbox.meta import MEDIA_KINDS, failure_words
from app.services.jobs import JobKind, PermanentFailure
from app.worker import register_handler

logger = logging.getLogger(__name__)

#: What the three buttons on the confirmation carry: ``confirm_<order id>``.
#: The same shape n8n's message used, so a tap on an old message still counts.
_TAP = re.compile(r"(confirm|edit|cancel)_(\d{1,32})")
ANSWERS = {"confirm": "confirmed", "edit": "edit", "cancel": "cancelled"}
ANSWER_WORDS = {"confirmed": "Tapped Confirm", "edit": "Tapped Edit", "cancelled": "Tapped Cancel"}

#: A tick only moves forward. ``failed`` is handled apart: it is an end.
_RANK = {"queued": 0, "sent": 1, "delivered": 2, "read": 3}

#: The list's second line, for a message with no words of its own.
_PREVIEW = {
    "image": "Photo",
    "audio": "Voice note",
    "video": "Video",
    "document": "File",
    "sticker": "Sticker",
    "unsupported": "A message this inbox cannot show",
}

#: WhatsApp's own code for "this number cannot be reached" - no WhatsApp.
UNDELIVERABLE = "undeliverable"


def _when(raw: Any) -> datetime:
    """WhatsApp's clock: seconds since 1970, as text."""
    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return utcnow()


def _phone(raw: Any) -> str | None:
    """A WhatsApp id: digits, country code first. Anything else is refused."""
    digits = re.sub(r"\D", "", str(raw or ""))
    return digits if 6 <= len(digits) <= 20 else None


def _text(raw: Any, limit: int | None = None) -> str | None:
    if not isinstance(raw, str):
        return None
    # Postgres text cannot hold a NUL, and one in a message would fail the job.
    cleaned = raw.replace("\x00", "")
    return (cleaned[:limit] if limit else cleaned) or None


def _conversation(db: Session, phone: str, name: str | None) -> InboxConversation:
    """This customer's conversation, made if it is her first message."""
    db.execute(
        insert(InboxConversation)
        .values(phone=phone, name=name)
        .on_conflict_do_nothing(index_elements=["phone"])
    )
    conversation = db.scalar(select(InboxConversation).where(InboxConversation.phone == phone))
    # Her WhatsApp profile name, only where we have no name for her yet: the
    # name on her order is the better one, and is never overwritten by this.
    if name and not conversation.name:
        conversation.name = name
    return conversation


def _read_message(message: dict) -> dict:
    """Meta's message, as the columns of ours. Unknown kinds are kept, shown
    as unsupported, and never dropped: a customer wrote *something*."""
    kind = str(message.get("type") or "")
    fields: dict[str, Any] = {"kind": "unsupported", "body": None, "extra": None, "media": None}

    if kind == "text":
        fields.update(kind="text", body=_text((message.get("text") or {}).get("body")))
    elif kind in MEDIA_KINDS:
        media = message.get(kind) or {}
        fields.update(kind=kind, body=_text(media.get("caption")), media=media)
        if kind == "audio" and media.get("voice"):
            fields["extra"] = {"voice": True}
    elif kind == "button":
        button = message.get("button") or {}
        fields.update(
            kind="button",
            body=_text(button.get("text"), 200),
            extra={"payload": _text(button.get("payload"), 200)},
        )
    elif kind == "interactive":
        reply = (message.get("interactive") or {}).get("button_reply") or {}
        fields.update(
            kind="button",
            body=_text(reply.get("title"), 200),
            extra={"payload": _text(reply.get("id"), 200)},
        )
    elif kind == "reaction":
        reaction = message.get("reaction") or {}
        fields.update(
            kind="reaction",
            # No emoji means she took the reaction back.
            body=_text(reaction.get("emoji"), 16),
            reply_to=_text(reaction.get("message_id"), 200),
        )
    else:
        fields["extra"] = {"type": _text(kind, 40)}
    return fields


def _answer(fields: dict) -> tuple[str, str] | None:
    """``(answer, order id)`` if this message is a tap on a confirmation."""
    if fields["kind"] != "button":
        return None
    found = _TAP.fullmatch(str((fields["extra"] or {}).get("payload") or ""))
    return (ANSWERS[found.group(1)], found.group(2)) if found else None


def _her_order(db: Session, order_id: str, phone: str) -> OrderConfirmation | None:
    """The order a tap names, **only if it is this customer's**.

    The order number inside a tap is whatever the sender's phone sent. An
    ordinary WhatsApp sends back what our button carried; a modified one can
    send any number it likes, and an answer taken on trust would let a
    stranger tag somebody else's order Cancelled. So a tap counts only for an
    order whose own phone, read from Shopify when it was decided, is the
    phone the tap came from.

    No record of the order means no way to know whose it is, and so no
    answer. Orders n8n messaged have a record once its sends are imported,
    which the plan does before the switch.
    """
    row = db.scalar(
        select(OrderConfirmation).where(OrderConfirmation.shopify_order_id == order_id)
    )
    if row is None or not row.phone or _phone(row.phone) != phone:
        return None
    return row


def _record_answer(
    db: Session,
    row: OrderConfirmation,
    answer: str,
    at: datetime,
    conversation: InboxConversation,
    message_id: int,
) -> None:
    """Keep the customer's answer with her order. The latest tap wins.

    An order n8n messaged may say only what *would* have been sent. Her tap
    proves a confirmation reached her, so the order stands as sent.

    What follows from an answer is queued, not done here: the order's tag in
    Shopify, and the reply to a tap on Edit or Cancel. Each is its own job,
    so Shopify or WhatsApp being down never loses her answer.
    """
    # Imported here: both modules build on this one.
    from app.services.inbox.outbound import queue_auto_reply
    from app.services.inbox.tags import queue_tags

    if row.state in ("pending", "would_send"):
        row.state = "sent"
    if row.answered_at is None or at >= row.answered_at:
        row.answer = answer
        row.answered_at = at
    row.conversation_id = conversation.id
    row.updated_at = utcnow()
    db.flush()
    queue_tags(db, row)
    queue_auto_reply(db, message_id)


def apply_message(db: Session, message: dict, names: dict[str, str]) -> bool:
    """Store one message from a customer. False if it was already stored."""
    phone = _phone(message.get("from"))
    wa_message_id = _text(message.get("id"), 200)
    if phone is None or wa_message_id is None:
        return False

    fields = _read_message(message)
    occurred_at = _when(message.get("timestamp"))
    conversation = _conversation(db, phone, _text(names.get(phone), 120))
    answer = _answer(fields)
    order = _her_order(db, answer[1], phone) if answer else None
    if answer and order is None:
        # A tap naming an order that is not hers, or one we have no record
        # of. It stays in the chat for somebody to see; it changes no order.
        logger.warning("a tap named an order that is not the sender's; no answer recorded")
        fields["extra"] = {**(fields["extra"] or {}), "unmatched": True}
        answer = None

    message_id = db.execute(
        insert(InboxMessage)
        .values(
            conversation_id=conversation.id,
            direction="in",
            kind=fields["kind"],
            body=fields["body"],
            wa_message_id=wa_message_id,
            reply_to_wa_id=fields.get("reply_to")
            or _text((message.get("context") or {}).get("id"), 200),
            status="received",
            origin="customer",
            shopify_order_id=answer[1] if answer else None,
            extra=fields["extra"],
            occurred_at=occurred_at,
        )
        # The same message in a second callback: stored once.
        .on_conflict_do_nothing(index_elements=["wa_message_id"])
        .returning(InboxMessage.id)
    ).scalar()
    if message_id is None:
        return False

    media = fields["media"]
    if media is not None:
        size = media.get("file_size")
        db.add(
            InboxMedia(
                message_id=message_id,
                wa_media_id=_text(str(media.get("id") or ""), 200),
                mime_type=_text(media.get("mime_type"), 120),
                filename=_text(media.get("filename"), 255),
                sha256=_text(media.get("sha256"), 64),
                size_bytes=size if isinstance(size, int) and size >= 0 else None,
                state="pending",
            )
        )

    if answer:
        _record_answer(db, order, answer[0], occurred_at, conversation, message_id)

    # She wrote: free replies are allowed for 24 hours from now.
    if conversation.last_inbound_at is None or occurred_at > conversation.last_inbound_at:
        conversation.last_inbound_at = occurred_at
    # A reaction is not a message to answer: it does not head the list or
    # count as unread.
    if fields["kind"] != "reaction":
        conversation.unread_count = InboxConversation.unread_count + 1
        if conversation.last_message_at is None or occurred_at >= conversation.last_message_at:
            conversation.last_message_at = occurred_at
            conversation.last_direction = "in"
            conversation.last_preview = (
                ANSWER_WORDS[answer[0]] if answer else fields["body"] or _PREVIEW.get(fields["kind"])
            )
            if conversation.last_preview:
                conversation.last_preview = conversation.last_preview[:160]
    db.flush()
    return True


def apply_status(db: Session, status: dict) -> bool:
    """Move one of our messages along: sent, delivered, read, or failed.

    False when the tick is for a message we do not hold - one n8n sent - or
    would move a message backwards.
    """
    wa_message_id = _text(status.get("id"), 200)
    state = str(status.get("status") or "")
    if wa_message_id is None:
        return False
    message = db.scalar(select(InboxMessage).where(InboxMessage.wa_message_id == wa_message_id))
    if message is None or message.direction != "out":
        return False

    if state == "failed":
        errors = status.get("errors")
        code = errors[0].get("code") if isinstance(errors, list) and errors and isinstance(errors[0], dict) else None
        kind, words = failure_words(code)
        message.status = "failed"
        message.error = words[:300]
        # If it was an order's confirmation, the order has to say so: a
        # number with no WhatsApp is one somebody has to call.
        db.execute(
            update(OrderConfirmation)
            .where(OrderConfirmation.wa_message_id == wa_message_id)
            .values(
                state="no_whatsapp" if kind == UNDELIVERABLE else "failed",
                last_error=words[:300],
                updated_at=utcnow(),
            )
        )
        db.flush()
        order = db.scalar(
            select(OrderConfirmation).where(OrderConfirmation.wa_message_id == wa_message_id)
        )
        if order is not None:
            from app.services.inbox.tags import queue_tags

            db.refresh(order)
            # WA Sent becomes No WhatsApp, so the order shows it needs a call.
            queue_tags(db, order)
        return True

    if state not in _RANK or message.status == "failed":
        return False
    if _RANK[state] <= _RANK.get(message.status, -1):
        return False
    message.status = state
    db.flush()
    return True


def apply_event(db: Session, payload: Any) -> dict[str, int]:
    """Apply everything in one callback. Returns what it did, for the log."""
    done = {"messages": 0, "statuses": 0, "ignored": 0}
    connection = db.get(InboxConnection, 1)
    ours = connection.phone_number_id if connection else None
    if not isinstance(payload, dict) or ours is None:
        return done

    for entry in payload.get("entry") or []:
        for change in (entry.get("changes") if isinstance(entry, dict) else None) or []:
            value = change.get("value") if isinstance(change, dict) else None
            if not isinstance(value, dict) or change.get("field") != "messages":
                done["ignored"] += 1
                continue
            if str((value.get("metadata") or {}).get("phone_number_id") or "") != ours:
                # Another number on the same Meta app. Not ours to keep.
                done["ignored"] += 1
                continue
            names = {
                _phone(contact.get("wa_id")): (contact.get("profile") or {}).get("name")
                for contact in value.get("contacts") or []
                if isinstance(contact, dict)
            }
            for message in value.get("messages") or []:
                if isinstance(message, dict) and apply_message(db, message, names):
                    done["messages"] += 1
            for status in value.get("statuses") or []:
                if isinstance(status, dict) and apply_status(db, status):
                    done["statuses"] += 1
    return done


@register_handler(JobKind.INBOX_APPLY_EVENT)
def _handle_apply_event(db: Session, payload: dict) -> None:
    event_id = payload.get("event_id")
    if not isinstance(event_id, int):
        raise PermanentFailure(
            f"{JobKind.INBOX_APPLY_EVENT} requires an event_id; got payload keys "
            f"{sorted(payload)!r}"
        )
    event = db.get(MetaWebhookEvent, event_id)
    # Applied already - a lease that ran out and was taken again - or gone.
    if event is None or event.processed_at is not None:
        return
    done = apply_event(db, event.payload)
    event.processed_at = utcnow()
    event.attempts = MetaWebhookEvent.attempts + 1
    logger.info("callback %s applied: %s", event_id, done)
