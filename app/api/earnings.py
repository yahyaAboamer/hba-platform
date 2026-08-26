"""What a month is worth, and what is stopping it.

The read side of the commission engine. Everything here is a calculation over
current data — nothing is stored, nothing is approved, and no money moves.
Freezing a figure is Phase 6's job, and doing it here would mean a month could
be settled by whoever happened to load a page.

## Blockers are the point, not an afterthought

A month with a blocker is **not payable**, and the endpoint says which one and
in what terms. §11.3 refuses approval on a hard blocker rather than warning
about it, so anyone about to run payroll needs to see them before they start,
not after.

## No customer ever appears here

Order number, date, what it was worth, whether it counts. Never a name, an
address, a phone number, or anything the customer typed. §6.5 keeps a model
away from anything deciding what she is owed; this keeps everybody away from
the customers.
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
from app.services.affiliates import list_affiliates
from app.services.commission.calculate import MonthCalculation, calculate_month

router = APIRouter(prefix="/api")


def _month_or_400(month: str) -> str:
    try:
        return parse_month(month)
    except ValueError as exc:
        raise HTTPException(400, "A month looks like 2026-04") from exc


def _render(result: MonthCalculation, name: str | None = None) -> dict:
    """One month, in both the exact figure and something readable.

    ``format_egp`` is display only and never feeds a calculation - the piastre
    integers beside it are what anything downstream should read.
    """
    return {
        "affiliate_id": result.affiliate_id,
        "name": name,
        "month": result.month,
        "orders": {
            "earned": result.earned_orders,
            "pending": result.pending_orders,
            "void": result.void_orders,
        },
        "sales": {
            "earned_piastres": result.earned_base_piastres,
            "earned": format_egp(result.earned_base_piastres),
            # Shown, never hidden. A model should be able to see what is
            # coming rather than wonder why her month looks small.
            "pending_piastres": result.pending_base_piastres,
            "pending": format_egp(result.pending_base_piastres),
        },
        "terms": {
            "type": result.compensation_type,
            "commission_rate_bp": result.commission_rate_bp,
            "fixed_piastres": result.fixed_piastres,
            "base_amount_piastres": result.base_amount_piastres,
        },
        "payout": {
            # Both figures, because the audit has to show what was calculated
            # as well as what would be paid (§9.6).
            "exact_unrounded_piastres": str(result.exact_unrounded_piastres),
            "piastres": result.payout_piastres,
            "display": format_egp(result.payout_piastres),
            "is_provisional": True,
        },
        "targets": {
            # Three answers, not two. `null` means nobody recorded what she
            # produced - which blocks her month, where missing the target does
            # not (§11.3).
            "achieved": result.target_achieved,
            "verified": result.target_verified,
            "guarantee_applied": result.guarantee_applied,
        },
        "is_house": result.is_house,
        "is_payable": result.is_payable,
        "blockers": result.blockers,
    }


@router.get("/affiliates/{affiliate_id}/earnings/{month}")
def affiliate_earnings(
    affiliate_id: int,
    month: str,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """One model's month, and every order behind the figure.

    The orders are included because a figure nobody can take apart is a figure
    nobody can argue with, and the first question anyone asks about a payout is
    *which sales is that?*
    """
    month = _month_or_400(month)
    affiliate = db.get(AffiliateProfile, affiliate_id)
    if affiliate is None:
        raise HTTPException(404, "No such affiliate")

    result = calculate_month(db, affiliate, month)

    orders = db.scalars(
        select(AttributedOrder)
        .where(AttributedOrder.affiliate_id == affiliate_id)
        .where(AttributedOrder.business_month == month)
        .order_by(AttributedOrder.shopify_order_id)
    )

    return {
        **_render(result, affiliate.name),
        "orders_detail": [
            {
                "shopify_order_id": row.shopify_order_id,
                "state": row.commission_state,
                "base_piastres": row.commission_base_piastres,
                "base": format_egp(row.commission_base_piastres),
                "counts_toward_payout": row.counts_toward_payout,
                "delivered_at": row.delivered_at.isoformat()
                if row.delivered_at
                else None,
                "return_status": row.return_status,
                "base_frozen_at": row.base_frozen_at.isoformat()
                if row.base_frozen_at
                else None,
            }
            for row in orders
        ],
    }


@router.get("/earnings/{month}")
def programme_earnings(
    month: str,
    include_archived: bool = False,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Every affiliate for one month - the payroll run, before it is a payroll.

    House accounts are **listed with their real sales and a payout of zero**
    (§8). Excluding them would report HBA's own orders as belonging to nobody,
    which is a different and wrong answer, and their dashboard is what makes
    verification possible in the first place.
    """
    month = _month_or_400(month)

    # Archived affiliates are excluded by default, exactly as list_affiliates
    # does it - the common question is "who is on the programme", not "who ever
    # was". An archived one still has real months behind her, so the flag is
    # there for the month somebody needs to go back and look at.
    rows = [
        _render(calculate_month(db, affiliate, month), affiliate.name)
        for affiliate in list_affiliates(db, include_archived=include_archived)
    ]

    payable = [row for row in rows if row["is_payable"]]
    return {
        "month": month,
        "affiliates": rows,
        "totals": {
            "affiliates": len(rows),
            # Only what could actually be paid today. A total that quietly
            # included blocked months would be a number nobody could act on.
            "payable_affiliates": len(payable),
            "payable_piastres": sum(row["payout"]["piastres"] for row in payable),
            "payable": format_egp(
                sum(row["payout"]["piastres"] for row in payable)
            ),
            "blocked_affiliates": len(rows) - len(payable),
        },
    }
