"""An unpaid international order's payment request (ADR 0062).

An order shipped outside Egypt that still owes money is sent Shopify's own
payment link on WhatsApp instead of the confirmation, and Shopify is asked
to email its invoice. The request is an ``order_confirmation`` row with
``kind = 'payment'``, so it is decided, claimed and sent by the
confirmation's own machinery (``confirmations``, ``outbound``); this module
holds what is different:

- **The link is read from Shopify each time a message is sent**, and never
  stored: it lets anyone who holds it pay the order. Only what follows the
  approved fixed part (``INBOX_PAYMENT_LINK_BASE``) is sent, and a link that
  does not begin with it is not sent at all.
- **One reminder**, 24 hours after the first message, if the order still
  owes money.
- **Paid is noticed from the order's own sync**, which closes the request.
- **The invoice email is asked for once**, through the second Shopify app,
  only on a server that may message customers.

Off unless the server is told (``INBOX_PAYMENT_REQUESTS_ENABLED``).
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.core.businesstime import utcnow
from app.models.inbox import InboxConnection, OrderConfirmation
from app.models.orders import OrderIndex
from app.services.inbox import tags
from app.services.jobs import JobKind, PermanentFailure, enqueue
from app.services.shopify.client import ShopifyClient, ShopifyError
from app.services.shopify.sync import PERMANENT, build_client, order_gid
from app.worker import register_handler

logger = logging.getLogger(__name__)

#: The approved message, by the name and language Meta holds it under.
TEMPLATE = "international_payment"
LANGUAGE = "en"

#: The one reminder, this long after the first message.
REMIND_AFTER = timedelta(hours=24)
#: Unpaid this long after the first message, the order needs a person.
NEEDS_A_PERSON_AFTER = timedelta(hours=72)

#: How Shopify says an order no longer owes anything.
PAID_STATUSES = frozenset({"paid", "refunded", "partially_refunded"})

#: What the request needs from the order, and nothing else.
PAYMENT_ORDER = """
query PaymentOrder($id: ID!) {
  order(id: $id) {
    cancelledAt
    totalOutstandingSet { shopMoney { amount currencyCode } }
    paymentCollectionDetails { additionalPaymentCollectionUrl }
  }
}
"""

INVOICE_SEND = """
mutation PaymentInvoiceSend($id: ID!) {
  orderInvoiceSend(id: $id) { userErrors { message } }
}
"""

PAID = "Paid before the payment link went out."
CANCELLED = "Cancelled before the payment link went out."
NOT_FOUND = "Shopify has no such order."
LINK_MISMATCH = (
    "Shopify's payment link does not match the approved message's link, so it "
    "was not sent. The store's domain may have changed (ADR 0062)."
)
CANNOT_READ = "The order could not be read from Shopify: "
INVOICE_UNANSWERED = (
    "Shopify did not answer when asked to email the invoice. Check the order's "
    "timeline in Shopify before sending one by hand."
)


def enabled() -> bool:
    """Whether this server sends payment requests at all."""
    return bool(settings.inbox_confirmations_enabled and settings.inbox_payment_requests_enabled)


# ── What an order owes ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Owed:
    """What Shopify says the order still owes, and where it is paid."""

    cancelled: bool
    amount: Decimal
    currency: str
    link: str | None


def _amount(raw: Any) -> Decimal:
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def owed_from(node: dict) -> Owed:
    """Read ``Owed`` from an order node. Pure."""
    money = (node.get("totalOutstandingSet") or {}).get("shopMoney") or {}
    collection = node.get("paymentCollectionDetails") or {}
    return Owed(
        cancelled=bool(node.get("cancelledAt")),
        amount=_amount(money.get("amount")),
        currency=str(money.get("currencyCode") or "").upper()[:3],
        link=collection.get("additionalPaymentCollectionUrl") or None,
    )


def money_text(amount: Decimal, currency: str) -> str:
    """The amount as the message says it: ``EGP 5,850.00``."""
    return f"{currency} {amount:,.2f}".strip()


def read_owed(order_id: str, client: ShopifyClient | None = None) -> Owed | None:
    """Ask Shopify what order ``order_id`` owes. None if it has no such order.

    Through the connection that reads money, which stays read-only.
    """
    data = (client or build_client()).execute(PAYMENT_ORDER, {"id": order_gid(order_id)})
    node = (data or {}).get("order")
    return owed_from(node) if node else None


def link_suffix(link: str | None) -> str | None:
    """What follows the approved fixed part of the link, or None if the link
    does not begin with it."""
    base = settings.inbox_payment_link_base
    if not base or not link or not link.startswith(base) or len(link) == len(base):
        return None
    return link[len(base):]


def components(row: OrderConfirmation, suffix: str) -> list[dict[str, Any]]:
    """The approved message's three details and its *Pay now* button."""
    details = (row.customer_name or "there", row.order_name or "", row.total_text or "")
    return [
        {"type": "body", "parameters": [{"type": "text", "text": detail} for detail in details]},
        {
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [{"type": "text", "text": suffix}],
        },
    ]


