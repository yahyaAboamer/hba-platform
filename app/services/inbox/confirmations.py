"""Whether an order gets a WhatsApp confirmation, decided once per order
(ADR 0059).

**This decides; it does not send.** An order that should get the message is
recorded one of two ways:

- ``would_send`` on a server that may not message that customer - WhatsApp
  not connected, sending off in Settings, or a server not told it may message
  customers (``sending.refusal``). That is the silent run beside the old
  automation: the record is compared against n8n's own until the two agree
  (``app.services.inbox.shadow``).
- ``pending`` on a server that may, with the sending queued as a job of its
  own (``app.services.inbox.outbound``).

**An order recorded as ``would_send`` is never sent later.** Turning sending
on changes what happens to orders decided from then on, and nothing before.

The rules are n8n's, kept as they were (ADR 0059, point 8):

- **Only cash on delivery, or payment still pending.** A paid order gets no
  message - and is recorded as ``not_needed``, finished, where n8n dropped it
  unmarked and called it failed.
- **To the customer's Egyptian mobile**: the order's own phone, else the
  customer's, else the shipping address's.
- **One per order.** ``order_confirmation.shopify_order_id`` is unique, so an
  order is decided once however many times it is synced.

One rule is new, because the platform can meet an order late where n8n only
ever met it at its webhook: **an order more than 48 hours old is not
considered at all.** A re-sync of last month's orders must never produce a
confirmation for one.

The order is read with a query of its own. The shared order query feeds
commission, and a customer field Shopify refused there would stop orders
indexing; here a refusal fails only this job.

**Off unless the server is told to** (``INBOX_CONFIRMATIONS_ENABLED``). A
decision keeps the customer's phone and first name, and staging reads the
real store: switched off, nothing is queued, nothing is read and nothing is
kept. It is on in production.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.core.businesstime import utcnow
from app.core.signals import Anomaly, report
from app.models.inbox import OrderConfirmation
from app.models.orders import OrderIndex
from app.services.inbox.sending import egyptian_mobile, international_mobile, refusal
from app.services.jobs import JobKind, PermanentFailure, enqueue
from app.services.shopify.client import ShopifyClient
from app.services.shopify.sync import PERMANENT, build_client, order_gid
from app.worker import register_handler

logger = logging.getLogger(__name__)

#: How long after it was placed an order is still considered. The sweep that
#: catches a missed webhook looks back this far, and nothing older ever gets
#: a row.
FRESH_FOR = timedelta(hours=48)

#: How many orders one sweep queues. Far more than 48 hours of orders.
SWEEP_BATCH = 500

#: What the confirmation message needs, and nothing else.
CONFIRMATION_ORDER = """
query ConfirmationOrder($id: ID!) {
  order(id: $id) {
    legacyResourceId
    name
    createdAt
    cancelledAt
    test
    displayFinancialStatus
    paymentGatewayNames
    totalPriceSet { shopMoney { amount } }
    totalOutstandingSet { shopMoney { amount currencyCode } }
    phone
    customer { firstName phone }
    shippingAddress { phone countryCodeV2 }
  }
}
"""

PAID = "A paid order: it gets no confirmation."
CANCELLED = "Cancelled before a confirmation went out."
TEST_ORDER = "A test order."
NO_PHONE = "The order has no phone number."
BAD_PHONE = "The phone number on the order is not a valid Egyptian number."
BAD_FOREIGN_PHONE = (
    "The phone number on the order could not be read as a number in the "
    "country it ships to. Shopify's invoice email still goes."
)


@dataclass(frozen=True)
class Decision:
    """What an order's confirmation is to be, and why."""

    state: str
    reason: str | None = None
    phone: str | None = None
    customer_name: str | None = None
    total_text: str | None = None
    #: ``payment`` for an unpaid international order (ADR 0062).
    kind: str = "confirmation"
    country: str | None = None


def is_cash_on_delivery(gateways: Any, financial_status: Any) -> bool:
    """n8n's own test: a gateway named for cash, or payment still pending."""
    names = gateways if isinstance(gateways, list) else []
    joined = " ".join(str(name) for name in names).lower()
    return "cash" in joined or str(financial_status or "").upper() == "PENDING"


def _total_text(node: dict) -> str | None:
    """The total as the old message wrote it: ``1450.00``."""
    amount = ((node.get("totalPriceSet") or {}).get("shopMoney") or {}).get("amount")
    try:
        return f"{Decimal(str(amount)):.2f}"
    except (InvalidOperation, ValueError):
        return None


