"""Agreeing what a month is worth, and freezing it.

§11. Approving is the moment a figure stops being a calculation and becomes an
obligation. Before it, asking twice may give two answers; after it, the number
does not move.

## Blockers refuse, they do not warn

§11.3, and the distinction underneath it is the whole design: **the block is on
missing information, never on poor performance.** A model who missed their targets
is paid their commission, promptly, and their month closes. A month nobody has
recorded anything for does not, because the platform genuinely does not know.

A warning that can be clicked past is not a control. Every blocker here refuses.

## Approving is what closes a month to editing

`assert_correctable` (compensation, Phase 3) and `assert_recordable` (targets,
Phase 5) have blocked nothing since they were written, and both `docs/limits.md`
entries say Phase 6 must wire them. This is that. Correcting somebody's rate or
their target after payroll would change what a month was worth **after the money
moved**, and the snapshot would silently disagree with the data it came from.

## A month before go-live is approved here too

ADR 0036, superseding 0014. There used to be a blocker, `month_predates_the
_platform`, refusing to approve any month the platform did not pay for. It has
been removed - not relaxed - and the guarantee it gave moved into
`balance_for`, which reports such a month as owing nothing whatever state it
reached.

That is the stronger place for it. A blocker lives in one function, refuses one
verb, and is gone the moment somebody deletes the line. A balance of zero
survives the month being approved, and there is no way to send money against a
month that is not owed any.

## The snapshot holds everything, not references to it

`payload_json` carries the whole calculation. A snapshot storing ids would
recompute the day a code changed hands or a rate was corrected - and a snapshot
that recomputes is not a snapshot. This is guarded by a test that changes the
underlying data and asserts the figure did not move.
"""

import hashlib
import json
from dataclasses import asdict

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.businesstime import business_month, parse_month, utcnow
from app.models.affiliates import AccountKind, AffiliateProfile
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.payroll import CalculationState, PayrollMonth, PayrollSnapshot
from app.services.attribution import AttributionOutcome, resolve_order
from app.services.audit import record_audit
from app.services.policy import active_policy_for
# F02. The policy names live beside the arithmetic that applies them and are
# re-exported here, because a snapshot is where one is recorded: every caller
# asking *which rule agreed this month* asks this module.
from app.services.commission.calculate import (
    COUNTED_STATES,
    DELIVERED_ONLY,
    PENDING_INCLUSIVE,
    MonthCalculation,
    calculate_month,
    counted_states_for,
    not_settled_by_another_month,
)

#: §9.2 and §11.3. An order carrying two registered codes belongs to nobody
#: until a person decides, and approving a month containing one would pay a
#: figure that is knowably incomplete.
ORDERS_ON_HOLD = "orders_held_for_multi_code_review"

#: §8, §17. A house account is a real code used by real customers and is never
#: owed money. Approving one would create an obligation to HBA itself.
HOUSE_ACCOUNT = "house_accounts_are_never_owed"

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


#: 05B. The month moved between the preview and the commit.
#:
#: Not a blocker: a blocker says *this month cannot be approved by anybody
#: yet*, and this says *the thing you looked at is not the thing in front of
#: you now*. Reloading fixes it, and nothing is wrong with the month.
SOURCE_MOVED = "source_changed_since_preview"


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
    if existing is not None and existing.calculation_state == CalculationState.APPROVED:
        blockers.append(ALREADY_APPROVED)

    if held_order_count(db, affiliate, month):
        blockers.append(ORDERS_ON_HOLD)

    # Section 11.2. An unset go-live still refuses everything, and for the
    # original reason: without it nothing here can tell a month the platform
    # is responsible for from one it is not, and every imported month reads as
    # ours to pay.
    #
    # **What is no longer here is the refusal of the months themselves**
    # (ADR 0036). They are approved and frozen like any other month, which is
    # what gives a model a March that looks like her August. The protection
    # moved into `balance_for`, where approving cannot bypass it.
    if not go_live_month():
        blockers.append(NO_GO_LIVE_MONTH)

    return blockers, calculation


