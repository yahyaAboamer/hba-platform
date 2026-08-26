"""Agreeing what a month is worth, and freezing it.

§11. Approving is the moment a figure stops being a calculation and becomes an
obligation. Before it, asking twice may give two answers; after it, the number
does not move.

## Blockers refuse, they do not warn

§11.3, and the distinction underneath it is the whole design: **the block is on
missing information, never on poor performance.** A model who missed her targets
is paid her commission, promptly, and her month closes. A month nobody has
recorded anything for does not, because the platform genuinely does not know.

A warning that can be clicked past is not a control. Every blocker here refuses.

## Approving is what closes a month to editing

`assert_correctable` (compensation, Phase 3) and `assert_recordable` (targets,
Phase 5) have blocked nothing since they were written, and both `docs/limits.md`
entries say Phase 6 must wire them. This is that. Correcting somebody's rate or
her target after payroll would change what a month was worth **after the money
moved**, and the snapshot would silently disagree with the data it came from.

## The snapshot holds everything, not references to it

`payload_json` carries the whole calculation. A snapshot storing ids would
recompute the day a code changed hands or a rate was corrected - and a snapshot
that recomputes is not a snapshot. This is guarded by a test that changes the
underlying data and asserts the figure did not move.
"""

import hashlib
import json
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import business_month, parse_month, utcnow
from app.models.affiliates import AccountKind, AffiliateProfile
from app.models.attributed_orders import AttributedOrder
from app.models.payroll import CalculationState, PayrollMonth, PayrollSnapshot
from app.services.attribution import AttributionOutcome, resolve_order
from app.services.audit import record_audit
from app.services.commission.calculate import MonthCalculation, calculate_month

#: §9.2 and §11.3. An order carrying two registered codes belongs to nobody
#: until a person decides, and approving a month containing one would pay a
#: figure that is knowably incomplete.
ORDERS_ON_HOLD = "orders_held_for_multi_code_review"

#: §8, §17. A house account is a real code used by real customers and is never
#: owed money. Approving one would create an obligation to HBA itself.
HOUSE_ACCOUNT = "house_accounts_are_never_owed"

#: §11.2. Before go-live, and settled outside the platform.
ALREADY_SETTLED_OUTSIDE = "month_predates_the_platform"

#: Approving twice would create a second obligation for one month.
ALREADY_APPROVED = "month_is_already_approved"


def get_month(
    db: Session, affiliate: AffiliateProfile, month: str
) -> PayrollMonth | None:
    parse_month(month)
    return db.scalar(
        select(PayrollMonth)
        .where(PayrollMonth.affiliate_id == affiliate.id)
        .where(PayrollMonth.month == month)
    )


def open_month(
    db: Session, affiliate: AffiliateProfile, month: str
) -> PayrollMonth:
    """The month row, created on demand if it does not exist.

    ADR 0013: created because somebody asked, not on a schedule. Twenty models
    times twelve months of empty rows is storage that answers no question.
    """
    parse_month(month)
    existing = get_month(db, affiliate, month)
    if existing is not None:
        return existing

    created = PayrollMonth(
        affiliate_id=affiliate.id,
        month=month,
        calculation_state=CalculationState.DRAFT,
    )
    db.add(created)
    db.flush()
    return created


def held_order_count(db: Session, affiliate: AffiliateProfile, month: str) -> int:
    """Orders in this month that two registered codes both claim (§9.2).

    Read from `order_index` rather than `attributed_order`, because a held order
    has **no** attributed row - that is what being held means. Counting the
    attributed ones would report zero and approve a month with a known gap in it.
    """
    from app.models.orders import OrderIndex

    rows = db.scalars(
        select(OrderIndex).where(OrderIndex.business_month == month)
    )
    held = 0
    for order in rows:
        decision = resolve_order(db, order)
        if decision.outcome == AttributionOutcome.HELD:
            held += 1
    return held


