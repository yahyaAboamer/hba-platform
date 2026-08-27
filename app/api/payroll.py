"""Payroll over HTTP: run a month, see what blocks it, agree it.

§11. The endpoints behind month-end.

## Approval can be previewed, and the preview runs the same code

§11.3 requires seeing every model, amount and blocker **before** committing. The
honest way to do that is a flag on the same endpoint, so the preview and the
commit compute identically — a separate preview path is a second implementation
that can drift, and it drifts silently because nobody compares them.

## Approving and reopening are different permissions

`payroll.approve` agrees an open month. `payroll.reopen` reaches back into one
somebody has already been paid for. Those are different acts and §5.1 separates
them.

## Bulk approval is all-or-nothing per model, not per run

One model failing does not stop the others — twenty months are twenty separate
obligations, and refusing them all because Nour's target is unverified would
make month-end hostage to a single row. What each model got is reported
individually.
"""

from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.businesstime import parse_month
from app.core.money import format_egp
from app.core.permissions import Permission
from app.db import get_session
from app.models.affiliates import AffiliateProfile
from app.models.identity import UserAccount
from app.services.affiliates import list_affiliates
from app.services.payroll import (
    approve_month,
    blockers_for,
    carry_forward_summary,
    get_month,
    historical_sales,
    is_historical,
    months_left_reopened,
    reconciliation_for,
    reopen_month,
    snapshots_for,
)

router = APIRouter(prefix="/api/payroll")


class ApproveBody(BaseModel):
    affiliate_ids: list[int]
    #: §11.3. Compute exactly what would happen and write nothing.
    preview: bool = True


class ReopenBody(BaseModel):
    affiliate_ids: list[int]
    reason: str = Field(min_length=1, max_length=500)


def _month_or_400(month: str) -> str:
    try:
        return parse_month(month)
    except ValueError as exc:
        raise HTTPException(400, "A month looks like 2026-04") from exc


def _affiliate_or_404(db: Session, affiliate_id: int) -> AffiliateProfile:
    affiliate = db.get(AffiliateProfile, affiliate_id)
    if affiliate is None:
        raise HTTPException(404, "No such affiliate")
    return affiliate


