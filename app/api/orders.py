"""The order index, over HTTP. Read-only.

No money decision lives here. `attributed_order` and `payroll_snapshot` already
decided what an order is worth and who it is paid by; this reads those
decisions rather than making any. That is the whole reason this screen needs
no permission beyond `affiliates.view` - it cannot change what anybody is owed.

**Why a screen for this at all**, when every figure already appears somewhere
on Affiliates, Payroll or Payments: those three answer "what does she earn"
and this answers "why does this *order* read the way it does" - whose code it
carried, whether Shopify has said it arrived, which payroll actually paid it.
That is the question support ends up asking about one order at a time, and it
needs the order as the unit, not the model or the month.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.businesstime import parse_month
from app.core.money import format_egp
from app.core.permissions import Permission
from app.db import get_session
from app.models.affiliates import AffiliateProfile
from app.models.attributed_orders import AttributedOrder
from app.models.identity import UserAccount
from app.models.orders import OrderIndex
from app.services.attribution import AttributionOutcome, resolve_order

router = APIRouter(prefix="/api/orders")


def _month_or_400(month: str) -> str:
    try:
        return parse_month(month)
    except ValueError as exc:
        raise HTTPException(400, "A month looks like 2026-04") from exc


def _render(db: Session, order: OrderIndex, names: dict[int, str]) -> dict:
    """One order: whose it is, what it is worth, and what happened to it.

    Attribution is **re-resolved** here rather than read off `attributed_order`
    alone, because an unattributed or held order has no row there at all - the
    screen has to be able to show those states too, not only the ones that
    already have money attached.

    One `resolve_order` call per order rather than a batched query: HBA's
    entire order history is a few hundred rows (§10.2 - the index exists
    precisely because it is cheap to keep all of them), so a per-order lookup
    against a few dozen registered codes costs nothing measurable. Worth
    revisiting only if that scale changes by an order of magnitude (ADR 0019).
    """
    attributed = db.get(AttributedOrder, order.shopify_order_id)
    decision = resolve_order(db, order)

    base = {
        "shopify_order_id": order.shopify_order_id,
        "order_number": order.order_number,
        "placed_at": order.placed_at.isoformat(),
        "business_month": order.business_month,
        "discount_codes": order.discount_codes,
        "total_piastres": order.total_piastres,
        "total": format_egp(order.total_piastres),
        "delivery_state": order.delivery_state,
        "delivery_status": order.delivery_status,
        "cancelled": order.cancelled_at is not None,
    }

    if decision.outcome == AttributionOutcome.HELD:
        return {
            **base,
            "outcome": "held",
            "affiliate_id": None,
            "affiliate_name": None,
            "matched_codes": decision.matched_codes,
            "commission_state": None,
            "base_piastres": None,
            "is_carried": False,
            "paid_in_month": None,
        }

    if decision.outcome == AttributionOutcome.UNATTRIBUTED or attributed is None:
        return {
            **base,
            "outcome": "unattributed",
            "affiliate_id": None,
            "affiliate_name": None,
            "matched_codes": [],
            "commission_state": None,
            "base_piastres": None,
            "is_carried": False,
            "paid_in_month": None,
        }

    settled_month = (
        _snapshot_month(db, attributed.settled_in_snapshot_id)
        if attributed.settled_in_snapshot_id is not None
        else None
    )

    return {
        **base,
        "outcome": "attributed",
        "affiliate_id": attributed.affiliate_id,
        "affiliate_name": names.get(attributed.affiliate_id, "—"),
        "matched_codes": decision.matched_codes,
        "commission_state": attributed.commission_state,
        "base_piastres": attributed.commission_base_piastres,
        "base": format_egp(attributed.commission_base_piastres),
        # §11.4. An order is "carried" once something other than its own
        # month's payroll is what actually paid it - the fact a model's own
        # arithmetic depends on and this screen exists partly to surface.
        "is_carried": settled_month is not None and settled_month != order.business_month,
        "paid_in_month": settled_month,
    }


def _snapshot_month(db: Session, snapshot_id: int) -> str | None:
    from app.models.payroll import PayrollMonth, PayrollSnapshot

    return db.scalar(
        select(PayrollMonth.month)
        .join(PayrollSnapshot, PayrollSnapshot.payroll_month_id == PayrollMonth.id)
        .where(PayrollSnapshot.id == snapshot_id)
    )


@router.get("/{month}")
def orders_for_month(
    month: str,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Every order placed in this business month, whoever it belongs to.

    Ordered newest first - the common reason to open this screen is "what just
    happened", not "what happened at the start of the month".
    """
    month = _month_or_400(month)
    orders = list(
        db.scalars(
            select(OrderIndex)
            .where(OrderIndex.business_month == month)
            .order_by(OrderIndex.placed_at.desc())
        )
    )
    names = {a.id: a.name for a in db.scalars(select(AffiliateProfile))}
    rows = [_render(db, order, names) for order in orders]

    held = [row for row in rows if row["outcome"] == "held"]
    unattributed = [row for row in rows if row["outcome"] == "unattributed"]
    carried = [row for row in rows if row["is_carried"]]

    return {
        "month": month,
        "orders": rows,
        "totals": {
            "orders": len(rows),
            "held": len(held),
            "unattributed": len(unattributed),
            "carried": len(carried),
        },
    }


@router.get("/lookup/{order_number}")
def find_order(
    order_number: str,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """One order, by its Shopify order number - #2001, or 2001, either works.

    The month grid is for browsing; this is for the actual support question,
    which arrives as an order number, never as a month.
    """
    needle = order_number.strip().lstrip("#")
    if not needle:
        raise HTTPException(400, "Give an order number")

    order = db.scalar(
        select(OrderIndex).where(OrderIndex.order_number.ilike(f"%{needle}"))
    )
    if order is None:
        raise HTTPException(404, f"No order matches {order_number!r}")

    names = {a.id: a.name for a in db.scalars(select(AffiliateProfile))}
    return _render(db, order, names)
