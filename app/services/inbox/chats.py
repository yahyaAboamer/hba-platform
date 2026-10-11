"""What the inbox's screens read, and what staff do from them (ADR 0059).

**Every conversation, a page at a time.** The old inbox loaded everything at
once and so stopped at 200 chats and 500 messages. Here the list and a chat
are both read by position - "the next thirty older than this one" - so the
thousandth conversation costs the same as the first.

**Nothing here sends on its own account.** A reply, a reaction and a
confirmation sent again all go out through ``outbound``, the one door, and
so through the one rule on who may be messaged.

This is the only part of the platform that returns a customer's name, phone
and words, and every route that reaches it is behind ``inbox.use``.
"""

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.models.identity import UserAccount
from app.models.inbox import InboxConversation, InboxMedia, InboxMessage, OrderConfirmation
from app.services.audit import record_audit
from app.services.inbox import outbound, sending, tags
from app.services.inbox.events import ANSWERS, _TAP
from app.services.inbox.meta import MetaClient

PAGE = 30
MESSAGE_PAGE = 50
MAX_PAGE = 100

#: The list's four views (the approved mockup's chips).
FILTERS = ("all", "unread", "edit", "cancelled")

#: WhatsApp's own limit on a text message.
MAX_TEXT = 4096

#: An order may be sent again only from these. Never one that was sent, is
#: being sent, or is waiting to be - that is how a second message would start.
SEND_AGAIN_FROM = ("failed", "would_send")

#: The Confirmations screen's tiles, and the orders behind each.
TILES = ("waiting", "edit", "cancelled", "not_sent", "no_whatsapp", "confirmed")
NOT_SENT_STATES = ("failed", "would_send", "no_phone", "bad_phone", "pending", "sending")

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

ALREADY_SENT = "This order already has its confirmation. Nothing was sent."
SENDING_WAS_OFF = "Sending was off when this order arrived."


class NotFound(LookupError):
    """No such conversation, message or order."""


class Refused(ValueError):
    """Why something was not done. The text is safe to show."""


def _like(text: str) -> str:
    """``%`` and ``_`` typed into a search are letters, not wildcards."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _cursor(at: datetime | None, row_id: int) -> str:
    return f"{(at or EPOCH).isoformat()}|{row_id}"


def _read_cursor(raw: str | None) -> tuple[datetime, int] | None:
    if not raw:
        return None
    try:
        at, row_id = raw.rsplit("|", 1)
        parsed = datetime.fromisoformat(at)
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc), int(row_id))
    except ValueError:
        raise Refused("That page marker is not one of ours.") from None


def _limit(limit: int | None, default: int) -> int:
    return max(1, min(limit or default, MAX_PAGE))


def _iso(at: datetime | None) -> str | None:
    return at.isoformat() if at else None


#: Her most recent order's answer, for the list's flag and two of its views.
_latest_answer = (
    select(OrderConfirmation.answer)
    .where(OrderConfirmation.conversation_id == InboxConversation.id)
    .order_by(OrderConfirmation.created_at.desc(), OrderConfirmation.id.desc())
    .limit(1)
    .correlate(InboxConversation)
    .scalar_subquery()
)

#: What the list is sorted by: the last message, newest first.
_sorted_at = func.coalesce(InboxConversation.last_message_at, EPOCH)


# ── The list ──────────────────────────────────────────────────────────────────


def _search(q: str):
    """Name, phone or order number."""
    digits = re.sub(r"\D", "", q)
    clauses = [InboxConversation.name.ilike(_like(q), escape="\\")]
    if len(digits) >= 3:
        clauses.append(InboxConversation.phone.like(_like(digits), escape="\\"))
        if digits.startswith("0"):
            # 010… is how she would say it; 2010… is how it is stored.
            clauses.append(InboxConversation.phone.like(_like("20" + digits[1:]), escape="\\"))
    order = q.lstrip("#").strip()
    if order:
        clauses.append(
            select(OrderConfirmation.id)
            .where(
                OrderConfirmation.conversation_id == InboxConversation.id,
                or_(
                    OrderConfirmation.order_name.ilike(_like(order), escape="\\"),
                    OrderConfirmation.shopify_order_id == order,
                ),
            )
            .exists()
        )
    return or_(*clauses)


def describe_conversation(conversation: InboxConversation, answer: str | None) -> dict:
    return {
        "id": conversation.id,
        "phone": conversation.phone,
        "name": conversation.name,
        "last_message_at": _iso(conversation.last_message_at),
        "last_preview": conversation.last_preview,
        "last_direction": conversation.last_direction,
        "unread_count": conversation.unread_count,
        # Whether a free reply may be typed right now, and until when.
        "window_open": outbound.window_open(conversation),
        "window_closes_at": _iso(
            conversation.last_inbound_at + outbound.WINDOW if conversation.last_inbound_at else None
        ),
        "answer": answer,
    }


def list_conversations(
    db: Session,
    *,
    view: str = "all",
    q: str | None = None,
    before: str | None = None,
    limit: int | None = None,
) -> dict:
    """One page of the list, newest first, and how to ask for the next."""
    if view not in FILTERS:
        raise Refused("That is not one of the list's views.")
    limit = _limit(limit, PAGE)
    query = select(InboxConversation, _latest_answer.label("answer"))
    if view == "unread":
        query = query.where(InboxConversation.unread_count > 0)
    elif view in ("edit", "cancelled"):
        query = query.where(_latest_answer == view)
    if q and q.strip():
        query = query.where(_search(q.strip()[:120]))
    position = _read_cursor(before)
    if position:
        at, row_id = position
        query = query.where(
            or_(_sorted_at < at, and_(_sorted_at == at, InboxConversation.id < row_id))
        )
    rows = db.execute(
        query.order_by(_sorted_at.desc(), InboxConversation.id.desc()).limit(limit + 1)
    ).all()
    page = rows[:limit]
    return {
        "conversations": [describe_conversation(row[0], row[1]) for row in page],
        "next": _cursor(page[-1][0].last_message_at, page[-1][0].id) if len(rows) > limit else None,
    }


def counts(db: Session) -> dict:
    """The numbers on the list's chips and the sidebar."""
    return {
        "all": db.scalar(select(func.count()).select_from(InboxConversation)) or 0,
        "unread": db.scalar(
            select(func.count()).select_from(InboxConversation).where(InboxConversation.unread_count > 0)
        ) or 0,
        "edit": db.scalar(
            select(func.count()).select_from(InboxConversation).where(_latest_answer == "edit")
        ) or 0,
    }