def shipping_country(node: dict) -> str | None:
    """Where the order ships, as Shopify writes it (``SA``), or None."""
    country = str((node.get("shippingAddress") or {}).get("countryCodeV2") or "").strip().upper()
    return country[:2] or None


def _payment_decision(node: dict, country: str, given: list[str], first_name: str) -> Decision:
    """An international order (ADR 0062): a payment request if it still
    owes money, nothing if it does not."""
    from app.services.inbox.payments import money_text, owed_from

    owed = owed_from(node)
    if owed.amount <= 0:
        return Decision("not_needed", PAID)
    kind = {"kind": "payment", "country": country}
    if not given:
        return Decision("no_phone", NO_PHONE, **kind)
    phone = next((read for read in (international_mobile(raw, country) for raw in given) if read), None)
    if phone is None:
        return Decision("bad_phone", BAD_FOREIGN_PHONE, **kind)
    return Decision(
        "would_send",
        phone=phone,
        customer_name=(first_name or "there")[:120],
        total_text=money_text(owed.amount, owed.currency),
        **kind,
    )


def decide(node: dict, *, payments: bool = False) -> Decision:
    """What n8n would do with this order. Pure: no clock, no database.

    With ``payments`` on, an order shipped outside Egypt is decided as a
    payment request instead (ADR 0062).
    """
    if node.get("test"):
        return Decision("not_needed", TEST_ORDER)
    if node.get("cancelledAt"):
        return Decision("not_needed", CANCELLED)

    customer = node.get("customer") or {}
    shipping = node.get("shippingAddress") or {}
    given = [
        str(raw).strip()
        for raw in (node.get("phone"), customer.get("phone"), shipping.get("phone"))
        if raw and str(raw).strip()
    ]
    first_name = str(customer.get("firstName") or "").strip()
    country = shipping_country(node)
    if payments and country and country != "EG":
        return _payment_decision(node, country, given, first_name)

    if not is_cash_on_delivery(node.get("paymentGatewayNames"), node.get("displayFinancialStatus")):
        return Decision("not_needed", PAID)
    if not given:
        return Decision("no_phone", NO_PHONE)
    phone = next((read for read in map(egyptian_mobile, given) if read), None)
    if phone is None:
        return Decision("bad_phone", BAD_PHONE)

    return Decision(
        "would_send",
        phone=phone,
        # The old message's own fallback, for an order with no first name.
        customer_name=(first_name or "there")[:120],
        total_text=_total_text(node),
    )


def _placed_at(node: dict) -> datetime | None:
    try:
        placed = datetime.fromisoformat(str(node.get("createdAt")).replace("Z", "+00:00"))
    except ValueError:
        return None
    return placed if placed.tzinfo else placed.replace(tzinfo=timezone.utc)


def _recorded(db: Session, order_id: str) -> OrderConfirmation | None:
    return db.scalar(
        select(OrderConfirmation).where(OrderConfirmation.shopify_order_id == order_id)
    )


def confirm_order(
    db: Session, order_id: str, client: ShopifyClient | None = None
) -> OrderConfirmation | None:
    """Decide one order's confirmation and record it. Returns the record.

    ``None`` when there is nothing to record: Shopify has no such order, or
    the order is older than ``FRESH_FOR``. An order already decided is
    returned as it stands, without asking Shopify again.
    """
    existing = _recorded(db, order_id)
    if existing is not None:
        return existing

    try:
        client = client or build_client()
        data = client.execute(CONFIRMATION_ORDER, {"id": order_gid(order_id)})
    except PERMANENT as exc:
        raise PermanentFailure(f"Cannot read order {order_id} for its confirmation: {exc}") from exc

    node = data.get("order")
    if not node:
        report(Anomaly.ORDER_NOT_FOUND, order_id=str(order_id))
        return None
    placed_at = _placed_at(node)
    if placed_at is None or placed_at < utcnow() - FRESH_FOR:
        return None

    from app.services.inbox import payments

    decision = decide(node, payments=payments.enabled())
    state = decision.state
    # May this server message her? If so the order waits to be sent; if not
    # it is recorded as what would have been sent, and stays that way.
    to_send = state == "would_send" and refusal(db, decision.phone) is None
    if to_send:
        state = "pending"
    # ON CONFLICT, not check-then-insert: a webhook and the sweep can reach
    # the same order at once, and the second must lose quietly.
    inserted = db.execute(
        insert(OrderConfirmation)
        .values(
            shopify_order_id=order_id,
            order_name=str(node.get("name") or "")[:40] or None,
            state=state,
            phone=decision.phone,
            customer_name=decision.customer_name,
            total_text=decision.total_text,
            # Why there is no message, for the states that have none.
            last_error=decision.reason,
            placed_at=placed_at,
            kind=decision.kind,
            country=decision.country,
        )
        .on_conflict_do_nothing(index_elements=["shopify_order_id"])
        .returning(OrderConfirmation.id)
    ).scalar()
    # Queued only by whoever recorded the decision, so the loser of a race
    # does not queue a second sending.
    if to_send and inserted is not None:
        from app.services.inbox.outbound import queue_confirmation_send

        queue_confirmation_send(db, order_id)
    row = _recorded(db, order_id)
    # Shopify's invoice email goes whether or not WhatsApp can reach her
    # (ADR 0062, point 6) - most of all when it cannot.
    if inserted is not None and row is not None and row.state != "not_needed":
        payments.queue_invoice(db, row)
    return row


