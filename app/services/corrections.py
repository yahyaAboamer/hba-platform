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
from app.services.commission.calculate import calculate_month
from app.services.payroll import (
    carried_into,
    get_month,
    is_historical,
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


@dataclass(frozen=True)
class Correction:
    """One agreed month whose evidence has moved since.

    `recoverable_piastres` is what HBA could take back, and it is **capped at
    what was actually paid**: a month agreed at E£2,000 and paid E£500 cannot
    give back E£2,000 however far the calculation has fallen. Recovering money
    that never moved would invent a debt.
    """

    affiliate_id: int
    month: str
    outcome: str
    agreed_piastres: int
    now_piastres: int
    difference_piastres: int
    paid_piastres: int
    recoverable_piastres: int
    snapshot_id: int
    snapshot_version: int
    #: `True` once somebody has carried or absorbed it. A resolved correction
    #: stays visible - the difference is still real - and stops being offered.
    resolved: bool
    resolution: str | None


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
    now = calculate_month(db, affiliate, month)
    if source_version(now, orders, carried_into(db, affiliate, month)) == frozen:
        return None

    agreed = snapshot.approved_obligation_piastres
    difference = now.payout_piastres - agreed
    outcome = (
        UNDERPAID if difference > 0 else OVERPAID if difference < 0 else NOTHING_TO_CORRECT
    )

    paid = allocated_to(db, snapshot)
    # Capped at what actually moved. A month agreed at E£2,000 and paid E£500
    # cannot give back E£2,000 however far the calculation has fallen -
    # recovering money that never left would invent a debt.
    recoverable = min(-difference, paid) if difference < 0 else 0

    resolution = _resolution_for(db, affiliate, month, snapshot.version)

    return Correction(
        affiliate_id=affiliate.id,
        month=month,
        outcome=outcome,
        agreed_piastres=agreed,
        now_piastres=now.payout_piastres,
        difference_piastres=difference,
        paid_piastres=paid,
        recoverable_piastres=recoverable,
        snapshot_id=snapshot.id,
        snapshot_version=snapshot.version,
        resolved=resolution is not None,
        resolution=resolution,
    )


def _resolution_for(
    db: Session, affiliate: AffiliateProfile, month: str, version: int
) -> str | None:
    """Whether somebody has already carried or absorbed this month's difference.

    **Inferred from the adjustment rather than stored on it**, and that is
    sound for one reason worth stating: since 05B retired reopening, a month
    has exactly one snapshot for its whole life. One agreement, therefore at
    most one open correction, therefore an existing credit or write-off out of
    this month *is* this correction's resolution — there is no second one it
    could belong to.

    If a month can ever carry two agreements again, this needs a column and
    this comment is where to start.
    """
    payroll_month = get_month(db, affiliate, month)
    if payroll_month is None:
        return None

    found = db.scalar(
        select(PayrollAdjustment.type)
        .where(PayrollAdjustment.source_payroll_month_id == payroll_month.id)
        .where(
            PayrollAdjustment.type.in_(
                [AdjustmentType.CREDIT, AdjustmentType.WRITEOFF]
            )
        )
        .order_by(PayrollAdjustment.created_at.desc())
        .limit(1)
    )
    return found


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
    """
    from app.services.portal import months_for

    found = []
    for month in months_for(db, affiliate):
        correction = correction_for(db, affiliate, month)
        if correction is None or correction.outcome != OVERPAID:
            continue
        if correction.recoverable_piastres <= 0 or correction.resolved:
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
    model on an E£8,000 guarantee, an overpayment to recover, and E£9,000
    earned in October - and answered *the whole E£9,000 if needed*. A month can
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
    """
    from app.services.payments import balance_for

    parse_month(month)
    if is_historical(month):
        # ADR 0036: settled outside the platform, balance zero by
        # construction. There is nothing here to consume.
        return 0

    payroll_month = get_month(db, affiliate, month)
    if payroll_month is None or not payroll_month.is_approved:
        return 0

    return max(balance_for(db, affiliate, month)["balance_piastres"], 0)


def resolve(
    db: Session,
    affiliate: AffiliateProfile,
    month: str,
    *,
    choice: str,
    reason: str,
    destination_month: str | None = None,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> PayrollAdjustment:
    """Carry an overpayment into a later month, or absorb it. §11.5's choice.

    `choice` is `credit` (carry) or `writeoff` (absorb) — the two words the
    ledger already uses, rather than a third vocabulary for the same two acts.

    ## What this adds over calling `adjust` directly

    **The amount is not passed in.** It is the recoverable figure this month
    actually has, computed here from the snapshot and the current calculation.
    A caller supplying its own number could recover more than was ever paid, or
    recover twice, and neither would be visible afterwards — the ledger would
    simply say somebody chose that.

    **It is idempotent.** A month already carried or absorbed is refused rather
    than adjusted again. Asking twice is what happens when a request is retried
    or two people are looking at the same list.

    **A carry is checked against the destination's capacity**, so two
    corrections cannot both spend the same later month.
    """
    from app.services.payments import adjust

    if choice not in (AdjustmentType.CREDIT, AdjustmentType.WRITEOFF):
        raise ValueError(
            "A correction is either carried into a later month ('credit') or "
            "absorbed by HBA ('writeoff')."
        )

    correction = correction_for(db, affiliate, month)
    if correction is None or correction.outcome != OVERPAID:
        raise ValueError(
            f"{affiliate.name}'s {month} has nothing to correct."
        )
    if correction.resolved:
        raise ValueError(
            f"{affiliate.name}'s {month} has already been "
            f"{'carried' if correction.resolution == AdjustmentType.CREDIT else 'absorbed'}."
        )
    if correction.recoverable_piastres <= 0:
        raise ValueError(
            f"Nothing was paid against {affiliate.name}'s {month}, so there is "
            "nothing to recover from it."
        )

    if choice == AdjustmentType.CREDIT:
        if not destination_month:
            raise ValueError("A carried correction needs a month to land in.")
        room = capacity_of(db, affiliate, destination_month)
        if room < correction.recoverable_piastres:
            # Refused rather than part-applied. A partial recovery leaves a
            # remainder that nothing is tracking, and the whole point of this
            # service is that a difference stops being forgotten.
            raise ValueError(
                f"{destination_month} can take {room} piastres and this "
                f"correction is {correction.recoverable_piastres}. Choose a "
                "month with room, or absorb it."
            )

    return adjust(
        db,
        affiliate,
        kind=choice,
        source_month=month,
        amount_piastres=correction.recoverable_piastres,
        reason=reason,
        destination_month=destination_month,
        # The difference this correction found, because the month's balance
        # cannot carry it: a snapshot's obligation no longer drops (05B), so
        # an overpaid month still shows a balance of zero. See `adjust`.
        open_difference_piastres=correction.recoverable_piastres,
        actor_id=actor_id,
        actor_email=actor_email,
    )