def blockers_for(
    db: Session, affiliate: AffiliateProfile, month: str
) -> tuple[list[str], MonthCalculation]:
    """Everything standing between this month and being approved.

    Returns the blockers **and** the calculation, because the caller almost
    always needs both and computing a month twice is the kind of waste that
    turns a bulk preview over twenty models into forty round trips.
    """
    calculation = calculate_month(db, affiliate, month)
    blockers = list(calculation.blockers)

    if affiliate.account_kind == AccountKind.HOUSE:
        blockers.append(HOUSE_ACCOUNT)

    existing = get_month(db, affiliate, month)
    if existing is not None:
        if existing.calculation_state == CalculationState.APPROVED:
            blockers.append(ALREADY_APPROVED)
        elif existing.calculation_state == CalculationState.HISTORICAL:
            blockers.append(ALREADY_SETTLED_OUTSIDE)

    if held_order_count(db, affiliate, month):
        blockers.append(ORDERS_ON_HOLD)

    # Section 11.2. An unset go-live would silently make eight months of
    # imported orders approvable - money already settled outside the platform,
    # ready to be paid a second time.
    if not go_live_month():
        blockers.append(NO_GO_LIVE_MONTH)
    elif is_historical(month):
        blockers.append(ALREADY_SETTLED_OUTSIDE)

    return blockers, calculation


def _payload(calculation: MonthCalculation, orders: list[AttributedOrder]) -> dict:
    """The whole calculation, in a form that survives the data changing.

    Every order is written out with what it was worth **at approval**, not a
    reference to a row that may be recalculated later.
    """
    body = asdict(calculation)
    body["exact_unrounded_piastres"] = str(calculation.exact_unrounded_piastres)
    body["commission_piastres"] = str(calculation.commission_piastres)
    body["orders"] = [
        {
            "shopify_order_id": order.shopify_order_id,
            "state": order.commission_state,
            "base_piastres": order.commission_base_piastres,
            "delivered_at": order.delivered_at.isoformat()
            if order.delivered_at
            else None,
        }
        for order in orders
    ]
    return body


def content_hash(payload: dict) -> str:
    """SHA-256 over the payload, with keys sorted.

    Sorted because a hash that changes when a dictionary happens to iterate
    differently answers "did the figures change?" with noise.
    """
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def approve_month(
    db: Session,
    affiliate: AffiliateProfile,
    month: str,
    *,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> PayrollSnapshot:
    """Agree what this month is worth, and freeze it.

    Refuses on any blocker. §11.3 makes these refusals rather than warnings,
    because a warning that can be clicked past is not a control.
    """
    parse_month(month)
    blockers, calculation = blockers_for(db, affiliate, month)
    if blockers:
        raise ValueError(
            f"{affiliate.name}'s {month} cannot be approved: "
            + ", ".join(blockers)
        )

    payroll_month = open_month(db, affiliate, month)
    orders = list(
        db.scalars(
            select(AttributedOrder)
            .where(AttributedOrder.affiliate_id == affiliate.id)
            .where(AttributedOrder.business_month == month)
            .order_by(AttributedOrder.shopify_order_id)
        )
    )

    payload = _payload(calculation, orders)
    previous = latest_version(db, payroll_month)

    snapshot = PayrollSnapshot(
        payroll_month_id=payroll_month.id,
        version=previous + 1,
        payload_json=payload,
        content_hash=content_hash(payload),
        approved_obligation_piastres=calculation.payout_piastres,
        exact_unrounded_piastres=str(calculation.exact_unrounded_piastres),
        approved_by=actor_id,
        approved_at=utcnow(),
    )
    db.add(snapshot)
    db.flush()

    payroll_month.calculation_state = CalculationState.APPROVED
    payroll_month.active_snapshot_id = snapshot.id
    payroll_month.updated_at = utcnow()

    # §11.4. Which payroll actually paid each order - deferred out of Phase 4
    # until snapshots existed, and what lets a model's dashboard say "paid in
    # your September payment" rather than leaving her to work out the
    # difference.
    for order in orders:
        if order.counts_toward_payout and order.settled_in_snapshot_id is None:
            order.settled_in_snapshot_id = snapshot.id
            order.settled_at = snapshot.approved_at

    db.flush()
    record_audit(
        db,
        action="payroll.approved",
        subject=f"affiliate:{affiliate.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        after={
            "month": month,
            "version": snapshot.version,
            "obligation_piastres": snapshot.approved_obligation_piastres,
            "exact_unrounded_piastres": snapshot.exact_unrounded_piastres,
            "orders": len(orders),
        },
    )
    return snapshot


def latest_version(db: Session, payroll_month: PayrollMonth) -> int:
    """The highest version so far, or 0. Versions are never reused."""
    return (
        db.scalar(
            select(PayrollSnapshot.version)
            .where(PayrollSnapshot.payroll_month_id == payroll_month.id)
            .order_by(PayrollSnapshot.version.desc())
            .limit(1)
        )
        or 0
    )


