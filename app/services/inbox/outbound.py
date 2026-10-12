"""Every message the platform sends goes out through here (ADR 0059).

One door, so the rules cannot be skipped by a second one:

- **Nobody is messaged unless this server may message them**
  (``sending.refusal``): WhatsApp connected, sending turned on in Settings,
  and either the server has been told it may message customers or the number
  is one of its test numbers. Refused, nothing is sent and nothing is
  recorded as sent.
- **A free message only inside the 24 hours** after the customer last wrote.
  Outside it WhatsApp accepts only an approved message, and refuses the rest.
- **An order's confirmation is sent at most once.** The order is claimed in a
  transaction of its own before WhatsApp is asked, so a crash after WhatsApp
  accepted the message leaves the order ``sending`` - which is never sent
  again on its own.

What is sent from here today: the order confirmation, and the two automatic
replies to a tap (ADR 0059, point 8). A tap on Confirm gets no reply.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.models.inbox import InboxConversation, InboxMessage, OrderConfirmation
from app.services.inbox import connection, sending, tags
from app.services.inbox.events import ANSWERS, _TAP, _conversation
from app.services.inbox.meta import MetaClient, MetaError
from app.services.jobs import JobKind, PermanentFailure, enqueue
from app.worker import register_handler

logger = logging.getLogger(__name__)

#: How long after her last message a free reply is allowed.
WINDOW = timedelta(hours=24)

#: The approved message, by the name and language Meta holds it under.
TEMPLATE = "order_confirmation"
LANGUAGE = "en"
BUTTONS = ("confirm", "edit", "cancel")

#: What is said after a tap. Nothing after Confirm: WhatsApp already shows
#: her own tap, and it was 880 of the 1,020 automatic replies a month.
REPLIES = {
    "edit": "What would you like to change? ✏️ Type it here and our team will help you.",
    # The order is only tagged, not cancelled, until somebody acts on it.
    "cancelled": "We received your cancellation request ❌",
}

#: A reply to a tap is only worth sending while it is still an answer to it.
REPLY_WHILE_FRESH = timedelta(minutes=15)

#: A confirmation WhatsApp did not take is tried this many times in all.
MAX_ATTEMPTS = 5
RETRY_AFTER = (
    timedelta(minutes=1),
    timedelta(minutes=2),
    timedelta(minutes=5),
    timedelta(minutes=15),
)

#: An order still ``sending`` after this long was interrupted.
INTERRUPTED_AFTER = timedelta(minutes=10)

WINDOW_CLOSED = (
    "More than 24 hours have passed since her last message. "
    "WhatsApp only allows an approved message now."
)
INTERRUPTED = (
    "Interrupted while sending. Check the chat in WhatsApp before sending again: "
    "the message may have gone out."
)


class NotSent(Exception):
    """Why a message was not sent. The text is safe to show."""

    def __init__(self, message: str, *, kind: str = "refused") -> None:
        super().__init__(message)
        self.kind = kind


def window_open(conversation: InboxConversation, now: datetime | None = None) -> bool:
    """Whether a free reply is allowed: she wrote within the last 24 hours."""
    if conversation.last_inbound_at is None:
        return False
    return (now or utcnow()) - conversation.last_inbound_at < WINDOW


def _client(db: Session) -> MetaClient:
    keys = connection.whatsapp(db)
    if keys is None:
        raise NotSent(sending.NOT_CONNECTED, kind="not_connected")
    return MetaClient(keys.access_token, keys.phone_number_id)


def record_outbound(
    db: Session,
    conversation: InboxConversation,
    *,
    kind: str,
    body: str | None,
    origin: str,
    status: str,
    wa_message_id: str | None = None,
    error: str | None = None,
    sent_by: int | None = None,
    template_name: str | None = None,
    extra: dict[str, Any] | None = None,
    reply_to: str | None = None,
    order_id: str | None = None,
    source_ref: str | None = None,
    heads_list: bool = True,
) -> InboxMessage:
    """Put one of our messages in the chat, sent or refused.

    ``heads_list`` is off for a reaction: it is not a message, and does not
    become the conversation's last line.
    """
    now = utcnow()
    message = InboxMessage(
        conversation_id=conversation.id,
        direction="out",
        kind=kind,
        body=body,
        wa_message_id=wa_message_id,
        reply_to_wa_id=reply_to,
        status=status,
        error=error[:300] if error else None,
        origin=origin,
        sent_by=sent_by,
        shopify_order_id=order_id,
        template_name=template_name,
        extra=extra,
        occurred_at=now,
        source_ref=source_ref,
    )
    db.add(message)
    if heads_list:
        conversation.last_message_at = now
        conversation.last_direction = "out"
        conversation.last_preview = (body or "")[:160] or None
    db.flush()
    return message


def send_file(
    db: Session,
    conversation: InboxConversation,
    *,
    kind: str,
    content: bytes,
    mime_type: str,
    filename: str,
    caption: str | None,
    voice: bool,
    sent_by: int,
    reply_to: str | None = None,
    client: MetaClient | None = None,
) -> InboxMessage:
    """Send a photo, a voice note, a video or a document from staff.

    Held to the same two rules as a text. The file is handed to WhatsApp
    first and then sent by the id it gives back; a refusal at either step is
    shown in the chat as a failed message, with the reason.
    """
    reason = sending.refusal(db, conversation.phone)
    if reason:
        raise NotSent(reason)
    if not window_open(conversation):
        raise NotSent(WINDOW_CLOSED, kind="window_closed")

    extra = {"voice": True} if voice else None
    owned = client is None
    client = client or _client(db)
    try:
        media_id = client.upload_media(content, mime_type, filename)
        wa_message_id = client.send_media(
            conversation.phone, kind, media_id,
            caption=caption, filename=filename, voice=voice, reply_to=reply_to,
        )
    except MetaError as exc:
        return record_outbound(
            db, conversation, kind=kind, body=caption, origin="staff", status="failed",
            error=str(exc), sent_by=sent_by, reply_to=reply_to, extra=extra,
        )
    finally:
        if owned:
            client.close()
    return record_outbound(
        db, conversation, kind=kind, body=caption, origin="staff", status="sent",
        wa_message_id=wa_message_id, sent_by=sent_by, reply_to=reply_to, extra=extra,
    )


def send_reaction(
    db: Session,
    conversation: InboxConversation,
    target: InboxMessage,
    emoji: str,
    *,
    sent_by: int,
    client: MetaClient | None = None,
) -> InboxMessage:
    """React to one of her messages. An empty ``emoji`` takes it back.

    A reaction is a free message as far as WhatsApp is concerned, so it is
    held to the same two rules: who may be messaged, and the 24 hours.
    """
    reason = sending.refusal(db, conversation.phone)
    if reason:
        raise NotSent(reason)
    if not window_open(conversation):
        raise NotSent(WINDOW_CLOSED, kind="window_closed")
    if not target.wa_message_id or target.conversation_id != conversation.id:
        raise NotSent("That message cannot be reacted to.", kind="invalid")

    owned = client is None
    client = client or _client(db)
    try:
        wa_message_id = client.send_reaction(conversation.phone, target.wa_message_id, emoji)
    except MetaError as exc:
        raise NotSent(str(exc), kind=exc.kind) from None
    finally:
        if owned:
            client.close()
    return record_outbound(
        db, conversation, kind="reaction", body=emoji or None, origin="staff", status="sent",
        wa_message_id=wa_message_id, sent_by=sent_by, reply_to=target.wa_message_id,
        heads_list=False,
    )


def send_text(
    db: Session,
    conversation: InboxConversation,
    body: str,
    *,
    origin: str,
    sent_by: int | None = None,
    reply_to: str | None = None,
    source_ref: str | None = None,
    client: MetaClient | None = None,
) -> InboxMessage:
    """Send a free message and put it in the chat.

    Raises ``NotSent`` when it may not be sent at all - nothing is recorded.
    A message WhatsApp refuses *is* recorded, as failed with the reason, so
    whoever sent it sees that it did not go.
    """
    reason = sending.refusal(db, conversation.phone)
    if reason:
        raise NotSent(reason)
    if not window_open(conversation):
        raise NotSent(WINDOW_CLOSED, kind="window_closed")

    owned = client is None
    client = client or _client(db)
    try:
        wa_message_id = client.send_text(conversation.phone, body, reply_to=reply_to)
    except MetaError as exc:
        # An automatic message WhatsApp did not answer is tried again by its
        # job. Anything else is shown where it was sent from.
        if origin == "automatic" and exc.retryable:
            raise
        return record_outbound(
            db, conversation, kind="text", body=body, origin=origin, status="failed",
            error=str(exc), sent_by=sent_by, reply_to=reply_to, source_ref=source_ref,
        )
    finally:
        if owned:
            client.close()
    return record_outbound(
        db, conversation, kind="text", body=body, origin=origin, status="sent",
        wa_message_id=wa_message_id, sent_by=sent_by, reply_to=reply_to, source_ref=source_ref,
    )


def send_template(
    db: Session,
    conversation: InboxConversation,
    *,
    name: str,
    language: str,
    body: str | None,
    sent_by: int,
    client: MetaClient | None = None,
) -> InboxMessage:
    """Send one of the approved messages exactly as Meta approved it.

    The one way to reach a customer whose 24 hours have passed, so it is not
    held to them - only to the rule on who may be messaged. ``body`` is the
    approved wording, kept so the chat shows what she was sent.
    """
    reason = sending.refusal(db, conversation.phone)
    if reason:
        raise NotSent(reason)

    owned = client is None
    client = client or _client(db)
    try:
        wa_message_id = client.send_template(conversation.phone, name, language)
    except MetaError as exc:
        return record_outbound(
            db, conversation, kind="template", body=body, origin="staff", status="failed",
            error=str(exc), sent_by=sent_by, template_name=name,
        )
    finally:
        if owned:
            client.close()
    return record_outbound(
        db, conversation, kind="template", body=body, origin="staff", status="sent",
        wa_message_id=wa_message_id, sent_by=sent_by, template_name=name,
    )


# ── The automatic reply to a tap ──────────────────────────────────────────────


def queue_auto_reply(db: Session, message_id: int) -> None:
    enqueue(
        db,
        JobKind.INBOX_AUTO_REPLY,
        {"message_id": message_id},
        dedupe_key=f"{JobKind.INBOX_AUTO_REPLY}:{message_id}",
    )


def auto_reply(
    db: Session, message_id: int, client: MetaClient | None = None
) -> InboxMessage | None:
    """Answer a tap on Edit or Cancel. At most one reply per tap.

    ``None`` when there is nothing to say: a tap on Confirm, a tap that is no
    longer fresh, one already answered, or a customer this server may not
    message. The reply is stored under the tap's own id, which is unique, so
    a job run twice cannot answer twice.
    """
    tap = db.get(InboxMessage, message_id)
    if tap is None or tap.direction != "in" or tap.kind != "button" or not tap.wa_message_id:
        return None
    # Only a tap that was taken as her answer carries its order. One that
    # named somebody else's order is not answered.
    if not tap.shopify_order_id:
        return None
    found = _TAP.fullmatch(str((tap.extra or {}).get("payload") or ""))
    words = REPLIES.get(ANSWERS[found.group(1)]) if found else None
    if words is None or utcnow() - tap.occurred_at > REPLY_WHILE_FRESH:
        return None
    reference = f"auto:{tap.wa_message_id}"[:80]
    if db.scalar(select(InboxMessage.id).where(InboxMessage.source_ref == reference)):
        return None
    conversation = db.get(InboxConversation, tap.conversation_id)
    try:
        return send_text(
            db, conversation, words, origin="automatic", source_ref=reference, client=client
        )
    except NotSent:
        # Sending is off, or this server may not message her. Say nothing.
        return None


# ── An order's confirmation ───────────────────────────────────────────────────


def components(row: OrderConfirmation) -> list[dict[str, Any]]:
    """The approved message's three details and three buttons, as n8n sent
    them: order name, first name, total; then confirm, edit, cancel."""
    details = (row.order_name or "", row.customer_name or "there", row.total_text or "")
    built: list[dict[str, Any]] = [
        {"type": "body", "parameters": [{"type": "text", "text": detail} for detail in details]}
    ]
    for index, action in enumerate(BUTTONS):
        built.append(
            {
                "type": "button",
                "sub_type": "quick_reply",
                "index": str(index),
                "parameters": [
                    {"type": "payload", "payload": f"{action}_{row.shopify_order_id}"}
                ],
            }
        )
    return built


def queue_confirmation_send(
    db: Session, order_id: str, *, attempt: int | str = 0, run_after=None
) -> None:
    enqueue(
        db,
        JobKind.INBOX_SEND_CONFIRMATION,
        {"order_id": order_id},
        run_after=run_after,
        # The attempt is in the key: a retry is queued while the attempt
        # that failed is still the running job under the old key.
        dedupe_key=f"{JobKind.INBOX_SEND_CONFIRMATION}:{order_id}:{attempt}",
    )


def _claim(order_id: str) -> bool:
    """Take the order for sending, in a transaction of its own.

    Committed before WhatsApp is asked. Whatever happens next - a crash, a
    lost lease, a second worker - the order is no longer ``pending`` and
    nobody else will send it.
    """
    from app.db import SessionLocal

    with SessionLocal() as own:
        claimed = own.execute(
            update(OrderConfirmation)
            .where(
                OrderConfirmation.shopify_order_id == order_id,
                OrderConfirmation.state == "pending",
            )
            .values(state="sending", updated_at=utcnow())
        ).rowcount
        own.commit()
    return claimed == 1


def _not_taken(db: Session, row: OrderConfirmation, exc: MetaError) -> None:
    """WhatsApp did not take the confirmation. Say why, and what happens next."""
    row.attempts += 1
    row.last_error = str(exc)[:300]
    row.updated_at = utcnow()
    if exc.kind == "undeliverable":
        # The number has no WhatsApp. Trying again will not give it one.
        row.state = "no_whatsapp"
        tags.queue_tags(db, row)
    elif exc.retryable and row.attempts < MAX_ATTEMPTS:
        row.state = "pending"
        row.next_attempt_at = utcnow() + RETRY_AFTER[min(row.attempts, len(RETRY_AFTER)) - 1]
        queue_confirmation_send(
            db, row.shopify_order_id, attempt=row.attempts, run_after=row.next_attempt_at
        )
    else:
        row.state = "failed"


def send_confirmation(
    db: Session,
    order_id: str,
    *,
    client: MetaClient | None = None,
    claim: Callable[[str], bool] = _claim,
) -> OrderConfirmation | None:
    """Send one order's confirmation, if it is still waiting to be sent."""
    row = db.scalar(
        select(OrderConfirmation).where(OrderConfirmation.shopify_order_id == order_id)
    )
    if row is None or row.state != "pending" or not row.phone:
        return row
    if sending.refusal(db, row.phone):
        # Sending was turned off between deciding and sending. The order
        # stands as it would on a server that only records.
        row.state = "would_send"
        row.updated_at = utcnow()
        return row

    owned = client is None
    client = client or _client(db)
    try:
        if not claim(order_id):
            return row
        try:
            wa_message_id = client.send_template(row.phone, TEMPLATE, LANGUAGE, components(row))
        except MetaError as exc:
            _not_taken(db, row, exc)
            return row
    finally:
        if owned:
            client.close()

    now = utcnow()
    name = row.customer_name if row.customer_name and row.customer_name != "there" else None
    conversation = _conversation(db, row.phone, name)
    row.state = "sent"
    row.wa_message_id = wa_message_id
    row.sent_at = now
    row.attempts += 1
    row.last_error = None
    row.next_attempt_at = None
    row.conversation_id = conversation.id
    row.updated_at = now
    record_outbound(
        db,
        conversation,
        kind="template",
        body=f"Order confirmation · {row.order_name or order_id}",
        origin="automatic",
        status="sent",
        wa_message_id=wa_message_id,
        template_name=TEMPLATE,
        extra={"buttons": ["Confirm", "Edit", "Cancel"]},
        order_id=order_id,
    )
    tags.queue_tags(db, row)
    return row