def _display_piastres(exact: Decimal | str) -> int:
    """A fractional-piastre figure as whole piastres, **for reading only**.

    `Decimal`, never `float`. `round(float(x))` is the habit this codebase
    exists to avoid: it works until the one figure sitting on a boundary, and
    that figure is somebody's pay (ADR 0002).

    The payout itself is rounded once, on the total (ADR 0004). This rounds a
    line so it can be shown beside the others; the two are not the same
    operation and the total is never assembled from these.
    """
    return int(Decimal(exact).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _row(db: Session, affiliate: AffiliateProfile, month: str) -> dict:
    """One model's month: the figure, what blocks it, and what it carries."""
    if is_historical(month):
        # §11.2. Sales only, never a commission figure - March's rates exist
        # only in the old system and in somebody's memory.
        return {**historical_sales(db, affiliate, month), "name": affiliate.name}

    blockers, calculation = blockers_for(db, affiliate, month)
    payroll_month = get_month(db, affiliate, month)
    snapshot = payroll_month.active_snapshot if payroll_month else None

    return {
        "affiliate_id": affiliate.id,
        "name": affiliate.name,
        "month": month,
        "calculation_state": (
            payroll_month.calculation_state if payroll_month else "draft"
        ),
        "orders": {
            "earned": calculation.earned_orders,
            "pending": calculation.pending_orders,
            "void": calculation.void_orders,
        },
        # What it would come to if calculated right now. For an approved month
        # this is **not** what was agreed: an order settling after approval
        # changes the calculation and never the obligation (§11.4).
        "obligation_piastres": calculation.payout_piastres,
        "obligation": format_egp(calculation.payout_piastres),
        # What was actually agreed, or null if nothing has been. A screen
        # showing the recalculated figure under the word "approved" would be
        # presenting a working number as a debt.
        "approved_obligation_piastres": (
            snapshot.approved_obligation_piastres if snapshot else None
        ),
        "approved_obligation": (
            format_egp(snapshot.approved_obligation_piastres) if snapshot else None
        ),
        "exact_unrounded_piastres": str(calculation.exact_unrounded_piastres),
        # §11.4. Orders from earlier approved months that this one is paying,
        # each at **its own** month's rate - the common path, not an edge case.
        # Both figures are given: the sales carried, and what they are worth.
        # A line that showed only sales would read as roughly ten times the
        # money it actually adds.
        "carried_forward": [
            {
                "from_month": line["from_month"],
                "orders": line["orders"],
                "base_piastres": line["base_piastres"],
                "commission_rate_bp": line["commission_rate_bp"],
                "commission_piastres": _display_piastres(line["commission_piastres"]),
            }
            for line in calculation.carried_lines
        ],
        "carried_piastres": _display_piastres(calculation.carried_piastres),
        "blockers": blockers,
        "is_payable": not blockers,
        "version": snapshot.version if snapshot else None,
    }


@router.get("/{month}")
def payroll_month_view(
    month: str,
    include_archived: bool = False,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Every model for one month, with what stands in each one's way."""
    month = _month_or_400(month)
    rows = [
        _row(db, affiliate, month)
        for affiliate in list_affiliates(db, include_archived=include_archived)
    ]
    payable = [row for row in rows if row.get("is_payable")]

    return {
        "month": month,
        "is_historical": is_historical(month),
        "affiliates": rows,
        "totals": {
            "affiliates": len(rows),
            "payable_affiliates": len(payable),
            "blocked_affiliates": len(rows) - len(payable),
            "obligation_piastres": sum(
                row["obligation_piastres"] for row in payable
            ),
            "obligation": format_egp(
                sum(row["obligation_piastres"] for row in payable)
            ),
        },
    }


@router.post("/{month}/approve")
def approve(
    month: str,
    body: ApproveBody,
    actor: UserAccount = Depends(require_permission(Permission.PAYROLL_APPROVE)),
    db: Session = Depends(get_session),
) -> dict:
    """Agree what a month is worth, for one model or many.

    **Defaults to a preview** (§11.3). Committing is the deliberate act, so it
    is the one that has to be asked for - a default that writes is a default
    that eventually writes by accident.
    """
    month = _month_or_400(month)
    results = []

    for affiliate_id in body.affiliate_ids:
        affiliate = _affiliate_or_404(db, affiliate_id)
        blockers, calculation = blockers_for(db, affiliate, month)

        outcome = {
            "affiliate_id": affiliate.id,
            "name": affiliate.name,
            "obligation_piastres": calculation.payout_piastres,
            "obligation": format_egp(calculation.payout_piastres),
            "blockers": blockers,
            "approved": False,
            "version": None,
        }

        if not blockers and not body.preview:
            snapshot = approve_month(
                db,
                affiliate,
                month,
                actor_id=actor.id,
                actor_email=actor.email,
            )
            outcome["approved"] = True
            outcome["version"] = snapshot.version
            outcome["obligation_piastres"] = snapshot.approved_obligation_piastres
            outcome["obligation"] = format_egp(snapshot.approved_obligation_piastres)

        results.append(outcome)

    if not body.preview:
        db.commit()

    approved = [row for row in results if row["approved"]]
    return {
        "month": month,
        "preview": body.preview,
        "results": results,
        "totals": {
            "approved": len(approved),
            "blocked": len([row for row in results if row["blockers"]]),
            "obligation_piastres": sum(row["obligation_piastres"] for row in approved),
        },
    }


@router.post("/{month}/reopen")
def reopen(
    month: str,
    body: ReopenBody,
    actor: UserAccount = Depends(require_permission(Permission.PAYROLL_REOPEN)),
    db: Session = Depends(get_session),
) -> dict:
    """Return an approved month to draft, with a written reason.

    A different permission from approving, because reaching back into a month
    somebody has been paid for is a different act (§5.1).
    """
    month = _month_or_400(month)
    reopened = []

    for affiliate_id in body.affiliate_ids:
        affiliate = _affiliate_or_404(db, affiliate_id)
        try:
            reopen_month(
                db,
                affiliate,
                month,
                reason=body.reason,
                actor_id=actor.id,
                actor_email=actor.email,
            )
        except ValueError as exc:
            db.rollback()
            raise HTTPException(
                400, f"{affiliate.name}: {exc}. Nothing reopened."
            ) from exc
        reopened.append({"affiliate_id": affiliate.id, "name": affiliate.name})

    db.commit()
    return {"month": month, "reopened": reopened}


@router.get("/{month}/reopened")
def stuck_reopened(
    month: str,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Months reopened and never re-approved (§11.5).

    **The dangerous state is not reopening; it is forgetting.** A month in draft
    with payments already made against a superseded snapshot is a balance
    nobody is watching.
    """
    month = _month_or_400(month)
    return {
        "month": month,
        "left_reopened": [
            {
                "affiliate_id": row.affiliate_id,
                "name": row.affiliate.name,
                "month": row.month,
            }
            for row in months_left_reopened(db, month)
        ],
    }