def snapshots_for(
    db: Session, payroll_month: PayrollMonth
) -> list[PayrollSnapshot]:
    """Every version of this month, oldest first."""
    return list(
        db.scalars(
            select(PayrollSnapshot)
            .where(PayrollSnapshot.payroll_month_id == payroll_month.id)
            .order_by(PayrollSnapshot.version)
        )
    )


# -- Historical months (Section 11.2, ADR 0014) --------------------------------

#: Section 11.2. Nobody has said which month the platform starts paying for, so
#: it refuses to pay for any of them.
NO_GO_LIVE_MONTH = "go_live_month_is_not_configured"


def go_live_month() -> str:
    """The first month the platform is responsible for. Empty until chosen."""
    from app.config import settings

    return str(settings.go_live_month or "").strip()


def working_month() -> str:
    """The month a screen should open on.

    Normally this month. Before go-live it is the go-live month instead.

    On 26 August, with the platform starting in September, "this month" holds
    nothing at all: every figure is zero and every list is empty, because the
    platform was not responsible for August. Somebody opening the tool in that
    week is there to get September ready, and showing them an empty August
    reads as "the numbers are broken" rather than "this month is not ours".

    This decides only what a screen **defaults to**. It never decides which
    month an order belongs to - that is the order's own date, taken in Cairo
    (ADR 0005), and nothing here may move it.
    """
    now = business_month(utcnow())
    configured = go_live_month()
    if configured and now < parse_month(configured):
        return parse_month(configured)
    return now


def is_historical(month: str) -> bool:
    """Section 11.2. Before go-live, and settled outside the platform.

    Re-importing from January gives every model months of orders with no
    payroll records. Without this they all read as unfinalised and **owed** -
    money HBA already paid, presented as a debt.
    """
    parse_month(month)
    configured = go_live_month()
    if not configured:
        return False
    return month < parse_month(configured)


def historical_sales(db: Session, affiliate: AffiliateProfile, month: str) -> dict:
    """What a historical month shows: sales, and no commission figure.

    **Decided, and worth restating** (ADR 0014). Computing March's commission
    needs March's rates, which exist only in the old system and in somebody's
    memory. Applying today's rates to last March would be actively misleading,
    and reconstructing them by hand invites errors nobody could later verify.
    """
    rows = list(
        db.scalars(
            select(AttributedOrder)
            .where(AttributedOrder.affiliate_id == affiliate.id)
            .where(AttributedOrder.business_month == month)
        )
    )
    return {
        "affiliate_id": affiliate.id,
        "month": month,
        "calculation_state": CalculationState.HISTORICAL,
        "orders": len(rows),
        "net_sales_piastres": sum(row.commission_base_piastres for row in rows),
        "commission": None,
        "label": "Settled before the platform - commission not calculated",
        "is_payable": False,
    }


# -- Carry-forward (Section 11.4) ---------------------------------------------


def carried_into(
    db: Session, affiliate: AffiliateProfile, month: str
) -> list[AttributedOrder]:
    """Orders from earlier months that this draft month will pay.

    Section 11.4, and **the common path rather than an edge case**: Egyptian
    cash-on-delivery routinely straddles month end, so an order placed on
    29 August may still be travelling when payroll runs on 5 September.

    An order qualifies when it was placed **before** this month, is earned, has
    not been settled by any payroll, and its own month is already approved -
    that last condition is what makes it *carried* rather than simply late. An
    unapproved earlier month will pay its own orders when it is approved.

    **Its business_month never changes.** August sales means orders placed in
    August, frozen by trigger since Phase 4. Carry-forward is about which
    payroll pays an order, never about which month it belongs to - and
    conflating the two is what would make a model's own arithmetic disagree
    with her payment.
    """
    parse_month(month)
    approved_months = {
        row.month
        for row in db.scalars(
            select(PayrollMonth)
            .where(PayrollMonth.affiliate_id == affiliate.id)
            .where(PayrollMonth.calculation_state == CalculationState.APPROVED)
        )
    }
    if not approved_months:
        return []

    rows = db.scalars(
        select(AttributedOrder)
        .where(AttributedOrder.affiliate_id == affiliate.id)
        .where(AttributedOrder.business_month < month)
        .where(AttributedOrder.settled_in_snapshot_id.is_(None))
        .order_by(AttributedOrder.business_month, AttributedOrder.shopify_order_id)
    )
    return [
        row
        for row in rows
        if row.counts_toward_payout and row.business_month in approved_months
    ]