# ── One chat ──────────────────────────────────────────────────────────────────


def _conversation(db: Session, conversation_id: int) -> InboxConversation:
    conversation = db.get(InboxConversation, conversation_id)
    if conversation is None:
        raise NotFound("No such conversation.")
    return conversation


def describe_order(row: OrderConfirmation) -> dict:
    return {
        "order_id": row.shopify_order_id,
        "order": row.order_name,
        "state": row.state,
        "answer": row.answer,
        "answered_at": _iso(row.answered_at),
        "placed_at": _iso(row.placed_at),
        "sent_at": _iso(row.sent_at),
        "total": row.total_text,
        # The one tag the order carries in Shopify for this.
        "tag": tags.wanted_tag(row),
        "why": row.last_error or (SENDING_WAS_OFF if row.state == "would_send" else None),
        "can_send_again": row.state in SEND_AGAIN_FROM and bool(row.phone) and not row.wa_message_id,
    }


def conversation_detail(db: Session, conversation_id: int) -> dict:
    """The chat's header and the orders beside it, newest first."""
    conversation = _conversation(db, conversation_id)
    orders = db.scalars(
        select(OrderConfirmation)
        .where(OrderConfirmation.conversation_id == conversation.id)
        .order_by(OrderConfirmation.created_at.desc(), OrderConfirmation.id.desc())
        .limit(10)
    ).all()
    return {
        **describe_conversation(conversation, orders[0].answer if orders else None),
        "orders": [describe_order(order) for order in orders],
    }


def describe_message(
    message: InboxMessage, sender: str | None, media: InboxMedia | None, quoted: dict | None = None
) -> dict:
    extra = message.extra or {}
    tapped = _TAP.fullmatch(str(extra.get("payload") or "")) if message.kind == "button" else None
    return {
        "id": message.id,
        "direction": message.direction,
        "kind": message.kind,
        "body": message.body,
        "status": message.status,
        "error": message.error,
        # customer, staff, automatic, or imported (the old inbox, which never
        # recorded who sent a reply).
        "origin": message.origin,
        "sender": sender,
        "reply_to": quoted,
        "template": message.template_name,
        "buttons": extra.get("buttons"),
        "tapped": ANSWERS[tapped.group(1)] if tapped and not extra.get("unmatched") else None,
        "voice": bool(extra.get("voice")),
        "order_id": message.shopify_order_id,
        "at": _iso(message.occurred_at),
        "media": {
            "id": media.id,
            "state": media.state,
            "mime_type": media.mime_type,
            "filename": media.filename,
            "size_bytes": media.size_bytes,
            "url": f"/api/inbox/media/{media.id}" if media.state == "stored" else None,
        }
        if media is not None
        else None,
    }