# ── The first message ─────────────────────────────────────────────────────────


def link_for(
    db: Session, row: OrderConfirmation, reader: ShopifyClient | None = None
) -> str | None:
    """The link to send with a request the sender has just claimed.

    None when there is nothing to send, with the row already saying why:
    paid or cancelled since it was decided (``not_needed``), a link that
    does not match (``failed``), or Shopify not answering (back to
    ``pending``, tried again like a message WhatsApp did not take).
    """
    from app.services.inbox.outbound import MAX_ATTEMPTS, RETRY_AFTER, queue_confirmation_send

    row.updated_at = utcnow()
    try:
        owed = read_owed(row.shopify_order_id, reader)
    except PERMANENT as exc:
        row.state, row.last_error = "failed", (CANNOT_READ + str(exc))[:300]
        return None
    except ShopifyError as exc:
        row.attempts += 1
        row.last_error = (CANNOT_READ + str(exc))[:300]
        if row.attempts >= MAX_ATTEMPTS:
            row.state = "failed"
            return None
        row.state = "pending"
        row.next_attempt_at = utcnow() + RETRY_AFTER[min(row.attempts, len(RETRY_AFTER)) - 1]
        queue_confirmation_send(
            db, row.shopify_order_id, attempt=row.attempts, run_after=row.next_attempt_at
        )
        return None

    if owed is None:
        row.state, row.last_error = "not_needed", NOT_FOUND
        return None
    if owed.cancelled:
        row.state, row.last_error = "not_needed", CANCELLED
        return None
    if owed.amount <= 0:
        row.state, row.last_error = "not_needed", PAID
        return None
    suffix = link_suffix(owed.link)
    if suffix is None:
        row.state, row.last_error = "failed", LINK_MISMATCH
        return None
    # What it owes now, which is what the link will ask for.
    row.total_text = money_text(owed.amount, owed.currency)
    return suffix


# ── The reminder ──────────────────────────────────────────────────────────────


def _claim_reminder(order_id: str) -> bool:
    """Take the reminder, in a transaction of its own, before WhatsApp is
    asked: whatever happens next, it is never sent a second time."""
    from app.db import SessionLocal

    with SessionLocal() as own:
        claimed = own.execute(
            update(OrderConfirmation)
            .where(
                OrderConfirmation.shopify_order_id == order_id,
                OrderConfirmation.kind == "payment",
                OrderConfirmation.reminded_at.is_(None),
            )
            .values(reminded_at=utcnow(), updated_at=utcnow())
        ).rowcount
        own.commit()
    return claimed == 1


def reminder_due(row: OrderConfirmation | None, now=None) -> bool:
    now = now or utcnow()
    return bool(
        row is not None
        and row.kind == "payment"
        and row.state == "sent"
        and row.paid_at is None
        and row.reminded_at is None
        and row.sent_at is not None
        and now - NEEDS_A_PERSON_AFTER <= row.sent_at <= now - REMIND_AFTER
    )


