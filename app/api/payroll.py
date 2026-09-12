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
from app.services.payroll import (
    SOURCE_MOVED,
    SourceMoved,
    approve_month,
    blockers_for,
    carried_into,
    carry_forward_summary,
    get_month,
    is_historical,
    months_left_reopened,
    reconciliation_for,
    snapshots_for,
    source_version,
)

router = APIRouter(prefix="/api/payroll")


class ApproveBody(BaseModel):
    affiliate_ids: list[int]
    #: §11.3. Compute exactly what would happen and write nothing.
    preview: bool = True
    #: 05B. What each model's month looked like in the preview the operator
    #: read, keyed by affiliate id.
    #:
    #: **Required to commit, and its absence is not agreement.** A caller that
    #: sends nothing has not been taught to check, and this route turns a
    #: working number into a debt - so a commit without one is refused rather
    #: than waved through. Ignored on a preview, which writes nothing.
    source_versions: dict[int, str] | None = None


class ReopenBody(BaseModel):
    affiliate_ids: list[int]
    reason: str = Field(min_length=1, max_length=500)


def _source_version_for(
    db: Session, affiliate: AffiliateProfile, month: str, calculation
) -> str:
    """The fingerprint of what this month is currently computed from.

    Reads the same two order sets `approve_month` reads, so the string the
    preview hands out is the string the commit recomputes. Any cheaper
    stand-in - a timestamp, a row count - would agree when the month had
    changed, which is the one case it exists for.
    """
    orders = list(
        db.scalars(
            select(AttributedOrder)
            .where(AttributedOrder.affiliate_id == affiliate.id)
            .where(AttributedOrder.business_month == month)
            .order_by(AttributedOrder.shopify_order_id)
        )
    )
    return source_version(calculation, orders, carried_into(db, affiliate, month))


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
    """One model's month: the figure, what blocks it, and what it carries.

    **The same shape for every month, including the ones before go-live**
    (ADR 0036). Those used to return a sales-only row with no commission and
    no blockers, which also meant no way to approve them - and the whole of
    task #17 is that they are approved like any other month, so a model's
    March reads like her August.

    They differ in one thing, and it is not on this row: what they are worth
    is never *owed*. `balance_for` says so, structurally, and no amount of
    approving changes it.
    """
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
        # 05B. **Something behind an agreed month has moved since it was
        # agreed** - an order refused on delivery, a target recorded, a rate
        # corrected.
        #
        # Reported and nothing else. The agreed figure does not follow it and
        # the payment instruction does not quietly change: money owed under an
        # agreement is owed until somebody decides otherwise, and a total that
        # drifts under the word "agreed" is the failure §11.1 is about.
        #
        # What to *do* about it is a correction, which is 05C's subject. This
        # is the flag that stops it being invisible until then - the old
        # answer was that nobody found out at all.
        "source_changed_since_approval": (
            bool(snapshot)
            and snapshot.payload_json.get("source_version") is not None
            and snapshot.payload_json.get("source_version")
            != _source_version_for(db, affiliate, month, calculation)
        ),
        # ADR 0036. Approvable, and never payable. The screen needs both
        # facts: it offers approval, and it must not offer to send money.
        "settled_outside": is_historical(month),
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
        # ADR 0036. Approvable like any other month, and never payable. The
        # screen says so once, at the top, rather than on twenty-one rows.
        "settled_outside": is_historical(month),
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
    # 05B. **Absence is not agreement.** A commit that carries no record of
    # what was on the screen is a commit from a caller that has not been taught
    # to check, and this route turns a working number into a debt. Refused
    # whole rather than per model: a request shaped this way is a client that
    # needs fixing, not a month that needs reloading.
    if not body.preview and body.source_versions is None:
        raise HTTPException(
            400,
            "Agreeing a month needs the figures the preview handed you. "
            "Reload the month and try again.",
        )
    results = []

    for affiliate_id in body.affiliate_ids:
        affiliate = _affiliate_or_404(db, affiliate_id)
        blockers, calculation = blockers_for(db, affiliate, month)
        seen = _source_version_for(db, affiliate, month, calculation)

        outcome = {
            "affiliate_id": affiliate.id,
            "name": affiliate.name,
            "obligation_piastres": calculation.payout_piastres,
            "obligation": format_egp(calculation.payout_piastres),
            "blockers": blockers,
            "approved": False,
            "version": None,
            # Handed out with the preview and handed back on the commit.
            "source_version": seen,
            "stale": False,
        }

        if not blockers and not body.preview:
            expected = (body.source_versions or {}).get(affiliate.id)
            try:
                snapshot = approve_month(
                    db,
                    affiliate,
                    month,
                    actor_id=actor.id,
                    actor_email=actor.email,
                    expected_source_version=expected,
                )
            except SourceMoved as moved:
                # **Refused for this model, and the rest of the run stands.**
                # Payroll is agreed for twenty people in one act; one model's
                # month moving is not a reason to refuse the other nineteen,
                # and re-running the whole batch to pick them up is how
                # somebody ends up approving in a hurry.
                outcome["stale"] = True
                outcome["blockers"] = [*blockers, SOURCE_MOVED]
                outcome["note"] = str(moved)
                results.append(outcome)
                continue
            outcome["approved"] = True
            outcome["version"] = snapshot.version
            outcome["obligation_piastres"] = snapshot.approved_obligation_piastres
            outcome["obligation"] = format_egp(snapshot.approved_obligation_piastres)
            outcome["source_version"] = snapshot.payload_json.get("source_version")

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
    _actor: UserAccount = Depends(require_permission(Permission.PAYROLL_REOPEN)),
    _db: Session = Depends(get_session),
) -> dict:
    """**Retired in 05B.** An agreed month is not returned to draft any more.

    ## Why it is gone

    Reopening was the platform's only way to change an agreed figure, and it
    worked by *unmaking the agreement*: the month went back to draft, the
    orders it had settled were released, and the next approval wrote a new
    version over the top. Everything about that is recoverable except the one
    thing that matters - **money that had already moved against the old
    figure**. The ledger kept the payment; the month it was made against no
    longer existed in the same form; and `reconciliation_for` was written to
    help a person work out afterwards what had happened to somebody's pay.

    §11.5's own name for the dangerous state says it: *the dangerous state is
    not reopening, it is forgetting*. A month left reopened and never agreed
    again is a model with no figure at all, and the platform needed a
    diagnostic to find those.

    An agreed month is now what its name says. What changes after it is a
    **correction** - an append-only event that records what moved and what is
    owed because of it, leaving the original agreement standing. That is 05C's
    subject, and this route is retired ahead of it so nothing new can be
    reopened in the meantime.

    ## Why the route is still here

    A 404 says *this address is wrong*. A retired capability should say what
    replaced it, to whoever is still calling it - an old tab, a bookmark, a
    script. The permission and its audit history are untouched, and every
    reader of past reopens still works.

    **Nothing about a month that was already reopened changes.** Those months
    are still visible, still diagnosed by `/{month}/reopened`, and still
    agreed again through the ordinary approval.
    """
    _month_or_400(month)
    raise HTTPException(
        409,
        "Agreed months are no longer reopened. The agreement stands and what "
        "changed is recorded against it as a correction. Nothing has been "
        "reopened.",
    )


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


