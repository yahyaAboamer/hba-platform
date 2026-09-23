"""What a month is worth *now*, against what was agreed, and who owes whom.

05C, and the piece that replaces reopening. §11.5 asked what happens when an
agreed month turns out to be wrong; 05B answered half of it by refusing to
unmake the agreement, and this answers the other half — **the agreement stands
and the difference is recorded against it.**

## Why an agreed month can be wrong at all

An order can fail on delivery weeks after the month closed. Shopify tells us,
the calculation moves, and the snapshot does not — deliberately, because money
owed under an agreement is owed until somebody decides otherwise (§11.1). What
was missing was any way to *act* on the difference without destroying the
agreement, and reopening was that way for as long as it existed.

## Nothing here decides anything

The platform reports; a person chooses. §11.5 is explicit that an overpayment
is a credit or a write-off and that which one is a business judgement about a
person HBA knows. This computes the figure and the choice stays with them —
the same division `reconciliation_for` drew for reopens, kept.

## Derived, not stored, until it is accepted

An open correction is a comparison between the frozen snapshot and a fresh
calculation, computed on demand. Nothing is written while nobody has decided,
which is what makes it idempotent: asking twice cannot create two of them, and
a failure that reverses before anybody acts simply stops being reported.

**Once accepted it is frozen**, as an append-only `payroll_adjustment` — and
from that moment the correction is the adjustment rather than this comparison.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import parse_month
from app.models.affiliates import AffiliateProfile
from app.models.attributed_orders import AttributedOrder
from app.models.payments import AdjustmentType, PayrollAdjustment
from app.models.payroll import PayrollMonth
from app.services.commission.calculate import calculate_month
from app.services.payroll import (
    carried_into,
    deductions_landing_on,
    get_month,
    is_historical,
    policy_of,
    source_version,
)

#: A month is only worth correcting if the difference is real money. Zero is
#: not a correction, and neither is a change that moves the evidence without
#: moving the figure - an order failing while another delivers for the same
#: amount is a different month and the same payable.
NOTHING_TO_CORRECT = "nothing_to_correct"

#: They were paid more than the month now comes to. §11.5's case.
OVERPAID = "overpaid"

#: The month is now worth more than was agreed. **Not a correction to recover**
#: - it is money HBA owes, and it is settled by agreeing the higher figure
#: rather than by an adjustment against her.
UNDERPAID = "underpaid"


#: F09/A05. The difference is real and none of it can be recovered, because
#: nothing has been recorded as transferred for this month. **Not the same as
#: resolved** - somebody still has to look at it.
NO_TRANSFER_RECORDED = "no_transfer_recorded"

#: Some of it moved and all of that has been recovered already. What is left
#: is a difference against money **not yet sent**, so there is nothing to take
#: back today - and it becomes recoverable the moment the rest is transferred.
MORE_THAN_WAS_SENT = "difference_exceeds_what_was_sent"


class CorrectionMoved(ValueError):
    """The difference changed between being shown and being acted on.

    Its own type, like `SourceMoved` at approval and for the same reason: a
    correction can now be settled in parts, so a repeated submission is no
    longer harmlessly idempotent. Two people acting on one queue, or one
    browser retrying a request that already succeeded, would otherwise recover
    the same money twice - and the ledger would afterwards record only that
    somebody chose that.
    """


@dataclass(frozen=True)
class Correction:
    """One agreed month whose evidence has moved since.

    ## Four figures, because they answer four different questions

    `shortfall_piastres` is the **cumulative** drop: what the whole month is
    worth now against what was agreed, however many orders failed to produce
    it. One agreed month has one difference, not one per parcel (F11).

    `resolved_piastres` is how much of that somebody has already carried or
    absorbed. `outstanding_piastres` is what is left of it — and it is the
    figure that decides whether this correction is still open, which is what
    lets a second failure appear after the first was settled.

    `recoverable_piastres` is what HBA could actually take back, **capped at
    money that moved and has not already been recovered**: a month agreed at
    EGP 2,000 and paid EGP 500 cannot give back EGP 2,000 however far the
    calculation has fallen. Recovering money that never left would invent a
    debt.

    The last two are deliberately separate. A month whose transfer has not
    been recorded yet has an outstanding difference and nothing recoverable,
    and F09 requires that to be reviewed rather than hidden — which is exactly
    what a queue keyed on recoverable money did with it.
    """

    affiliate_id: int
    month: str
    outcome: str
    agreed_piastres: int
    now_piastres: int
    difference_piastres: int
    shortfall_piastres: int
    resolved_piastres: int
    outstanding_piastres: int
    paid_piastres: int
    recoverable_piastres: int
    snapshot_id: int
    snapshot_version: int
    #: `True` once the whole difference has been carried or absorbed. A
    #: resolved correction stays visible - the difference is still real - and
    #: stops being offered.
    resolved: bool
    #: The last choice recorded against this month, if any. A month can now
    #: carry more than one: a partial carry, then another for the remainder.
    resolution: str | None
    #: Why this still needs somebody to look at it, or `None` when it does
    #: not. Distinct from *what can be recovered*, which may be nothing.
    review_reason: str | None

    @property
    def needs_review(self) -> bool:
        """Somebody has to look at this, whether or not money can move."""
        return self.outstanding_piastres > 0


def correction_for(
    db: Session, affiliate: AffiliateProfile, month: str
) -> Correction | None:
    """What this agreed month is worth now, against what was agreed.

    `None` when there is nothing to say: the month was never agreed, it was
    settled outside the platform (ADR 0036 — its balance is zero by
    construction and there is nothing to recover), or its evidence has not
    moved.

    ## Guarantee-aware, and it falls out of reusing the engine

    A failed order on a guaranteed minimum often costs **nothing**: the
    guarantee is a floor, and losing a sale above the floor moves the
    commission without moving what she is paid. Getting that wrong would
    manufacture a debt against a model who never had one — so the comparison is
    between two runs of `calculate_month`, not between two commission figures.
    §15's rule is applied by the one implementation that knows it.
    """
    from app.services.payments import allocated_to

    parse_month(month)
    if is_historical(month):
        return None

    payroll_month = get_month(db, affiliate, month)
    snapshot = payroll_month.active_snapshot if payroll_month else None
    if payroll_month is None or snapshot is None or not payroll_month.is_approved:
        return None

    frozen = snapshot.payload_json.get("source_version")
    if frozen is None:
        # Agreed before 05B froze a fingerprint. **Unknown is not "moved"** -
        # reporting a correction here would put a figure in front of somebody
        # that nothing can substantiate, on a month that is closed.
        return None

    orders = list(
        db.scalars(
            select(AttributedOrder)
            .where(AttributedOrder.affiliate_id == affiliate.id)
            .where(AttributedOrder.business_month == month)
            .order_by(AttributedOrder.shopify_order_id)
        )
    )
    # **Recalculated under the rule this month was agreed under** (F10).
    #
    # A month approved before the transition was agreed delivered-only, and
    # comparing it with a pending-inclusive recalculation would report the
    # policy change itself as a difference - telling somebody a closed month
    # had become worth more, on evidence that had not moved at all.
    #
    # The question here is only ever *has the evidence moved*, so both sides
    # of the comparison have to be the same rule.
    now = calculate_month(db, affiliate, month, policy=policy_of(snapshot))
    if (
        source_version(
            now,
            orders,
            carried_into(db, affiliate, month),
            deductions_landing_on(db, affiliate, month),
        )
        == frozen
    ):
        return None

    agreed = snapshot.approved_obligation_piastres
    difference = now.payout_piastres - agreed
    outcome = (
        UNDERPAID if difference > 0 else OVERPAID if difference < 0 else NOTHING_TO_CORRECT
    )

    paid = allocated_to(db, snapshot)

    # **The cumulative difference, and what is left of it** (F11).
    #
    # One agreed month has one entitlement, and a second failed order moves
    # that same entitlement further rather than creating a second correction.
    # So the question is never *has anything been resolved here* - it is *how
    # much of the difference has been*, which is what a month with two
    # failures and one earlier credit needs somebody to be able to read.
    shortfall = -difference if difference < 0 else 0
    already, resolution = _resolved_so_far(db, affiliate, month)
    outstanding = max(shortfall - already, 0)

    # Capped at what actually moved, less whatever has already been taken
    # back. A month agreed at EGP 2,000 and paid EGP 500 cannot give back EGP 2,000
    # however far the calculation has fallen - recovering money that never
    # left would invent a debt.
    recoverable = max(min(outstanding, paid - already), 0)

    return Correction(
        affiliate_id=affiliate.id,
        month=month,
        outcome=outcome,
        agreed_piastres=agreed,
        now_piastres=now.payout_piastres,
        difference_piastres=difference,
        shortfall_piastres=shortfall,
        resolved_piastres=already,
        outstanding_piastres=outstanding,
        paid_piastres=paid,
        recoverable_piastres=recoverable,
        snapshot_id=snapshot.id,
        snapshot_version=snapshot.version,
        resolved=shortfall > 0 and outstanding == 0,
        resolution=resolution,
        # F09. *Nothing can be recovered* and *nothing needs deciding* are
        # different facts, and the second one used to be reported for both.
        review_reason=(
            None
            if outstanding <= 0 or recoverable > 0
            else NO_TRANSFER_RECORDED
            if paid <= 0
            else MORE_THAN_WAS_SENT
        ),
    )


def _resolved_so_far(
    db: Session, affiliate: AffiliateProfile, month: str
) -> tuple[int, str | None]:
    """How much of this month's difference is already carried or absorbed.

    **The amount, not merely whether one exists** — and that distinction is
    the whole of F11. Treating any earlier credit as *this is dealt with*
    hid every later failure behind the first one: a month corrected by EGP 300,
    carried, and then hit by a second failed order reported nothing at all,
    because something had been carried once.

    Summed from the adjustments themselves rather than stored, which keeps it
    true across partial recoveries: three carries of EGP 100 against one month
    leave the same trace as one of EGP 300, and neither can be counted twice.

    Returns the total and the most recent choice, which is what the screens
    label a partly-settled month with.
    """
    payroll_month = get_month(db, affiliate, month)
    if payroll_month is None:
        return 0, None

    rows = list(
        db.execute(
            select(PayrollAdjustment.type, PayrollAdjustment.amount_piastres)
            .where(PayrollAdjustment.source_payroll_month_id == payroll_month.id)
            .where(
                PayrollAdjustment.type.in_(
                    [
                        AdjustmentType.CREDIT,
                        AdjustmentType.WRITEOFF,
                        # R4. HBA absorbed a difference on a month nothing was
                        # sent for. No money moved and the decision is real,
                        # so it settles the review exactly as the other two do.
                        AdjustmentType.ACCEPTED,
                        # R1. What a destination could not take, handed back.
                        AdjustmentType.RELEASE,
                    ]
                )
            )
            .order_by(PayrollAdjustment.created_at, PayrollAdjustment.id)
        ).all()
    )
    if not rows:
        return 0, None

    # A release is negative here: it is the part of a carry that never
    # landed, so it stops counting as settled and the correction opens again
    # by exactly that much.
    settled = sum(
        -int(amount or 0) if kind == AdjustmentType.RELEASE else int(amount or 0)
        for kind, amount in rows
    )
    decisions = [kind for kind, _ in rows if kind != AdjustmentType.RELEASE]
    return max(settled, 0), decisions[-1] if decisions else None


def open_corrections(db: Session, affiliate: AffiliateProfile) -> list[Correction]:
    """Every agreed month of hers whose evidence has moved and still costs money.

    Newest first, and **only the ones with something to decide**: a difference
    of zero is not a correction, an underpayment is settled by agreeing the
    higher figure rather than by taking money back, and a resolved one has
    already been carried or absorbed.

    The whole list is here rather than a per-month lookup because the question
    at month end is *what is outstanding across her*, and answering it one
    month at a time is how one gets forgotten — which is the failure §11.5
    named about reopens and which retiring them did not remove.

    ## Keyed on the difference, not on what can be recovered (F09)

    A month whose transfer has not been recorded yet has a real difference and
    nothing recoverable, and this used to drop it: with an approved EGP 2,000,
    a revised EGP 1,800 and no payment recorded, the queue was empty and nobody
    was told anything had changed.

    That was the wrong half to filter on. It is right not to invent
    recoverable debt for money that never moved; it is wrong to let the fact
    that it never moved hide the change. So a correction is listed while any
    of its difference is outstanding, and `recoverable_piastres` says
    separately how much of it is money.
    """
    from app.services.portal import months_for

    found = []
    for month in months_for(db, affiliate):
        correction = correction_for(db, affiliate, month)
        if correction is None or correction.outcome != OVERPAID:
            continue
        if correction.outstanding_piastres <= 0:
            continue
        found.append(correction)
    return found


def outstanding_piastres(
    db: Session,
    affiliate: AffiliateProfile,
    corrections: list[Correction] | None = None,
) -> int:
    """Everything she has been advanced and not yet had recovered, added up.

    The cumulative figure D04 is about. Deciding a single month against a
    single later month would let two corrections each take the same capacity,
    and the second would quietly overdraw a month that had already been spent.

    **Money, not differences.** A month awaiting its transfer has a real
    difference and nothing advanced, and adding it here would report a debt
    against somebody who has not been sent anything. The queue lists it;
    this total does not count it.

    **Pass the list if you already have it.** Each correction runs the whole
    calculation for its month, so recomputing them to add them up doubles the
    work of every screen that shows both - which is every screen that shows
    either.
    """
    rows = open_corrections(db, affiliate) if corrections is None else corrections
    return sum(row.recoverable_piastres for row in rows)


def capacity_of(db: Session, affiliate: AffiliateProfile, month: str) -> int:
    """How much of a later month a deduction may consume.

    **All of it** (D04, 10 September 2026). The owner was asked directly - a
    model on an EGP 8,000 guarantee, an overpayment to recover, and EGP 9,000
    earned in October - and answered *the whole EGP 9,000 if needed*. A month can
    settle at zero while a debt clears, including a month she qualified for her
    guaranteed minimum in.

    The platform recommended the other rule: take only what was earned above
    the floor, and let the remainder wait. It was overruled, and
    `decisions/D04-recovery-comes-before-the-guarantee.md` records both the
    answer and the reasoning it overrode - so that somebody finding a model
    paid nothing in a month she met her targets in finds a decision rather than
    what looks like a bug.

    **What is already carried into this month is out of the figure**, so two
    corrections cannot both spend the same capacity. That falls out of the
    balance rather than being subtracted here: `balance_for` already nets a
    credit landing on a month, because that month needs exactly that much less
    sent (ADR 0035). Subtracting it again here was a double count, and it made
    a month with room look full.

    ## A month that has not been approved yet still has room (F07, F12)

    Capacity used to be zero until the destination was approved, and that had
    the timing exactly backwards: an overpayment is found in early October,
    October is not approved until November, and the only choices left were to
    write off money that should have carried or to remember to come back —
    which §11.5 exists to stop anybody relying on.

    So an unapproved month offers what it is currently worth, less anything
    already landing on it. The allocation is accepted against a draft month
    and reviewed when that month is approved (F07 freezes accepted deduction
    allocations with the figure), which is where it belongs: the person
    agreeing the month sees the deduction as part of what they are agreeing.
    """
    from app.services.payments import balance_for, credited_into

    parse_month(month)
    if is_historical(month):
        # ADR 0036: settled outside the platform, balance zero by
        # construction. There is nothing here to consume.
        return 0

    payroll_month = get_month(db, affiliate, month)
    if payroll_month is not None and payroll_month.is_approved:
        return max(balance_for(db, affiliate, month)["balance_piastres"], 0)

    # Not agreed yet. What it is worth as it stands, less the credits already
    # waiting to land on it, so two corrections cannot both spend a month that
    # nobody has approved. A month that cannot be calculated - no terms, a
    # house account - is worth nothing here, and offers nothing.
    calculation = calculate_month(db, affiliate, month)
    already = credited_into(db, payroll_month) if payroll_month is not None else 0
    return max(calculation.payout_piastres - already, 0)


def _lock_month(db: Session, affiliate: AffiliateProfile, month: str) -> None:
    """Hold this month's row until the transaction ends. R2.

    `SELECT ... FOR UPDATE` on the `payroll_month` row, which every figure in
    this file is ultimately about: its snapshot, its allocations, its
    adjustments. Locking the row rather than a table keeps two models'
    corrections independent, which matters on the one screen that resolves
    several at month end.

    Silent when the month has no row yet. A month nobody has opened has no
    correction and no capacity, and both callers below create it first where
    they need one.
    """
    db.execute(
        select(PayrollMonth.id)
        .where(PayrollMonth.affiliate_id == affiliate.id)
        .where(PayrollMonth.month == month)
        .with_for_update()
    ).first()


def resolve(
    db: Session,
    affiliate: AffiliateProfile,
    month: str,
    *,
    choice: str,
    reason: str,
    destination_month: str | None = None,
    expected_outstanding_piastres: int | None = None,
    operation_key: str | None = None,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> PayrollAdjustment:
    """Carry an overpayment into a later month, or absorb it. §11.5's choice.

    `choice` is `credit` (carry) or `writeoff` (absorb) — the two words the
    ledger already uses, rather than a third vocabulary for the same two acts.

    ## The decision is taken under a lock, not merely checked before one (R2)

    Reading the outstanding amount, asking the destination what it has room
    for and writing the adjustment are three steps, and between them another
    session can do all three itself. Both would read the same figure, both
    would pass every check, and the money would be recovered twice — a race no
    sequential retry test can reach.

    So the source month's row is locked before the correction is computed, and
    the destination's before its capacity is read. Two resolutions of one
    correction queue; two corrections aiming at one destination queue on the
    destination. The order is always source then destination, which is why
    they cannot deadlock against each other.

    **The lock is not the only guard.** `operation_key` gives one decision one
    identity, so a request that arrives twice — the browser's retry after a
    response it never saw — is answered with the row the first one wrote.

    ## What this adds over calling `adjust` directly

    **The amount is not passed in.** It is the recoverable figure this month
    actually has, computed here from the snapshot and the current calculation.
    A caller supplying its own number could recover more than was ever paid, or
    recover twice, and neither would be visible afterwards — the ledger would
    simply say somebody chose that.

    **A carry takes what the destination has room for, and the rest waits**
    (F12). A deduction of EGP 200 against a month worth EGP 100 applies EGP 100,
    sends nothing, and leaves EGP 100 outstanding against the source month —
    which the next month can take, this year or any later one. It used to be
    refused outright, on the reasoning that a partial recovery leaves a
    remainder nothing is tracking; the remainder is tracked now, by comparing
    the month's whole difference with everything already carried or absorbed,
    so the refusal was costing the platform the case it was built for.

    **Nothing is ever written for zero.** A destination with no room is
    refused rather than recorded as a settlement of nothing, and a month with
    no recorded transfer cannot be recovered from at all (F09): the difference
    is real, but no money has moved to take back, and inventing one would be
    a debt against somebody who has not been sent anything.

    **A repeat is refused, not reapplied.** Pass `expected_outstanding_piastres`
    — what the screen showed — and a request that arrives twice, or second
    after somebody else's, is answered with `CorrectionMoved` instead of
    recovering the same money again.
    """
    from app.services.money_gate import hold_money_gate
    from app.services.payments import _replay_of, adjust
    from app.services.payroll import open_month

    if choice not in (AdjustmentType.CREDIT, AdjustmentType.WRITEOFF):
        raise ValueError(
            "A correction is either carried into a later month ('credit') or "
            "absorbed by HBA ('writeoff')."
        )

    operation_key = (operation_key or "").strip() or None

    def replay() -> PayrollAdjustment | None:
        """The row this key already wrote, refusing a key reused for another.

        Two kinds are looked for, because `resolve` can write either: the
        decision as asked, or the `accepted` that R4 substitutes when there is
        nothing to recover. A retry of an absorb must find its own row rather
        than be told the key belongs to some other decision.
        """
        if not operation_key:
            return None
        for kind in (
            (choice, AdjustmentType.ACCEPTED)
            if choice == AdjustmentType.WRITEOFF
            else (choice,)
        ):
            try:
                found = _replay_of(
                    db,
                    operation_key,
                    affiliate=affiliate,
                    kind=kind,
                    source_month=month,
                    destination_month=(
                        destination_month if kind == AdjustmentType.CREDIT else None
                    ),
                )
            except ValueError:
                continue
            if found is not None:
                return found
        # Nothing matched. Let `_replay_of` raise its own message about the
        # decision this key really belongs to, rather than inventing one.
        return _replay_of(
            db,
            operation_key,
            affiliate=affiliate,
            kind=choice,
            source_month=month,
            destination_month=destination_month,
        )

    # R2. **A replay is answered before anything else is judged.**
    #
    # A request that already succeeded is not stale and is not a conflict: the
    # decision was made once and this is the same decision arriving again,
    # because the browser never saw the answer. Checked here rather than left
    # to the freshness test below, which would call it a conflict and leave
    # the caller unable to tell a lost response from somebody else's edit.
    already = replay()
    if already is not None:
        return already

    # R2. A destination earlier than its source is not a carry forward, and
    # the server says so rather than trusting the screen to have offered only
    # later months.
    if choice == AdjustmentType.CREDIT and destination_month:
        parse_month(destination_month)
        if destination_month <= month:
            raise ValueError(
                f"A correction from {month} cannot land on {destination_month}. "
                "It carries into a later month, never an earlier one."
            )

    # F3. One gate for every writer of this model's money, taken before the
    # reading rather than before the writing, and shared with `approve_month`
    # so a carry and an approval cannot interleave. See `money_gate.py`.
    hold_money_gate(db, affiliate)

    # R2. The month rows too, inside the gate. They are redundant while every
    # writer takes the gate first and they are cheap, so they stay: a future
    # path that forgets the gate still cannot resolve two corrections against
    # one month at once. Source first, always.
    _lock_month(db, affiliate, month)
    if choice == AdjustmentType.CREDIT and destination_month:
        open_month(db, affiliate, destination_month)
        _lock_month(db, affiliate, destination_month)

    # F4. **The key is looked for again, now that the waiting is over.**
    #
    # The check above ran before the gate. Two identical requests in flight at
    # once both find nothing there, both queue, and the one that waits wakes
    # up in a world where its own decision has already been recorded - by its
    # twin. Judged on freshness it is a conflict, and the caller is told to
    # reload a correction that its own retry settled. Asked again here, it is
    # what it actually is: the same decision, already made, and the row is
    # handed back.
    already = replay()
    if already is not None:
        return already

    correction = correction_for(db, affiliate, month)
    if correction is None or correction.outcome != OVERPAID:
        raise ValueError(
            f"{affiliate.name}'s {month} has nothing to correct."
        )
    # **Freshness before everything else.** A duplicate submission arrives
    # after the first one settled the month, so the ordinary refusal below
    # would answer it *this is already done* - true, and the wrong answer for
    # a browser that never learned the first attempt succeeded. Checked first,
    # a retry is told to look again, which is what it needs to hear.
    if (
        expected_outstanding_piastres is not None
        and expected_outstanding_piastres != correction.outstanding_piastres
    ):
        raise CorrectionMoved(
            f"{affiliate.name}'s {month} now has "
            f"{correction.outstanding_piastres} piastres outstanding, not "
            f"{expected_outstanding_piastres}. Reload the correction before "
            "acting on it."
        )
    if correction.outstanding_piastres <= 0:
        raise ValueError(
            f"{affiliate.name}'s {month} has already been "
            f"{'carried' if correction.resolution == AdjustmentType.CREDIT else 'absorbed'}."
        )
    # **R4, widened by F2. Absorbing is always recorded as `accepted`.**
    #
    # R4 introduced this type for the one case it had noticed: a month with no
    # transfer recorded, where there is a real difference and nothing to take
    # back. Absorbing was a real answer nobody could give, because the only
    # word for it was *write-off* — and a write-off reduces what a month still
    # owes, which would have paid her less than was agreed.
    #
    # F2 found that the same sentence is true whenever anything is still owed,
    # which is most months: agreed EGP 2,000, sent EGP 1,000, EGP 200 absorbed, and
    # the write-off took the EGP 200 out of the EGP 1,000 still to send. HBA
    # "taking the loss" came out of her money.
    #
    # The two acts were sharing one row type and therefore one arithmetic.
    # They are separated here rather than by redefining what a write-off
    # means: a write-off recorded against a balance still forgives it, exactly
    # as §11.5 always said, and remains the way to say *the remainder is not
    # worth chasing*. Absorbing a correction is a different sentence — *the
    # agreed figure stands and HBA takes the difference* — and now has its own
    # row to say it in.
    if choice == AdjustmentType.WRITEOFF:
        return adjust(
            db,
            affiliate,
            kind=AdjustmentType.ACCEPTED,
            source_month=month,
            amount_piastres=correction.outstanding_piastres,
            reason=reason,
            # The difference it closes is the review, not the balance.
            open_difference_piastres=correction.outstanding_piastres,
            operation_key=operation_key,
            actor_id=actor_id,
            actor_email=actor_email,
        )

    if correction.recoverable_piastres <= 0:
        raise ValueError(
            f"No transfer is recorded against {affiliate.name}'s {month}, so "
            "there is nothing to carry into another month. Record the transfer "
            "that was made, or absorb the difference and pay the agreed figure "
            "in full."
        )

    applied = correction.recoverable_piastres

    if choice == AdjustmentType.CREDIT:
        if not destination_month:
            raise ValueError("A carried correction needs a month to land in.")
        room = capacity_of(db, affiliate, destination_month)
        # F12. As much as this month can take; the remainder stays against the
        # source month and is offered again next time.
        applied = min(applied, room)
        if applied <= 0:
            raise ValueError(
                f"{destination_month} has no room for this correction. Choose "
                "a month with something payable in it, or absorb it."
            )

    return adjust(
        db,
        affiliate,
        kind=choice,
        source_month=month,
        amount_piastres=applied,
        reason=reason,
        destination_month=destination_month,
        # The difference this correction found, because the month's balance
        # cannot carry it: a snapshot's obligation no longer drops (05B), so
        # an overpaid month still shows a balance of zero. See `adjust`.
        #
        # **What is being recovered now, not the whole difference.** `adjust`
        # caps an adjustment at the open difference it is given, and handing
        # it the full shortfall while applying a part of it would let the cap
        # pass a second, overlapping recovery it exists to refuse.
        open_difference_piastres=applied,
        operation_key=operation_key,
        actor_id=actor_id,
        actor_email=actor_email,
    )