def _order_line(order: AttributedOrder) -> dict:
    return {
        "shopify_order_id": order.shopify_order_id,
        "state": order.commission_state,
        "base_piastres": order.commission_base_piastres,
        "delivered_at": order.delivered_at.isoformat()
        if order.delivered_at
        else None,
    }


def _payload(
    calculation: MonthCalculation,
    orders: list[AttributedOrder],
    carried: list[AttributedOrder] | None = None,
    deductions: list[dict] | None = None,
    applied_piastres: int | None = None,
    released: list[dict] | None = None,
) -> dict:
    """The whole calculation, in a form that survives the data changing.

    Every order is written out with what it was worth **at approval**, not a
    reference to a row that may be recalculated later.

    Carried orders are listed separately and keep their own month, because
    "which payroll paid it" and "which month it belongs to" are different
    questions and §11.4 turns on not confusing them.
    """
    body = asdict(calculation)
    # Decimals are written as strings, not floats. A float would round the one
    # value the whole module exists to keep exact, and JSON has no other way
    # to carry it.
    body["exact_unrounded_piastres"] = str(calculation.exact_unrounded_piastres)
    body["commission_piastres"] = str(calculation.commission_piastres)
    body["carried_piastres"] = str(calculation.carried_piastres)
    body["orders"] = [_order_line(order) for order in orders]
    body["carried_from_earlier_months"] = [
        {**_order_line(order), "business_month": order.business_month}
        for order in (carried or [])
    ]
    # F02. Which rule agreed this figure, frozen with the figure itself. A
    # month must be able to say what it counted long after the policy moved
    # on, and every later question about it - was this order paid, is that
    # difference a correction - is answered from this rather than from
    # whatever the calculator does today.
    body["policy"] = PENDING_INCLUSIVE
    # 05B. What this figure was computed from, in one short string. Frozen
    # here so a later question - *has anything moved since we agreed this?* -
    # is one comparison rather than a re-derivation of a month that is closed.
    body["source_version"] = source_version(calculation, orders, carried, deductions)
    # F07 names accepted deduction allocations among what approval freezes, so
    # they are written into the snapshot rather than only hashed into its
    # fingerprint: a statement has to be able to say what was deducted without
    # re-deriving it from a ledger that has moved on.
    body["deductions"] = deductions or []
    # F1, and the reason the two lines below are not one. **What was asked of
    # this month and what it could do about it are different facts**, and the
    # snapshot used to record only the first.
    #
    # A month agreed at nothing with E£2,000 of deduction landing on it froze a
    # deduction list reading E£2,000, because the payload is built before
    # approval works out what can actually be absorbed. Rendered onto a
    # statement that says *E£2,000 was deducted* - which is false twice: that
    # much was requested, none of it was taken, and all of it went back to the
    # month it came from and is still open there.
    #
    # `deductions` stays exactly as it was: the allocation somebody reviewed
    # and agreed, and the thing the fingerprint is over. These say what it came
    # to.
    body["deductions_applied_piastres"] = (
        int(applied_piastres)
        if applied_piastres is not None
        else sum(
            row["amount_piastres"]
            if row["type"] != "release"
            else -row["amount_piastres"]
            for row in (deductions or [])
        )
    )
    body["deductions_released"] = released or []
    body["deductions_released_piastres"] = sum(
        row["amount_piastres"] for row in (released or [])
    )
    return body


def deductions_landing_on(db: Session, affiliate: AffiliateProfile, month: str) -> list[dict]:
    """Corrections accepted against this month, oldest first. R1, F07.

    What the reviewer is agreeing to, beside the figure itself: approval
    freezes *accepted deduction allocations* as well as the earnings, and a
    deduction is the difference between a month that pays E£500 and one that
    pays nothing.

    Each row is identified by the adjustment that created it, so a deduction
    added, changed or released between the preview and the commit shows up as
    a different fingerprint rather than as the same month quietly settling
    for less.
    """
    from app.models.payments import AdjustmentType, PayrollAdjustment

    payroll_month = get_month(db, affiliate, month)
    if payroll_month is None:
        return []

    rows = db.execute(
        select(
            PayrollAdjustment.id,
            PayrollAdjustment.type,
            PayrollAdjustment.amount_piastres,
            PayrollMonth.month,
        )
        .join(PayrollMonth, PayrollMonth.id == PayrollAdjustment.source_payroll_month_id)
        .where(PayrollAdjustment.destination_payroll_month_id == payroll_month.id)
        .where(
            PayrollAdjustment.type.in_(
                [AdjustmentType.CREDIT, AdjustmentType.RELEASE]
            )
        )
        .order_by(PayrollAdjustment.id)
    ).all()
    return [
        {
            "adjustment_id": row_id,
            "type": kind,
            "amount_piastres": int(amount or 0),
            "from_month": from_month,
        }
        for row_id, kind, amount, from_month in rows
    ]