def send_reminder(
    db: Session,
    order_id: str,
    *,
    client=None,
    reader: ShopifyClient | None = None,
    claim: Callable[[str], bool] = _claim_reminder,
) -> OrderConfirmation | None:
    """Send a request's one reminder, if it is due and the order still owes."""
    from app.services.inbox import outbound, sending
    from app.services.inbox.events import _conversation
    from app.services.inbox.meta import MetaError

    row = db.scalar(
        select(OrderConfirmation).where(OrderConfirmation.shopify_order_id == order_id)
    )
    if not reminder_due(row) or not row.phone or sending.refusal(db, row.phone):
        return row
    try:
        owed = read_owed(order_id, reader)
    except PERMANENT as exc:
        raise PermanentFailure(f"Cannot read order {order_id} for its reminder: {exc}") from exc
    if owed is None or owed.cancelled:
        return row
    if owed.amount <= 0:
        mark_paid(db, row)
        return row
    suffix = link_suffix(owed.link)
    if suffix is None:
        row.last_error = LINK_MISMATCH
        return row
    row.total_text = money_text(owed.amount, owed.currency)

    owned = client is None
    client = client or outbound._client(db)
    try:
        if not claim(order_id):
            return row
        row.reminded_at = utcnow()
        conversation = _conversation(db, row.phone, None)
        body = f"Payment reminder · {row.order_name or order_id}"
        try:
            wa_message_id = client.send_template(
                row.phone, TEMPLATE, LANGUAGE, components(row, suffix)
            )
        except MetaError as exc:
            row.last_error = f"The reminder did not go: {exc}"[:300]
            outbound.record_outbound(
                db, conversation, kind="template", body=body, origin="automatic",
                status="failed", error=str(exc), template_name=TEMPLATE, order_id=order_id,
            )
            return row
    finally:
        if owned:
            client.close()
    outbound.record_outbound(
        db, conversation, kind="template", body=body, origin="automatic", status="sent",
        wa_message_id=wa_message_id, template_name=TEMPLATE,
        extra={"buttons": ["Pay now"]}, order_id=order_id,
    )
    row.updated_at = utcnow()
    return row


def due_reminders(db: Session) -> list[str]:
    """Requests whose reminder is due, on orders not cancelled or paid."""
    now = utcnow()
    return list(
        db.scalars(
            select(OrderConfirmation.shopify_order_id)
            .join(OrderIndex, OrderIndex.shopify_order_id == OrderConfirmation.shopify_order_id)
            .where(
                OrderConfirmation.kind == "payment",
                OrderConfirmation.state == "sent",
                OrderConfirmation.paid_at.is_(None),
                OrderConfirmation.reminded_at.is_(None),
                OrderConfirmation.sent_at <= now - REMIND_AFTER,
                OrderConfirmation.sent_at >= now - NEEDS_A_PERSON_AFTER,
                OrderIndex.cancelled_at.is_(None),
            )
            .order_by(OrderConfirmation.sent_at)
        )
    )


def queue_reminders(db: Session) -> int:
    order_ids = due_reminders(db)
    for order_id in order_ids:
        enqueue(
            db,
            JobKind.INBOX_PAYMENT_REMINDER,
            {"order_id": order_id},
            dedupe_key=f"{JobKind.INBOX_PAYMENT_REMINDER}:{order_id}",
        )
    return len(order_ids)


# ── Paid ──────────────────────────────────────────────────────────────────────


def mark_paid(db: Session, row: OrderConfirmation) -> None:
    """Close the request. Its tag changes only if a message went out - a
    server that may not message customers (``would_send``) never writes to
    Shopify."""
    row.paid_at = utcnow()
    row.updated_at = row.paid_at
    db.flush()
    tags.queue_tags(db, row)


def note_paid(db: Session, order: OrderIndex) -> bool:
    """Close the order's request if the order is now paid. Called each time
    an order is indexed; reads only our own tables."""
    if str(order.financial_status or "").lower() not in PAID_STATUSES:
        return False
    row = db.scalar(
        select(OrderConfirmation).where(
            OrderConfirmation.shopify_order_id == order.shopify_order_id,
            OrderConfirmation.kind == "payment",
            OrderConfirmation.paid_at.is_(None),
        )
    )
    if row is None or row.state == "not_needed":
        return False
    mark_paid(db, row)
    return True


def needs_a_person(row: OrderConfirmation, now=None) -> bool:
    """Unpaid three days after the link went out: somebody should get in
    touch. Nothing is ever cancelled automatically."""
    now = now or utcnow()
    return bool(
        row.kind == "payment"
        and row.state == "sent"
        and row.paid_at is None
        and row.sent_at is not None
        and row.sent_at <= now - NEEDS_A_PERSON_AFTER
    )


# ── The invoice email ─────────────────────────────────────────────────────────


