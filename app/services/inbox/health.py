"""What went wrong with order confirmations, for Operations' WhatsApp tab
(ADR 0059, point 18).

Operations' rules hold here as on its other tabs (ADR 0057):

- **It only reads.** Nothing on the tab sends or retries; each order links
  to the Inbox, where the fix is made.
- **No customer details.** An order number, when it was placed and why -
  never a name, a phone or a message. Nothing in this module selects one.
- **A count nobody has is not shown as 0.** These are the platform's own
  tables, so the counts are always current; what can be stale is WhatsApp
  itself, and ``last_heard_at`` says when it was last heard from.
"""

from datetime import timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.models.inbox import InboxConnection, InboxMessage, MetaWebhookEvent, OrderConfirmation
from app.models.integration import BackgroundJob
from app.services.inbox import tags
from app.services.jobs import JobKind, JobStatus
from app.services.order_ops.shopify import waiting_days

#: The tab's five cards, in the order the approved mockup draws them.
CARDS = ("failed", "no_whatsapp", "never_messaged", "answers_not_recorded", "waiting")

#: How long a delivered confirmation may go unanswered before it is listed.
WAITING_AFTER = timedelta(hours=24)

LIST_LIMIT = 200

#: WhatsApp answers every message we send within seconds, with at least a
#: "sent". Longer than this after a send with nothing heard, it has gone quiet.
QUIET_AFTER = timedelta(minutes=10)


def _where(card: str, since):
    state, answer = OrderConfirmation.state, OrderConfirmation.answer
    recent = OrderConfirmation.placed_at >= since
    return {
        "failed": and_(recent, state == "failed"),
        "no_whatsapp": and_(recent, state == "no_whatsapp", answer.is_(None)),
        "never_messaged": and_(recent, state.in_(("no_phone", "bad_phone"))),
        "waiting": and_(
            recent,
            state == "sent",
            answer.is_(None),
            # A payment request has nothing to tap (ADR 0062).
            OrderConfirmation.kind == "confirmation",
            OrderConfirmation.sent_at < utcnow() - WAITING_AFTER,
        ),
    }[card]


def _untagged_order_ids(db: Session, since) -> list[str]:
    """Orders whose answer could not be written to Shopify as a tag: the tag
    job gave up. The answer itself is safe in the platform."""
    rows = db.scalars(
        select(BackgroundJob.payload["order_id"].astext)
        .where(
            BackgroundJob.kind == JobKind.INBOX_TAG_ORDER,
            BackgroundJob.status == JobStatus.FAILED,
            BackgroundJob.created_at >= since,
        )
        .distinct()
    ).all()
    return [order_id for order_id in rows if order_id]


def _row(order: OrderConfirmation, now) -> dict:
    # Deliberately no phone and no name: Operations shows neither.
    return {
        "order_id": order.shopify_order_id,
        "order": order.order_name,
        "placed_at": order.placed_at.isoformat() if order.placed_at else None,
        "waiting_days": waiting_days(order.placed_at, now) if order.placed_at else None,
        "why": order.last_error,
        "state": order.state,
        "answer": order.answer,
        # The one tag the order carries in Shopify for this, if any.
        "tag": tags.wanted_tag(order),
    }


def quiet_since(db: Session, last_heard, now):
    """When WhatsApp went quiet, or None if it has not.

    Not "nothing for a while": at night nothing arrives for hours and nothing
    is wrong. It is quiet when we have sent something and heard nothing since
    - not even that it was sent.
    """
    last_sent = db.scalar(
        select(func.max(InboxMessage.occurred_at)).where(
            InboxMessage.direction == "out", InboxMessage.wa_message_id.is_not(None)
        )
    )
    if last_sent is None or now - last_sent < QUIET_AFTER:
        return None
    if last_heard is not None and last_heard >= last_sent:
        return None
    return last_heard or last_sent


def pulse(db: Session) -> dict:
    """Whether WhatsApp is being heard from, for the Inbox's own heading.

    The Inbox's staff do not hold Operations, so they are told here, in the
    same terms, and with no order or customer in it.
    """
    now = utcnow()
    connection = db.get(InboxConnection, 1)
    last_heard = db.scalar(select(func.max(MetaWebhookEvent.received_at)))
    quiet = quiet_since(db, last_heard, now)
    return {
        "connected": connection is not None,
        "sending": bool(connection and connection.sending_enabled),
        "last_heard_at": last_heard.isoformat() if last_heard else None,
        "quiet_since": quiet.isoformat() if quiet else None,
    }


def summary(db: Session, *, card: str | None = None, days: int = 7) -> dict:
    """The tab: five counts, when WhatsApp was last heard from, and the
    orders behind one card when asked."""
    if card is not None and card not in CARDS:
        raise ValueError(f"Unknown card: {card!r}")
    now = utcnow()
    since = now - timedelta(days=max(1, min(days, 90)))
    untagged = _untagged_order_ids(db, since)

    def count(name: str) -> int:
        if name == "answers_not_recorded":
            return len(untagged)
        return db.scalar(
            select(func.count()).select_from(OrderConfirmation).where(_where(name, since))
        ) or 0

    connection = db.get(InboxConnection, 1)
    last_heard = db.scalar(select(func.max(MetaWebhookEvent.received_at)))
    quiet = quiet_since(db, last_heard, now)
    body = {
        "connected": connection is not None,
        "sending": bool(connection and connection.sending_enabled),
        "last_heard_at": last_heard.isoformat() if last_heard else None,
        "quiet_since": quiet.isoformat() if quiet else None,
        "read_at": now.isoformat(),
        "days": days,
        "cards": {name: count(name) for name in CARDS},
        "orders": None,
    }
    if card is not None:
        if card == "answers_not_recorded":
            query = select(OrderConfirmation).where(OrderConfirmation.shopify_order_id.in_(untagged))
        else:
            query = select(OrderConfirmation).where(_where(card, since))
        orders = db.scalars(
            query.order_by(OrderConfirmation.placed_at.desc().nulls_last()).limit(LIST_LIMIT)
        ).all()
        body["orders"] = [_row(order, now) for order in orders]
    return body