def list_messages(
    db: Session, conversation_id: int, *, before: str | None = None, limit: int | None = None
) -> dict:
    """One page of a chat, oldest first, ending at the newest - or at
    ``before``, for the page above it."""
    conversation = _conversation(db, conversation_id)
    limit = _limit(limit, MESSAGE_PAGE)
    query = (
        select(InboxMessage, UserAccount.display_name, InboxMedia)
        .outerjoin(UserAccount, UserAccount.id == InboxMessage.sent_by)
        .outerjoin(InboxMedia, InboxMedia.message_id == InboxMessage.id)
        .where(InboxMessage.conversation_id == conversation.id)
    )
    position = _read_cursor(before)
    if position:
        at, row_id = position
        query = query.where(
            or_(
                InboxMessage.occurred_at < at,
                and_(InboxMessage.occurred_at == at, InboxMessage.id < row_id),
            )
        )
    rows = db.execute(
        query.order_by(InboxMessage.occurred_at.desc(), InboxMessage.id.desc()).limit(limit + 1)
    ).all()
    page = list(reversed(rows[:limit]))

    # What each reply answers, where that message is one we hold.
    wanted = {row[0].reply_to_wa_id for row in page if row[0].reply_to_wa_id}
    quoted = {}
    if wanted:
        for found in db.scalars(select(InboxMessage).where(InboxMessage.wa_message_id.in_(wanted))):
            quoted[found.wa_message_id] = {
                "id": found.id,
                "direction": found.direction,
                "kind": found.kind,
                "body": (found.body or "")[:160] or None,
            }
    return {
        "messages": [
            describe_message(message, sender, media, quoted.get(message.reply_to_wa_id))
            for message, sender, media in page
        ],
        "earlier": _cursor(page[0][0].occurred_at, page[0][0].id) if len(rows) > limit else None,
    }


def mark_read(db: Session, conversation_id: int) -> str | None:
    """She has been read. Returns her last message's WhatsApp id, for the
    blue ticks, or None if there is nothing to tick."""
    conversation = _conversation(db, conversation_id)
    conversation.unread_count = 0
    db.flush()
    return db.scalar(
        select(InboxMessage.wa_message_id)
        .where(
            InboxMessage.conversation_id == conversation.id,
            InboxMessage.direction == "in",
            InboxMessage.wa_message_id.is_not(None),
        )
        .order_by(InboxMessage.occurred_at.desc(), InboxMessage.id.desc())
        .limit(1)
    )


# ── What staff do ─────────────────────────────────────────────────────────────


def _described(db: Session, message: InboxMessage) -> dict:
    sender = db.scalar(select(UserAccount.display_name).where(UserAccount.id == message.sent_by))
    return describe_message(message, sender, None)


def _target(db: Session, conversation: InboxConversation, message_id: int | None) -> InboxMessage | None:
    """The message a reply or a reaction is to: one of this chat's own."""
    if message_id is None:
        return None
    target = db.get(InboxMessage, message_id)
    if target is None or target.conversation_id != conversation.id or not target.wa_message_id:
        raise Refused("That message is not one in this chat.")
    return target


def reply(
    db: Session,
    conversation_id: int,
    body: str,
    *,
    actor_id: int,
    reply_to: int | None = None,
    client: MetaClient | None = None,
) -> dict:
    """A member of staff's message. It carries their name."""
    conversation = _conversation(db, conversation_id)
    body = (body or "").strip()
    if not body:
        raise Refused("Type a message first.")
    if len(body) > MAX_TEXT:
        raise Refused(f"That is longer than WhatsApp allows ({MAX_TEXT} characters).")
    target = _target(db, conversation, reply_to)
    message = outbound.send_text(
        db,
        conversation,
        body,
        origin="staff",
        sent_by=actor_id,
        reply_to=target.wa_message_id if target else None,
        client=client,
    )
    return _described(db, message)