def carry_forward_summary(
    db: Session, affiliate: AffiliateProfile, month: str
) -> list[dict]:
    """The labelled lines Section 11.4 describes, one per month carried from.

    "Carried forward from August - 2 orders, 840 pounds."
    """
    carried = carried_into(db, affiliate, month)
    by_month: dict[str, dict] = {}
    for order in carried:
        line = by_month.setdefault(
            order.business_month,
            {"from_month": order.business_month, "orders": 0, "piastres": 0},
        )
        line["orders"] += 1
        line["piastres"] += order.commission_base_piastres
    return [by_month[key] for key in sorted(by_month)]


# -- Reopen (Section 11.5) ----------------------------------------------------


def reopen_month(
    db: Session,
    affiliate: AffiliateProfile,
    month: str,
    *,
    reason: str,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> PayrollMonth:
    """Return an approved month to draft.

    **The most dangerous operation in the platform** - it touches a month
    somebody has been paid for. Hence: a written reason, the prior snapshot
    preserved as a version, and payment allocations against it left untouched.
    Money that moved does not un-move because a calculation was revisited.

    Orders settled by the reopened snapshot are **released**, so the
    recalculation can pay them again. Orders paid by a *different* snapshot are
    left alone - that month is settled, and Section 11.4 says they stay there.
    """
    parse_month(month)
    if not str(reason or "").strip():
        raise ValueError("Reopening an approved month requires a written reason")

    payroll_month = get_month(db, affiliate, month)
    if payroll_month is None or not payroll_month.is_approved:
        raise ValueError(f"{affiliate.name}'s {month} is not approved")

    snapshot_id = payroll_month.active_snapshot_id
    released = 0
    if snapshot_id is not None:
        for order in db.scalars(
            select(AttributedOrder).where(
                AttributedOrder.settled_in_snapshot_id == snapshot_id
            )
        ):
            order.settled_in_snapshot_id = None
            order.settled_at = None
            released += 1

    payroll_month.calculation_state = CalculationState.DRAFT
    payroll_month.active_snapshot_id = None
    payroll_month.updated_at = utcnow()
    db.flush()

    record_audit(
        db,
        action="payroll.reopened",
        subject=f"affiliate:{affiliate.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before={"month": month, "snapshot_id": snapshot_id},
        after={"month": month, "orders_released": released},
        reason=reason.strip(),
    )
    return payroll_month


def reconciliation_for(db: Session, affiliate: AffiliateProfile, month: str) -> dict:
    """Section 11.5. What re-approving changed, and what to do about it.

    Three outcomes, and **the platform reports rather than decides**: an
    overpayment is a credit or a write-off, and which one is a business
    judgement about a person HBA knows.
    """
    payroll_month = get_month(db, affiliate, month)
    if payroll_month is None:
        return {"outcome": "no_month"}

    versions = snapshots_for(db, payroll_month)
    if len(versions) < 2:
        return {"outcome": "not_reconcilable", "versions": len(versions)}

    previous, latest = versions[-2], versions[-1]
    difference = (
        latest.approved_obligation_piastres - previous.approved_obligation_piastres
    )
    outcome = "unchanged"
    if difference > 0:
        outcome = "underpaid"
    elif difference < 0:
        outcome = "overpaid"

    return {
        "outcome": outcome,
        "difference_piastres": difference,
        "from_version": previous.version,
        "to_version": latest.version,
        # Section 11.5: the maintainer chooses a credit or a write-off.
        # Deciding here would be the platform spending HBA's money on its own
        # judgement.
        "resolution": None,
    }


def months_left_reopened(db: Session, month: str | None = None) -> list[PayrollMonth]:
    """Section 11.5. Months returned to draft and never re-approved.

    **The dangerous state is not reopening; it is forgetting.** A month sitting
    in draft with payments already made against a superseded snapshot is a
    balance nobody is watching.
    """
    query = (
        select(PayrollMonth)
        .where(PayrollMonth.calculation_state == CalculationState.DRAFT)
        .where(PayrollMonth.active_snapshot_id.is_(None))
    )
    if month is not None:
        query = query.where(PayrollMonth.month == parse_month(month))

    return [
        row
        for row in db.scalars(query)
        if db.scalar(
            select(PayrollSnapshot.id)
            .where(PayrollSnapshot.payroll_month_id == row.id)
            .limit(1)
        )
        is not None
    ]