@router.get("/{month}/summary")
def month_summary_view(
    month: str,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """The owner's whole month in one answer. A01, Phase 07B.

    **The breakdown is computed here, never in the browser.** Three components
    assembled from a payload would be a second implementation of what a month
    is worth, and it would disagree with the payroll screen the first time
    somebody rounded differently — on the screen whose job is to say how much
    money to find.
    """
    from app.services.overview import month_summary

    month = _month_or_400(month)
    found = month_summary(db, month)

    return {
        "month": found.month,
        "active_models": found.active_models,
        "sales_piastres": found.sales_piastres,
        "sales": format_egp(found.sales_piastres),
        "ready": found.ready,
        "blocked": found.blocked,
        # Every part, and the total they add to. Given together so a screen
        # never has to sum them and cannot report a different total.
        "expected": {
            "payout_piastres": found.breakdown.payout_piastres,
            "payout": format_egp(found.breakdown.payout_piastres),
            "commission_piastres": found.breakdown.commission_piastres,
            "commission": format_egp(found.breakdown.commission_piastres),
            "fixed_piastres": found.breakdown.fixed_piastres,
            "fixed": format_egp(found.breakdown.fixed_piastres),
            "guarantee_top_up_piastres": found.breakdown.guarantee_top_up_piastres,
            "guarantee_top_up": format_egp(
                found.breakdown.guarantee_top_up_piastres
            ),
        },
        # A01's content progress needing review, by why. Two of the three are
        # HBA's own work rather than a verdict on anybody (D08).
        "selling_models": found.selling_models,
        "needs_review": found.needs_review,
        # The same question answered by name rather than by count, so the
        # panel can be acted on without opening Targets to find out who.
        "content": found.content,
        "top": [
            {**row, "sales": format_egp(row["sales_piastres"])}
            for row in found.top
        ],
        # January to this month, one figure each, for the chart the approved
        # Home draws under everything else. Formatted here like every other
        # figure on this payload, so no browser ever divides by a hundred.
        "year": [
            {**row, "sales": format_egp(row["sales_piastres"])}
            for row in found.year
        ],
    }