def source_version(
    calculation: MonthCalculation,
    orders: list[AttributedOrder],
    carried: list[AttributedOrder] | None = None,
    deductions: list[dict] | None = None,
) -> str:
    """A short fingerprint of everything this month's figure was computed from.

    §11.3, 05B. Approving is the moment a working number becomes a debt, and
    the operator agrees to **the figure they were shown**. Between the preview
    and the commit a webhook can settle an order, a delivery can fail, a
    target can be recorded or a rate can be corrected — and the old approve
    route recalculated at commit time and froze whatever was true *then*,
    silently. Nobody would ever see the difference: the screen said one number
    and the snapshot said another.

    So the preview hands this out, the commit hands it back, and a mismatch is
    refused rather than reconciled. There is no correct guess about which
    figure somebody meant, exactly as 04A found for the targets grid.

    ## What goes in, and why not simply the payout

    The payout alone is not enough. **Two different months can be worth the
    same money** — an order failing while another delivers for the same amount
    leaves the total untouched and the evidence behind it completely changed,
    and a guarantee turns on the evidence rather than the total. So this covers
    the orders and their states, the arrangement, and the target outcome:
    everything §11.3 lets decide a figure.

    Derived, never stored — the same reasoning as 04A's grid revision. A column
    would need writing on every path that touches an order and would be wrong
    the first time somebody forgot.
    """
    facts = {
        "affiliate_id": calculation.affiliate_id,
        "month": calculation.month,
        "compensation_type": calculation.compensation_type,
        "commission_rate_bp": calculation.commission_rate_bp,
        "fixed_piastres": calculation.fixed_piastres,
        "base_amount_piastres": calculation.base_amount_piastres,
        # A target that is met but unconfirmed is a different month from one
        # that is met and confirmed: only the second releases a guarantee.
        "target_achieved": calculation.target_achieved,
        "target_verified": calculation.target_verified,
        "orders": [_order_line(order) for order in orders],
        "carried": [
            {**_order_line(order), "business_month": order.business_month}
            for order in (carried or [])
        ],
    }
    # R1, F07. A deduction accepted against this month decides what is
    # actually transferred for it, so it is part of what the reviewer agrees.
    # One added, changed or released between the preview and the commit has to
    # move this fingerprint, or the settlement they approve is not the
    # settlement they were shown.
    #
    # **Added only when there is one**, so the fingerprint of a month with no
    # deductions is the same string it has always been. Every snapshot agreed
    # before this existed keeps comparing equal, and the cheap *nothing has
    # moved* answer keeps working for them.
    if deductions:
        facts["deductions"] = deductions
    return content_hash(facts)[:16]


def policy_of(snapshot: PayrollSnapshot) -> str:
    """Which counting rule a snapshot was agreed under. F02.

    Absent means `DELIVERED_ONLY`: every month approved before the transition
    was agreed under the old rule, and none of them carries the flag.
    """
    return (snapshot.payload_json or {}).get("policy") or DELIVERED_ONLY


def counted_in_snapshot(snapshot: PayrollSnapshot, shopify_order_id: str) -> bool:
    """Did this agreed month already pay for this order?

    **The one question the transition turns on.** An order left out of its own
    month because it had not been delivered yet is still owed, and a later
    payroll pays it (§11.4). An order its own month counted is paid, and
    nothing may pay it again - however it is delivered afterwards.

    Answered from the snapshot's frozen order list and the policy recorded
    beside it, never from the order's state today: today's state is exactly
    what changed, and reading it would answer a question about September using
    facts from November.
    """
    counted = counted_states_for(policy_of(snapshot))
    for line in (snapshot.payload_json or {}).get("orders") or []:
        if line.get("shopify_order_id") == shopify_order_id:
            return line.get("state") in counted
    # Not in the snapshot at all. It reached us after the month was agreed, so
    # that month cannot have paid for it.
    return False