def react(
    db: Session,
    conversation_id: int,
    message_id: int,
    emoji: str,
    *,
    actor_id: int,
    client: MetaClient | None = None,
) -> dict:
    conversation = _conversation(db, conversation_id)
    emoji = (emoji or "").strip()
    if len(emoji) > 16:
        raise Refused("A reaction is one emoji.")
    target = _target(db, conversation, message_id)
    message = outbound.send_reaction(
        db, conversation, target, emoji, sent_by=actor_id, client=client
    )
    return _described(db, message)


def _order(db: Session, order_id: str) -> OrderConfirmation:
    row = db.scalar(
        select(OrderConfirmation).where(OrderConfirmation.shopify_order_id == str(order_id))
    )
    if row is None:
        raise NotFound("No such order.")
    return row


def send_again(db: Session, order_id: str, *, actor_id: int, actor_email: str | None) -> dict:
    """Queue an order's confirmation again. **Never a second message.**

    Only an order with no confirmation on record, from a state in which none
    can be on its way. An order that was sent, is being sent or is waiting to
    be is refused - and so is a number with no WhatsApp, which is a call.
    """
    row = _order(db, order_id)
    if row.wa_message_id or row.state in ("sent", "sending", "pending"):
        raise Refused(ALREADY_SENT)
    if row.state not in SEND_AGAIN_FROM or not row.phone:
        raise Refused("This order cannot be messaged. " + (row.last_error or "").strip())
    reason = sending.refusal(db, row.phone)
    if reason:
        raise Refused(reason)

    before = row.state
    row.state = "pending"
    row.attempts = 0
    row.last_error = None
    row.next_attempt_at = None
    row.updated_at = utcnow()
    outbound.queue_confirmation_send(db, row.shopify_order_id, attempt=f"again-{time.time_ns()}")
    record_audit(
        db,
        action="inbox.confirmation_resent",
        subject=f"order:{row.shopify_order_id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before={"state": before},
        after={"state": "pending", "order": row.order_name},
    )
    db.flush()
    return describe_order(row)


def set_answer(
    db: Session, order_id: str, answer: str, *, actor_id: int, actor_email: str | None
) -> dict:
    """Staff record the customer's answer themselves - she confirmed by
    phone, say. It changes the order's tag in Shopify and nothing else there:
    marking an order cancelled here does not cancel it in Shopify."""
    if answer not in tags.ANSWER_TAGS:
        raise Refused("An order is confirmed, wants a change, or is cancelled.")
    row = _order(db, order_id)
    before = row.answer
    row.answer = answer
    row.answered_at = utcnow()
    row.updated_at = utcnow()
    db.flush()
    tags.queue_tags(db, row)
    record_audit(
        db,
        action="inbox.answer_set",
        subject=f"order:{row.shopify_order_id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before={"answer": before},
        after={"answer": answer, "order": row.order_name},
    )
    return describe_order(row)


# ── The Confirmations screen ──────────────────────────────────────────────────


def _tile(tile: str):
    answer, state = OrderConfirmation.answer, OrderConfirmation.state
    return {
        "waiting": and_(state == "sent", answer.is_(None)),
        "edit": answer == "edit",
        "cancelled": answer == "cancelled",
        "confirmed": answer == "confirmed",
        "no_whatsapp": and_(state == "no_whatsapp", answer.is_(None)),
        "not_sent": and_(state.in_(NOT_SENT_STATES), answer.is_(None)),
    }[tile]


def confirmations(db: Session, *, tile: str | None = None, days: int = 7) -> dict:
    """Where each cash-on-delivery order's confirmation stands.

    A paid order is not here: it never gets a confirmation.
    """
    if tile is not None and tile not in TILES:
        raise Refused("That is not one of the Confirmations cards.")
    since = utcnow() - timedelta(days=max(1, min(days, 90)))
    recent = and_(OrderConfirmation.placed_at >= since, OrderConfirmation.state != "not_needed")
    body: dict[str, Any] = {
        "days": days,
        "total": db.scalar(select(func.count()).select_from(OrderConfirmation).where(recent)) or 0,
        "tiles": {
            name: db.scalar(
                select(func.count()).select_from(OrderConfirmation).where(recent, _tile(name))
            ) or 0
            for name in TILES
        },
        "orders": None,
    }
    if tile is not None:
        rows = db.scalars(
            select(OrderConfirmation)
            .where(recent, _tile(tile))
            .order_by(OrderConfirmation.placed_at.desc())
            .limit(200)
        ).all()
        body["orders"] = [
            {
                **describe_order(row),
                "customer": row.customer_name if row.customer_name != "there" else None,
                "conversation_id": row.conversation_id,
            }
            for row in rows
        ]
    return body