def invoice_allowed(db: Session) -> bool:
    """Only a server that may message customers asks Shopify to email one.
    There are no test addresses: staging never emails a customer."""
    connection = db.get(InboxConnection, 1)
    return bool(
        enabled()
        and settings.inbox_send_to_customers
        and connection is not None
        and connection.sending_enabled
    )


def queue_invoice(db: Session, row: OrderConfirmation) -> bool:
    if row.kind != "payment" or row.invoice_at is not None or not invoice_allowed(db):
        return False
    enqueue(
        db,
        JobKind.INBOX_SEND_INVOICE,
        {"order_id": row.shopify_order_id},
        dedupe_key=f"{JobKind.INBOX_SEND_INVOICE}:{row.shopify_order_id}",
    )
    return True


def _claim_invoice(order_id: str) -> bool:
    from app.db import SessionLocal

    with SessionLocal() as own:
        claimed = own.execute(
            update(OrderConfirmation)
            .where(
                OrderConfirmation.shopify_order_id == order_id,
                OrderConfirmation.kind == "payment",
                OrderConfirmation.invoice_at.is_(None),
            )
            .values(invoice_at=utcnow(), updated_at=utcnow())
        ).rowcount
        own.commit()
    return claimed == 1


def send_invoice(
    db: Session,
    order_id: str,
    *,
    client: ShopifyClient | None = None,
    reader: ShopifyClient | None = None,
    claim: Callable[[str], bool] = _claim_invoice,
) -> OrderConfirmation | None:
    """Ask Shopify to email the order's invoice, once, while it still owes."""
    row = db.scalar(
        select(OrderConfirmation).where(OrderConfirmation.shopify_order_id == order_id)
    )
    if row is None or row.kind != "payment" or row.invoice_at is not None:
        return row
    if not invoice_allowed(db):
        return row
    try:
        owed = read_owed(order_id, reader)
    except PERMANENT as exc:
        raise PermanentFailure(f"Cannot read order {order_id} for its invoice: {exc}") from exc
    if owed is None or owed.cancelled or owed.amount <= 0:
        return row

    try:
        client = client or tags.tags_client(db)
    except PermanentFailure as exc:
        row.invoice_error = str(exc)[:300]
        return row
    if not claim(order_id):
        return row
    row.invoice_at = utcnow()
    try:
        # Never retried: a timeout may have sent it, and she gets one email.
        data = client.execute(INVOICE_SEND, {"id": order_gid(order_id)}, at_most_once=True)
    except PERMANENT as exc:
        row.invoice_error = f"Shopify refused the invoice email: {exc}"[:300]
        return row
    except ShopifyError:
        # Whether it went is unknown. It is not asked for again.
        row.invoice_error = INVOICE_UNANSWERED
        return row
    errors = ((data or {}).get("orderInvoiceSend") or {}).get("userErrors") or []
    if errors:
        row.invoice_error = (
            "Shopify refused the invoice email: "
            + "; ".join(str(error.get("message")) for error in errors)
        )[:300]
    else:
        row.invoice_error = None
    return row


# ── Jobs ──────────────────────────────────────────────────────────────────────


def _order_id(kind: str, payload: dict) -> str:
    order_id = str(payload.get("order_id") or "").strip()
    if not order_id:
        raise PermanentFailure(f"{kind} requires an order_id; got payload keys {sorted(payload)!r}")
    return order_id


@register_handler(JobKind.INBOX_PAYMENT_REMINDER)
def _handle_reminder(db: Session, payload: dict) -> None:
    order_id = _order_id(JobKind.INBOX_PAYMENT_REMINDER, payload)
    if not enabled():
        return
    from app.services.inbox.outbound import NotSent

    try:
        send_reminder(db, order_id)
    except NotSent as exc:
        raise PermanentFailure(f"Cannot send order {order_id}'s reminder: {exc}") from exc


@register_handler(JobKind.INBOX_SEND_INVOICE)
def _handle_invoice(db: Session, payload: dict) -> None:
    order_id = _order_id(JobKind.INBOX_SEND_INVOICE, payload)
    row = send_invoice(db, order_id)
    if row is not None and row.invoice_error:
        logger.warning("order %s: invoice email not sent: %s", order_id, row.invoice_error)