def content_hash(payload: dict) -> str:
    """SHA-256 over the payload, with keys sorted.

    Sorted because a hash that changes when a dictionary happens to iterate
    differently answers "did the figures change?" with noise.
    """
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class SourceMoved(ValueError):
    """The month changed between being previewed and being agreed.

    Its own type rather than a message, because the API answers it with a
    different status from an ordinary refusal: a blocker means *fix the month*
    and this means *look again*.
    """


def approve_month(
    db: Session,
    affiliate: AffiliateProfile,
    month: str,
    *,
    actor_id: int | None = None,
    actor_email: str | None = None,
    expected_source_version: str | None = None,
) -> PayrollSnapshot:
    """Agree what this month is worth, and freeze it.

    Refuses on any blocker. §11.3 makes these refusals rather than warnings,
    because a warning that can be clicked past is not a control.
    """
    from app.services.money_gate import hold_money_gate

    parse_month(month)

    # F3. **The lock comes before the reading, not before the writing.**
    #
    # Everything below decides a figure and then freezes it: the blockers, the
    # calculation, the carried orders, the deductions landing on the month and
    # the fingerprint they are checked against. All of it was read outside any
    # lock, and a carry committing in that window was agreed to by a snapshot
    # that had never seen it — the freshness check passed because the figure it
    # compared had been read before the change, which is precisely the check
    # failing to do its job.
    #
    # The gate is taken on the model rather than the month, and
    # `app/services/money_gate.py` says why at length: approval and
    # `corrections.resolve` need the same two month rows in opposite orders,
    # and one lock has no order to get wrong. It re-reads on the way in, so
    # what follows is the world as it is now rather than as this session last
    # loaded it.
    hold_money_gate(db, affiliate)
    payroll_month = open_month(db, affiliate, month)

    blockers, calculation = blockers_for(db, affiliate, month)
    if blockers:
        raise ValueError(
            f"{affiliate.name}'s {month} cannot be approved: "
            + ", ".join(blockers)
        )

    orders = list(
        db.scalars(
            select(AttributedOrder)
            .where(AttributedOrder.affiliate_id == affiliate.id)
            .where(AttributedOrder.business_month == month)
            .order_by(AttributedOrder.shopify_order_id)
        )
    )
    # §11.4. Orders from earlier closed months that this payroll is paying.
    # They are settled by this snapshot below, which is what stops them being
    # offered to next month as well - the calculation would happily pay them
    # again, because nothing about the order says it has been paid except this.
    carried = carried_into(db, affiliate, month)
    # R1, F07. What is already accepted against this month, frozen with the
    # figure and checked for freshness beside it.
    deductions = deductions_landing_on(db, affiliate, month)

    # 05B. Agree the figure that was shown, or agree nothing.
    #
    # Optional, and its absence is **not** treated as agreement by the route
    # above - a caller that sends nothing is one that has not been taught to
    # check. It is optional here because approval is also driven from tests,
    # backfills and the shell, where there is no screen to be stale.
    if expected_source_version is not None:
        current = source_version(calculation, orders, carried, deductions)
        if current != expected_source_version:
            raise SourceMoved(
                f"{affiliate.name}'s {month} changed while you were looking at "
                "it. Reload the month and check the figure before agreeing it."
            )

    # F1. What this month can actually take of what is landing on it, worked
    # out *before* the payload so the snapshot can freeze both the allocation
    # that was reviewed and the amount it came to. The releases themselves are
    # written below, once there is a snapshot to have been agreed at this
    # figure.
    applied_piastres, giving_back = _deduction_outcome(
        db, payroll_month, calculation.payout_piastres
    )

    payload = _payload(
        calculation,
        orders,
        carried,
        deductions,
        applied_piastres=applied_piastres,
        released=giving_back,
    )
    previous = latest_version(db, payroll_month)

    # §16, Phase 10 Batch C. Which plain-language rules this was calculated
    # under - frozen here and never re-resolved, so a policy reworded next
    # year cannot change what this snapshot already told somebody.
    policy = active_policy_for(db, month)

    snapshot = PayrollSnapshot(
        payroll_month_id=payroll_month.id,
        version=previous + 1,
        payload_json=payload,
        content_hash=content_hash(payload),
        approved_obligation_piastres=calculation.payout_piastres,
        exact_unrounded_piastres=str(calculation.exact_unrounded_piastres),
        approved_by=actor_id,
        approved_at=utcnow(),
        policy_version_id=policy.id if policy else None,
    )
    # 05B. **Two people run payroll and both open it at month end.**
    #
    # `ALREADY_APPROVED` is read a few lines above, and between that read and
    # this insert the other person can commit. Then both compute the same next
    # version and the database refuses the second on
    # `payroll_snapshot_version_unique` - which is the constraint doing its
    # job, and which arrived here as an `IntegrityError` that aborted the whole
    # transaction. On a route approving twenty models, one collision took the
    # other nineteen with it.
    #
    # A savepoint keeps the collision local, so it can be answered as *look
    # again* for that model while the rest of the run stands.
    try:
        with db.begin_nested():
            db.add(snapshot)
            db.flush()
    except IntegrityError as clash:
        raise SourceMoved(
            f"{affiliate.name}'s {month} was agreed by somebody else while you "
            "were looking at it. Reload the month before agreeing it again."
        ) from clash

    payroll_month.calculation_state = CalculationState.APPROVED
    payroll_month.active_snapshot_id = snapshot.id
    payroll_month.updated_at = utcnow()

    # §11.4. Which payroll actually paid each order - deferred out of Phase 4
    # until snapshots existed, and what lets a model's dashboard say "paid in
    # your September payment" rather than leaving them to work out the
    # difference.
    #
    # **Every order this figure counted, not only the delivered ones** (F02).
    # A pending order the month paid for is paid, and the link saying so is
    # what stops a later payroll offering it again when the courier confirms
    # it. Leaving it unmarked would make the guarantee depend on nobody ever
    # reading the order's state instead of the snapshot's.
    for order in [*orders, *carried]:
        if order.commission_state in COUNTED_STATES and order.settled_in_snapshot_id is None:
            order.settled_in_snapshot_id = snapshot.id
            order.settled_at = snapshot.approved_at

    _release_deductions_the_month_cannot_take(
        db, affiliate, payroll_month, snapshot, giving_back=giving_back, actor_id=actor_id
    )

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

    # Section 16, and ADR 0030: a reopen sends nothing of its own, so this one
    # email covers the first approval and every re-approval after it. Queued in
    # the same transaction as the snapshot, so an agreed month and the notice
    # about it commit together.
    #
    # **Except for a month before go-live** (ADR 0036). Backfilling the history
    # of twenty-one models means approving eight months each, and this line
    # would send about a hundred and seventy mails announcing that a month
    # closed - months that closed and were paid before the platform existed.
    # Every one of them would read as a new payment on its way.
    #
    # Suppressed rather than made optional: there is no reading of "your month
    # is closed, here is what you earned" that is true about March, and a flag
    # somebody has to remember to set is a flag somebody forgets on the run
    # that matters. The business tells the models about the older months
    # directly, before the portal opens.
    if not is_historical(month):
        from app.services.notifications import month_approved

        month_approved(db, affiliate, snapshot, month)
    return snapshot