# ── Queueing ──────────────────────────────────────────────────────────────────


def enabled() -> bool:
    """Whether this server decides confirmations at all."""
    return bool(settings.inbox_confirmations_enabled)


def queue_confirmation(db: Session, order_id: str) -> None:
    enqueue(
        db,
        JobKind.INBOX_CONFIRM_ORDER,
        {"order_id": order_id},
        dedupe_key=f"{JobKind.INBOX_CONFIRM_ORDER}:{order_id}",
    )


def queue_if_new(db: Session, order: OrderIndex) -> bool:
    """Queue ``order``'s confirmation if it is fresh and not yet decided.

    Called each time an order is indexed. Reads only our own tables, so an
    order synced for the tenth time costs one small query and no job. An
    order whose payment request is open is closed here once it is paid
    (ADR 0062).
    """
    if not enabled():
        return False
    from app.services.inbox.payments import note_paid

    note_paid(db, order)
    if order.placed_at is None or order.placed_at < utcnow() - FRESH_FOR:
        return False
    if _recorded(db, order.shopify_order_id) is not None:
        return False
    queue_confirmation(db, order.shopify_order_id)
    return True


def unconfirmed_recent(db: Session, *, limit: int = SWEEP_BATCH) -> list[str]:
    """Fresh orders in the index with no confirmation on record, oldest first."""
    return list(
        db.scalars(
            select(OrderIndex.shopify_order_id)
            .where(
                OrderIndex.placed_at >= utcnow() - FRESH_FOR,
                ~exists().where(
                    OrderConfirmation.shopify_order_id == OrderIndex.shopify_order_id
                ),
            )
            .order_by(OrderIndex.placed_at)
            .limit(limit)
        )
    )


@register_handler(JobKind.INBOX_CONFIRM_ORDER)
def _handle_confirm_order(db: Session, payload: dict) -> None:
    order_id = str(payload.get("order_id") or "").strip()
    if not order_id:
        raise PermanentFailure(
            f"{JobKind.INBOX_CONFIRM_ORDER} requires an order_id; got payload keys "
            f"{sorted(payload)!r}"
        )
    # Queued while it was on, run after it was turned off: read nothing and
    # keep nothing. The job simply finishes.
    if not enabled():
        return
    confirm_order(db, order_id)


@register_handler(JobKind.INBOX_CONFIRM_SWEEP)
def _handle_confirm_sweep(db: Session, payload: dict) -> None:
    if not enabled():
        return
    # An order a crash left half-sent is shown as failed, never sent again.
    from app.services.inbox.outbound import recover_interrupted

    interrupted = recover_interrupted(db)
    if interrupted:
        logger.warning("%s confirmations were interrupted while sending", interrupted)
    order_ids = unconfirmed_recent(db)
    for order_id in order_ids:
        queue_confirmation(db, order_id)
    if order_ids:
        logger.info("confirmation sweep queued %s recent orders", len(order_ids))

    # A payment request's one reminder, 24 hours on (ADR 0062).
    from app.services.inbox import payments

    if payments.enabled():
        reminders = payments.queue_reminders(db)
        if reminders:
            logger.info("confirmation sweep queued %s payment reminders", reminders)
