"""Orders that left and that nobody will ever report on. ADR 0051.

Delivery comes from Shopify (ADR 0023), and Shopify learns it from the courier.
**Only Bosta reports back.** An order shipped with no tracking number, or with
Aramex or DHL, stays *fulfilled* in Shopify for ever unless a person marks it
delivered or cancels it there - and on staging, 28 September, 211 orders were
in exactly that state, some since February.

The platform does not guess. A parcel nobody has confirmed is pending, which
is counted and paid (ADR 0040), and it stays that way until Shopify says
otherwise. What was missing was anybody *seeing* them: this is that list, so
the fix happens where the truth lives - one click in Shopify - and the next
sweep carries it here.

Read from `order_index.fulfilments`, the per-fulfilment facts ADR 0051 keeps,
so the list costs no Shopify call.
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.modules.affiliates.models.attributed_orders import AttributedOrder
from app.shared.models.orders import OrderIndex
from app.shared.services.shopify.fulfilment import (
    DELIVERED_STATUSES,
    FAILED_STATUSES,
    frozen_fulfilments,
)

#: How long a fulfilment may go without courier news before somebody looks.
#: Bosta's slowest normal delivery on the audit was well inside a week.
STALE_AFTER_DAYS = 14

#: The only courier that reports delivery back into Shopify.
REPORTING_COURIER = "bosta"

NO_TRACKING = "no_tracking"
OTHER_COURIER = "other_courier"
COURIER_SILENT = "courier_silent"
NOT_YET_READ = "not_yet_read"

#: Order of the groups on the screen: the ones nothing will ever fix first.
GROUPS = (NO_TRACKING, OTHER_COURIER, COURIER_SILENT, NOT_YET_READ)


def _waiting(fulfilments: list[dict] | None, return_status: str | None) -> list[dict]:
    """The counting fulfilments that have neither arrived nor failed."""
    counted = frozen_fulfilments(
        [
            # Stored rows use snake_case; the rules read Shopify's names.
            {
                "status": row.get("status"),
                "displayStatus": row.get("display_status"),
                "createdAt": row.get("created_at"),
                "deliveredAt": row.get("delivered_at"),
                "_row": row,
            }
            for row in (fulfilments or [])
        ],
        return_status=return_status,
    )
    return [
        row["_row"]
        for row in counted
        if str(row.get("displayStatus") or "").upper()
        not in DELIVERED_STATUSES | FAILED_STATUSES
    ]


def _group(waiting: list[dict]) -> tuple[str, str | None]:
    """Why nothing will report on it, and the courier named, if any."""
    if not waiting:
        return NOT_YET_READ, None
    last = waiting[-1]
    company = last.get("company")
    if not last.get("tracked"):
        return NO_TRACKING, company
    if not company or company.strip().lower() != REPORTING_COURIER:
        return OTHER_COURIER, company
    return COURIER_SILENT, company


def admin_url(shop_domain: str | None, order_id: str) -> str | None:
    """The order's page in the Shopify admin, where it is actually fixed."""
    domain = (shop_domain or "").strip().removeprefix("https://").rstrip("/")
    if not domain:
        return None
    return f"https://{domain}/admin/orders/{order_id}"


def stale_fulfilments(
    db: Session, *, days: int = STALE_AFTER_DAYS, shop_domain: str | None = None
) -> dict:
    """Undelivered orders older than `days`, grouped by why.

    *Not yet read* is an order indexed before its fulfilments were kept; the
    six-hourly resync fills it in, after which it lands in its real group.
    """
    cutoff = utcnow() - timedelta(days=days)
    attributed = set(
        db.scalars(
            select(AttributedOrder.shopify_order_id)
            .join(OrderIndex, OrderIndex.shopify_order_id == AttributedOrder.shopify_order_id)
            .where(OrderIndex.delivery_state == "in_flight")
        )
    )
    rows = db.scalars(
        select(OrderIndex)
        .where(OrderIndex.delivery_state == "in_flight")
        .where(OrderIndex.cancelled_at.is_(None))
        .where(OrderIndex.placed_at < cutoff)
        .order_by(OrderIndex.placed_at.asc())
    )

    groups: dict[str, list[dict]] = {name: [] for name in GROUPS}
    now = utcnow()
    for order in rows:
        waiting = _waiting(order.fulfilments, order.return_status)
        if order.fulfilments is not None and not waiting:
            # Every counting fulfilment arrived or failed: in flight only by a
            # mix (docs/limits.md), which is not something a courier will fix.
            continue
        group, company = _group(waiting if order.fulfilments is not None else [])
        groups[group].append(
            {
                "shopify_order_id": order.shopify_order_id,
                "order_number": order.order_number,
                "placed_at": order.placed_at.isoformat() if order.placed_at else None,
                "days": (now - order.placed_at).days if order.placed_at else None,
                "courier": company,
                "attributed": order.shopify_order_id in attributed,
                "admin_url": admin_url(shop_domain, order.shopify_order_id),
            }
        )

    return {
        "after_days": days,
        "total": sum(len(items) for items in groups.values()),
        "groups": [{"reason": name, "orders": groups[name]} for name in GROUPS],
    }