def _deduction_outcome(
    db: Session, payroll_month: PayrollMonth, payable: int
) -> tuple[int, list[dict]]:
    """What a month's incoming deductions come to, and what goes back. R1, F1.

    Answers both halves of one question — *this month is worth `payable`, and
    this much is being deducted from it: how much of that can it take?* — so
    that approval can freeze the answer and then act on it, rather than acting
    first and freezing the request.

    Returns the piastres the month absorbs and, per source month, the piastres
    it hands back. Writes nothing.

    ## Netted per source month, which is the fix F1 asked for

    The first version of this walked the individual credit rows and, for each
    one, subtracted the releases recorded against its whole source-and-
    destination *pair*. With one credit those are the same number and it was
    right. With two credits from one source it counted the first release again
    while judging the second, decided the second was already fully released,
    and left half the deduction applied to a month that could not pay it.

    A release carries no link to an individual credit — deliberately, because
    "how much of August's correction is applied to October" is a fact about the
    pair and not about which of two rows somebody clicked first. So the
    arithmetic is done where the fact lives: credits less releases, per source,
    and whatever that nets to is what there is to hand back.
    """
    from app.models.payments import AdjustmentType, PayrollAdjustment

    rows = db.execute(
        select(
            PayrollAdjustment.source_payroll_month_id,
            PayrollAdjustment.type,
            func.sum(PayrollAdjustment.amount_piastres),
            func.max(PayrollAdjustment.id),
        )
        .where(PayrollAdjustment.destination_payroll_month_id == payroll_month.id)
        .where(
            PayrollAdjustment.type.in_(
                [AdjustmentType.CREDIT, AdjustmentType.RELEASE]
            )
        )
        .group_by(
            PayrollAdjustment.source_payroll_month_id, PayrollAdjustment.type
        )
    ).all()

    applied: dict[int, int] = {}
    newest: dict[int, int] = {}
    for source_id, kind, total, last_id in rows:
        sign = -1 if kind == AdjustmentType.RELEASE else 1
        applied[source_id] = applied.get(source_id, 0) + sign * int(total or 0)
        if kind == AdjustmentType.CREDIT:
            newest[source_id] = max(newest.get(source_id, 0), int(last_id or 0))

    landing = sum(amount for amount in applied.values() if amount > 0)
    excess = landing - payable
    if excess <= 0:
        return landing, []

    # Newest first: the last carry accepted is the one that over-committed the
    # month, so it is the one to unwind. An older credit was accepted when the
    # month had more room and has the better claim to it.
    order = sorted(
        (source_id for source_id, amount in applied.items() if amount > 0),
        key=lambda source_id: newest.get(source_id, 0),
        reverse=True,
    )

    giving_back = []
    for source_id in order:
        if excess <= 0:
            break
        give_back = min(applied[source_id], excess)
        source = db.get(PayrollMonth, source_id)
        giving_back.append(
            {
                "from_month": source.month if source else None,
                "amount_piastres": give_back,
            }
        )
        excess -= give_back

    return landing - sum(row["amount_piastres"] for row in giving_back), giving_back


