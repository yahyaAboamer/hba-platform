"""Today's *Orders, last 7 days* (Phase 2, batch 2.2).

The week's orders by where each one is now, for somebody holding both the
Inbox and Operations. From the order index, with the Inbox's confirmations and
Operations' Bosta mirror reached **only through their ``public``** (the import
check in ``pyproject.toml`` holds this module to it).

**Each order lands in exactly one row, the first that matches**, so the rows
always add up to the number placed:

1. ``cancelled`` - cancelled in Shopify, refunded or voided, delivery failed,
   any return activity, or the customer's answer was Cancel;
2. ``delivered`` - delivered, per the order index;
3. ``with_bosta`` - an order on Bosta that Bosta still has, or fulfilled in
   Shopify;
4. ``waiting`` - the confirmation went out and has no answer, or she asked
   for a change;
5. ``confirmed`` - she confirmed, or no confirmation was needed (paid);
6. ``not_asked`` - everything left: no confirmation, or it could not be sent.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import business_date, business_midnight
from app.modules.inbox import public as inbox
from app.modules.operations import public as operations
from app.shared.models.orders import OrderIndex

#: The financial states that undo an order (as commission reads them).
REVERSED = frozenset({"refunded", "voided"})

#: Row key, words, and the department that acts on it - in the mockup's order.
#: Delivered has none (an empty string, as the mockup draws it).
ROWS: tuple[tuple[str, str, str], ...] = (
    ("waiting", "Waiting for an answer", "Inbox"),
    ("confirmed", "Confirmed, not with Bosta", "Operations"),
    ("with_bosta", "With Bosta", "Operations"),
    ("delivered", "Delivered", ""),
    ("cancelled", "Cancelled or returned", "Operations"),
    ("not_asked", "Not asked to confirm", "Inbox"),
)

DAYS = 7


def where_it_is(
    order, confirmation: tuple[str, str | None] | None, on_bosta: bool
) -> str:
    """The one row an order belongs in, first match wins. ``order`` is an
    ``order_index`` row (or any object with its columns used here)."""
    state, answer = confirmation if confirmation else (None, None)
    if (
        order.cancelled_at is not None
        or str(order.financial_status or "").lower() in REVERSED
        or order.delivery_state == "failed"
        or order.return_activity
        or order.return_open
    ):
        return "cancelled"
    if order.delivery_state == "delivered":
        return "delivered"
    # After delivered: a customer who answered Cancel and then took the parcel
    # was delivered. Until then the answer counts as the cancellation.
    if answer == "cancelled":
        return "cancelled"
    if on_bosta or str(order.fulfillment_status or "").lower() == "fulfilled":
        return "with_bosta"
    if answer == "edit" or (state == "sent" and answer is None):
        return "waiting"
    if answer == "confirmed" or state == "not_needed":
        return "confirmed"
    return "not_asked"


def week(db: Session, now: datetime) -> dict:
    """The panel: the days, the number placed, and the rows."""
    last = business_date(now)
    first = last - timedelta(days=DAYS - 1)
    # Only the facts the rows are decided on, not whole order rows.
    orders = list(
        db.execute(
            select(
                OrderIndex.shopify_order_id,
                OrderIndex.order_number,
                OrderIndex.cancelled_at,
                OrderIndex.financial_status,
                OrderIndex.delivery_state,
                OrderIndex.fulfillment_status,
                OrderIndex.return_activity,
                OrderIndex.return_open,
            ).where(
                OrderIndex.placed_at >= business_midnight(first),
                OrderIndex.placed_at <= now,
            )
        )
    )
    confirmations = inbox.confirmations_for_orders(db, {o.shopify_order_id for o in orders})
    on_bosta = operations.order_numbers_on_bosta(db, {o.order_number for o in orders})
    bosta_at = operations.bosta_read_at(db)

    counted = {key: 0 for key, _, _ in ROWS}
    for order in orders:
        counted[
            where_it_is(order, confirmations.get(order.shopify_order_id), order.order_number in on_bosta)
        ] += 1

    return {
        "from": first.isoformat(),
        "to": last.isoformat(),
        "placed": len(orders),
        "bosta_as_of": bosta_at.isoformat() if bosta_at else None,
        "rows": [
            {"key": key, "label": label, "department": department, "count": counted[key]}
            for key, label, department in ROWS
            # Shown only when there is something in it.
            if key != "not_asked" or counted[key] > 0
        ],
    }