def recover_interrupted(db: Session) -> int:
    """Orders left ``sending`` by a crash become failed, never re-sent.

    Whether the message went out is not something the platform can know, so
    it says so and leaves the decision to a person.
    """
    recovered = db.execute(
        update(OrderConfirmation)
        .where(
            OrderConfirmation.state == "sending",
            OrderConfirmation.updated_at < utcnow() - INTERRUPTED_AFTER,
        )
        .values(state="failed", last_error=INTERRUPTED, updated_at=utcnow())
    ).rowcount
    return recovered or 0


@register_handler(JobKind.INBOX_SEND_CONFIRMATION)
def _handle_send_confirmation(db: Session, payload: dict) -> None:
    order_id = str(payload.get("order_id") or "").strip()
    if not order_id:
        raise PermanentFailure(
            f"{JobKind.INBOX_SEND_CONFIRMATION} requires an order_id; got payload keys "
            f"{sorted(payload)!r}"
        )
    try:
        send_confirmation(db, order_id)
    except NotSent as exc:
        # The keys cannot be read. Retrying will not read them.
        raise PermanentFailure(f"Cannot send order {order_id}'s confirmation: {exc}") from exc


@register_handler(JobKind.INBOX_AUTO_REPLY)
def _handle_auto_reply(db: Session, payload: dict) -> None:
    message_id = payload.get("message_id")
    if not isinstance(message_id, int):
        raise PermanentFailure(
            f"{JobKind.INBOX_AUTO_REPLY} requires a message_id; got payload keys "
            f"{sorted(payload)!r}"
        )
    auto_reply(db, message_id)