def _release_deductions_the_month_cannot_take(
    db: Session,
    affiliate: AffiliateProfile,
    payroll_month: PayrollMonth,
    snapshot: PayrollSnapshot,
    *,
    giving_back: list[dict] | None = None,
    actor_id: int | None = None,
) -> int:
    """Hand back the part of a carried correction this month cannot absorb. R1.

    ## Why a carry can be too big by the time the month is agreed

    A correction is carried into a month **before** that month is approved, on
    what it is worth at the time — which is the whole point of accepting it
    then (F07, F12): finding an overpayment in early October and being told to
    come back in November is how one gets forgotten.

    What it is worth can fall. E£200 is carried into October when October is
    earning E£200; an order fails, October is agreed at E£100, and E£200 of
    deduction is now sitting on a month with E£100 in it.

    ## What was wrong with leaving it

    The month's balance simply went to **minus E£100 — "overpaid"** — on a
    month nothing had ever been transferred for. Worse, the source correction
    read as fully resolved, so the E£100 that could not be taken was tracked
    nowhere at all. A request to recover money and an amount a month could
    actually absorb are different facts, and the ledger was recording only the
    first.

    ## What happens instead

    The excess is returned to the correction it came from, as an append-only
    `release` carrying the same source and destination as the credit it
    un-applies. Both ends net it out: the destination's `credited_into` drops
    to what it could take, and the source's correction opens again by exactly
    the remainder, for any later month.

    **Nothing is edited.** The credit stands as the decision somebody made;
    the release stands as what the month could do about it. Returns the
    piastres released, which is zero on almost every approval.
    """
    from app.models.payments import AdjustmentType
    from app.services.payments import adjust

    payable = snapshot.approved_obligation_piastres
    if giving_back is None:
        _, giving_back = _deduction_outcome(db, payroll_month, payable)

    released = 0
    for row in giving_back:
        give_back = row["amount_piastres"]
        if give_back <= 0:
            continue
        source_month = row["from_month"]
        adjust(
            db,
            affiliate,
            kind=AdjustmentType.RELEASE,
            source_month=source_month,
            destination_month=payroll_month.month,
            amount_piastres=give_back,
            reason=(
                f"{payroll_month.month} was agreed at "
                f"{payable} piastres, which cannot take the whole deduction "
                f"carried from {source_month}. This much returns to "
                f"{source_month} and can be carried into a later month."
            ),
            open_difference_piastres=give_back,
            actor_id=actor_id,
        )
        released += give_back

    return released


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


# -- Months before go-live (Section 11.2, ADR 0036) ----------------------------

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


# -- Carry-forward (Section 11.4) ---------------------------------------------


def carried_into(
    db: Session, affiliate: AffiliateProfile, month: str
) -> list[AttributedOrder]:
    """Orders from earlier months that this draft month will pay.

    Section 11.4, and **the common path rather than an edge case**: Egyptian
    cash-on-delivery routinely straddles month end, so an order placed on
    29 August may still be travelling when payroll runs on 5 September.

    An order qualifies when it was placed **before** this month, is earned, is
    not settled by a *different* month's payroll, and its own month is already
    approved - that last condition is what makes it *carried* rather than
    simply late. An unapproved earlier month will pay its own orders when it is
    approved.

    "A different month" rather than "any payroll", so that an approved month
    still reports what it carried. Excluding everything settled would make a
    month's own figure fall the moment it was agreed.

    **Its business_month never changes.** August sales means orders placed in
    August, frozen by trigger since Phase 4. Carry-forward is about which
    payroll pays an order, never about which month it belongs to - and
    conflating the two is what would make a model's own arithmetic disagree
    with their payment.

    ## Since F02 this is a backlog, not a mechanism

    The new policy counts a pending order in its own month, so no month
    approved under it can leave one behind: there is nothing for a later
    payroll to carry. What remains are the orders **delivered-only approvals
    left out** — real sales, agreed under the old rule, still owed — and this
    keeps paying exactly those.

    That is what makes the transition reconcilable rather than a write-off of
    other people's money. The set is finite, it is identified from each
    snapshot's own frozen evidence (`counted_in_snapshot`), and it can only
    shrink. Nothing is added to it again.
    """
    parse_month(month)
    approved = {
        row.month: row.active_snapshot
        for row in db.scalars(
            select(PayrollMonth)
            .where(PayrollMonth.affiliate_id == affiliate.id)
            .where(PayrollMonth.calculation_state == CalculationState.APPROVED)
        )
        if row.active_snapshot is not None
    }
    if not approved:
        return []

    rows = db.scalars(
        select(AttributedOrder)
        .where(AttributedOrder.affiliate_id == affiliate.id)
        .where(AttributedOrder.business_month < month)
        .where(not_settled_by_another_month(affiliate.id, month))
        .order_by(AttributedOrder.business_month, AttributedOrder.shopify_order_id)
    )
    return [
        row
        for row in rows
        if row.counts_toward_payout
        and row.business_month in approved
        # **Only what its own month did not pay for.** Under the old rule that
        # is every order still travelling at approval; under the new one it is
        # nothing, because they were all counted where they belong.
        and not counted_in_snapshot(approved[row.business_month], row.shopify_order_id)
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

    **Unreachable from the interface since 05B**, and deliberately still here.

    Nothing an operator can press calls this: `POST /api/payroll/{month}/reopen`
    refuses, because unmaking an agreement is not how an agreed figure changes
    any more - a correction is recorded against it instead (05C). What this
    still does is *construct* the state, which the tests covering reopened
    history need and which a future repair of an old month may need. Its own
    audit entry has always said who and why.

    **If you are reaching for this from a shell to fix a real month, stop.**
    The month you would be unmaking may have been paid against, and the reason
    the route is gone is that the ledger keeps the payment while the figure it
    was made against disappears.

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
