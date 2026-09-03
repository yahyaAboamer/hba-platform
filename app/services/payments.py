"""What is still owed, and recording that it was paid.

§11.1, §14. Phase 6 agreed a figure; this is the other half.

    balance_due = approved obligation - allocations - credits and write-offs

**Derived every time, never stored.** The moment settlement becomes a column it
disagrees with the payments it came from - and the disagreement is invisible,
because the column looks authoritative. That single conflated column is what
produced the old dashboard's *"Approved · Partially paid"*.

## A reopened month has no answer, and says so

Reopening leaves the month in `draft` with no active snapshot. Its balance is
**unanswerable**, not zero. Reporting zero would say *"nothing outstanding"*
about a month with real money already paid against a superseded version, which
is the most misleading thing this module could do.

## Recording is never automatic

§14. Everything written here describes something a person did outside the
platform - opened InstaPay, sent money, screenshotted it. The Pay button changes
nothing, and neither does anything in this file until somebody says it happened.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.businesstime import parse_month, utcnow
from app.models.affiliates import AffiliateProfile
from app.models.payments import (
    AdjustmentType,
    PaymentAllocation,
    PaymentTransaction,
    PayrollAdjustment,
)
from app.models.payments import VALID_ADJUSTMENT_TYPES
from app.models.payroll import PayrollMonth, PayrollSnapshot
from app.services.audit import record_audit
from app.services.payments_state import SettlementState
from app.services.payouts import current_destination, mask_destination
from app.services.payroll import get_month, open_month


def allocated_to(db: Session, snapshot: PayrollSnapshot) -> int:
    """Money applied to this **version** of a month.

    Against the snapshot rather than the month, because §11.5 requires payments
    made against a superseded version to remain visible after a reopen.

    ``int()``, and not for tidiness. **Postgres `SUM()` over a bigint returns
    `numeric`**, which psycopg hands back as a `Decimal` - and a `Decimal`
    reaching the API is serialised as a *string*, so every balance would arrive
    as `"180000"` and any client doing arithmetic on it would break. Money is
    integer piastres everywhere (ADR 0002), including on the way out of a sum.
    """
    return int(
        db.scalar(
            select(func.coalesce(func.sum(PaymentAllocation.allocated_piastres), 0))
            .where(PaymentAllocation.payroll_snapshot_id == snapshot.id)
        )
        or 0
    )


def allocated_to_month(db: Session, payroll_month: PayrollMonth) -> int:
    """Money applied to **any version** of this month.

    `allocated_to` answers *what has been paid against this snapshot*, which is
    the right question for a version and the wrong one for a bank account.

    After a reopen the two diverge, and the platform reported the wrong one.
    August was agreed at E£760 and paid in full; more orders arrived; it was
    reopened and agreed again at E£1,060. The payment screen then said **still
    owed E£1,060** - because nothing had been allocated to version 2 - when they
    had already received E£760 and was genuinely owed E£300.

    Paying what that screen said would have sent E£1,820 for a month worth
    E£1,060.

    Both facts still exist and are still separate: a payment stays attached to
    the version it settled (§11.5), and this sums what actually left the bank
    for the month. What is owed is a question about the month.
    """
    snapshots = select(PayrollSnapshot.id).where(
        PayrollSnapshot.payroll_month_id == payroll_month.id
    )
    return int(
        db.scalar(
            select(
                func.coalesce(func.sum(PaymentAllocation.allocated_piastres), 0)
            ).where(PaymentAllocation.payroll_snapshot_id.in_(snapshots))
        )
        or 0
    )


def version_history(db: Session, payroll_month: PayrollMonth) -> list[dict]:
    """Every agreed figure this month has had, and what was paid against each.

    §11.5 keeps superseded versions rather than overwriting them, and until now
    nothing showed them. A single figure with a small "v2" beside it cannot
    answer the only question somebody has when they see one: *is this the whole
    amount, or what is left?*
    """
    from app.services.payroll import snapshots_for

    versions = snapshots_for(db, payroll_month)
    active = payroll_month.active_snapshot_id
    return [
        {
            "version": snapshot.version,
            "obligation_piastres": snapshot.approved_obligation_piastres,
            "paid_piastres": allocated_to(db, snapshot),
            "approved_at": snapshot.approved_at.isoformat()
            if snapshot.approved_at
            else None,
            "is_current": snapshot.id == active,
        }
        for snapshot in versions
    ]


def adjusted_against(db: Session, payroll_month: PayrollMonth) -> int:
    """Credits and write-offs closing this month's difference.

    ADR 0035. Both kinds **close a difference, whichever way it runs**: a
    write-off against an underpaid month discharges the debt, and either kind
    against an overpaid month absorbs the excess. Neither ever opens a larger
    difference than the one it was created to settle.

    A **credit** moves the excess to a later month, where the model already
    holds it and that month therefore needs less sent. A **write-off** goes
    nowhere - HBA absorbs it.
    """
    return int(
        db.scalar(
            select(func.coalesce(func.sum(PayrollAdjustment.amount_piastres), 0))
            .where(PayrollAdjustment.source_payroll_month_id == payroll_month.id)
        )
        or 0
    )


def credited_into(db: Session, payroll_month: PayrollMonth) -> int:
    """Credits landing on this month from an earlier overpayment."""
    return int(
        db.scalar(
            select(func.coalesce(func.sum(PayrollAdjustment.amount_piastres), 0))
            .where(PayrollAdjustment.destination_payroll_month_id == payroll_month.id)
            .where(PayrollAdjustment.type == AdjustmentType.CREDIT)
        )
        or 0
    )


def balance_for(db: Session, affiliate: AffiliateProfile, month: str) -> dict:
    """What is still owed for one month, and how that figure was reached.

    Returns the parts as well as the total. A balance nobody can take apart is a
    balance nobody can argue with, and the first question about any outstanding
    figure is *"what makes it up?"*
    """
    parse_month(month)
    payroll_month = get_month(db, affiliate, month)

    if payroll_month is None:
        return {
            "month": month,
            "state": SettlementState.NOT_APPROVED,
            "obligation_piastres": 0,
            "paid_piastres": 0,
            "adjusted_piastres": 0,
            "credited_piastres": 0,
            "balance_piastres": 0,
        }

    snapshot = payroll_month.active_snapshot
    if snapshot is None:
        # Reopened, or never approved. Either way there is no agreed figure to
        # settle against - and saying zero would say "nothing outstanding"
        # about a month that may have been paid in full against a superseded
        # version.
        return {
            "month": month,
            "state": SettlementState.NOT_APPROVED,
            "obligation_piastres": 0,
            "paid_piastres": 0,
            "adjusted_piastres": 0,
            "credited_piastres": 0,
            "balance_piastres": 0,
            "reopened": bool(
                db.scalar(
                    select(PayrollSnapshot.id)
                    .where(PayrollSnapshot.payroll_month_id == payroll_month.id)
                    .limit(1)
                )
            ),
        }

    obligation = snapshot.approved_obligation_piastres
    # **The month, not the version.** See `allocated_to_month`: after a reopen
    # these differ, and reporting the version's figure as the balance told
    # somebody to send money that had already been sent.
    paid = allocated_to_month(db, payroll_month)
    paid_this_version = allocated_to(db, snapshot)
    adjusted = adjusted_against(db, payroll_month)
    credited = credited_into(db, payroll_month)

    # **A credit landing here is money the model already holds** (§11.5, ADR
    # 0035). It came from an earlier month they were overpaid, so it covers
    # this month exactly as a transfer does - this month needs that much less
    # sent, which is what the reconcile screen promises in words.
    difference = obligation - paid - credited

    # **An adjustment closes a difference; it never opens a larger one.**
    #
    # Which way it closes depends on which way the difference runs, and that
    # is the whole of ADR 0035. Writing off a *debt* reduces what is owed;
    # settling an *excess* reduces the overpayment. Subtracting in both cases
    # - which is what this did - pushes an already-overpaid month further
    # into overpayment, so every press of "settle the difference" doubled it:
    # a real overpayment of E£257 was reported as E£5,074.
    #
    # The clamp is the second guard. Even if an adjustment is larger than the
    # difference it closes - and one was, four times over, before the cap
    # below existed - the balance stops at zero rather than crossing it.
    balance = (
        max(difference - adjusted, 0)
        if difference > 0
        else min(difference + adjusted, 0)
    )

    return {
        "month": month,
        "state": SettlementState.of_balance(balance, paid),
        # Payments allocate to a **snapshot**, not to a month (§11.5): money
        # paid against a superseded version has to stay attached to the version
        # it settled. Anything recording a payment therefore needs this id, so
        # the balance that says what is owed also says what to pay it against.
        "payroll_snapshot_id": snapshot.id,
        "version": snapshot.version,
        "obligation_piastres": obligation,
        "paid_piastres": paid,
        # Kept separate rather than folded in. A payment belongs to the version
        # it settled (§11.5) and that stays true; it is simply not the answer
        # to "how much is still to send".
        "paid_this_version_piastres": paid_this_version,
        "paid_earlier_versions_piastres": paid - paid_this_version,
        "adjusted_piastres": adjusted,
        "credited_piastres": credited,
        "balance_piastres": balance,
        # Every figure this month has had. Nothing showed them, and a lone
        # figure with a small "v2" beside it cannot answer the only question
        # somebody has on seeing one.
        "versions": version_history(db, payroll_month),
    }


def balance_due(db: Session, affiliate: AffiliateProfile, month: str) -> int:
    """Just the number, for pre-filling the amount field (§14)."""
    return balance_for(db, affiliate, month)["balance_piastres"]


def record_payment(
    db: Session,
    affiliate: AffiliateProfile,
    *,
    amount_piastres: int,
    allocations: dict[int, int] | None = None,
    occurred_at: datetime | None = None,
    reference: str | None = None,
    note: str | None = None,
    proof_file_id: str | None = None,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> PaymentTransaction:
    """Record money that has already moved.

    ``allocations`` maps snapshot id to piastres. Leaving it empty is allowed: a
    transfer may arrive before anybody has decided which months it covers, and
    forcing a split at the moment of recording would invent an answer.

    The destination is **frozen and masked** onto the row (§6.4.4). Not a
    reference to `payout_destination`, which is append-only precisely so a past
    payment resolves the destination in force at the time.
    """
    if amount_piastres <= 0:
        raise ValueError("A payment must be for more than nothing")

    # **Nothing is paid while one of this model's months is mid-correction.**
    #
    # Correcting a rate across several months means reopening each of them -
    # reopen May, reopen June, edit, re-approve both. Between the first reopen
    # and the last re-approval the figures disagree with themselves: a
    # reopened month has no active snapshot, so what is owed is unknown, while
    # the payment already made against the superseded one still stands.
    #
    # Paying into that gap is how somebody gets paid twice. `reopen_month`
    # already calls itself the most dangerous operation here, and its real
    # danger is not reopening but *forgetting* - which is what
    # `months_left_reopened` exists to surface. This refuses to let money move
    # until the correction is finished.
    from app.services.payroll import months_left_reopened

    unfinished = sorted(
        row.month
        for row in months_left_reopened(db)
        if row.affiliate_id == affiliate.id
    )
    if unfinished:
        raise ValueError(
            f"{affiliate.name} has "
            + ", ".join(unfinished)
            + " reopened and not yet agreed again. Finish the correction "
            "before recording a payment - until every reopened month is "
            "approved, what is owed is still changing."
        )

    requested = allocations or {}
    if sum(requested.values()) > amount_piastres:
        raise ValueError(
            f"Those allocations come to {sum(requested.values())} piastres, "
            f"which is more than the {amount_piastres} that was sent"
        )

    transaction = PaymentTransaction(
        affiliate_id=affiliate.id,
        amount_piastres=int(amount_piastres),
        occurred_at=occurred_at or utcnow(),
        destination_snapshot_json=mask_destination(
            current_destination(db, affiliate)
        ),
        reference=(reference or "").strip() or None,
        note=(note or "").strip() or None,
        proof_file_id=proof_file_id,
        created_by=actor_id,
    )
    db.add(transaction)
    db.flush()

    for snapshot_id, piastres in requested.items():
        if piastres <= 0:
            raise ValueError("An allocation must be for more than nothing")
        db.add(
            PaymentAllocation(
                payment_transaction_id=transaction.id,
                payroll_snapshot_id=snapshot_id,
                allocated_piastres=int(piastres),
            )
        )
    db.flush()

    record_audit(
        db,
        action="payment.recorded",
        subject=f"affiliate:{affiliate.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        after={
            "amount_piastres": transaction.amount_piastres,
            "allocations": {str(k): v for k, v in requested.items()},
            "reference": transaction.reference,
            "has_proof": proof_file_id is not None,
            # Already masked on the row; masking again here is belt and braces
            # against somebody later passing the raw destination in.
            "destination": transaction.destination_snapshot_json,
        },
        reason=transaction.note,
    )

    # Section 14. The receipt itself stays on their payments screen rather than
    # travelling as an attachment - mail is the one channel that leaves the
    # building, and ADR 0017 accepted exposure to *them*, not to whatever
    # forwards an inbox.
    from app.services.notifications import payment_recorded

    payment_recorded(db, affiliate, transaction)
    return transaction


def allocate(
    db: Session,
    transaction: PaymentTransaction,
    snapshot: PayrollSnapshot,
    piastres: int,
    *,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> PaymentAllocation:
    """Apply part of an existing transfer to an agreed figure.

    The database refuses an allocation that would take the total past the
    transfer, because *"we allocated E£12,000 of a E£10,000 transfer"* has to be
    impossible rather than caught in review.
    """
    if piastres <= 0:
        raise ValueError("An allocation must be for more than nothing")

    allocation = PaymentAllocation(
        payment_transaction_id=transaction.id,
        payroll_snapshot_id=snapshot.id,
        allocated_piastres=int(piastres),
    )
    db.add(allocation)
    db.flush()

    record_audit(
        db,
        action="payment.allocated",
        subject=f"affiliate:{transaction.affiliate_id}",
        actor_id=actor_id,
        actor_email=actor_email,
        after={
            "transaction_id": transaction.id,
            "snapshot_id": snapshot.id,
            "piastres": int(piastres),
        },
    )
    return allocation


def payments_for(
    db: Session, affiliate: AffiliateProfile
) -> list[PaymentTransaction]:
    """Everything they have been paid, newest first."""
    return list(
        db.scalars(
            select(PaymentTransaction)
            .where(PaymentTransaction.affiliate_id == affiliate.id)
            .order_by(PaymentTransaction.occurred_at.desc())
        )
    )


# -- Adjustments (Section 11.5) -----------------------------------------------


def adjust(
    db: Session,
    affiliate: AffiliateProfile,
    *,
    kind: str,
    source_month: str,
    amount_piastres: int,
    reason: str,
    destination_month: str | None = None,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> PayrollAdjustment:
    """Move money without a transfer: a credit, a write-off, a correction.

    This is where the sentence Phase 6 left unfinished ends. Re-approving a
    reopened month may find a model **overpaid**, and Section 11.5 says the
    maintainer chooses between applying the excess against a later month and
    absorbing it. `reconciliation_for` reports the difference and returns
    `resolution: None`; this fills it in.

    **A reason is required.** An adjustment is money moving with no bank record
    behind it, and the only thing that makes one auditable is why.

    **A credit needs somewhere to land.** A write-off does not - it goes
    nowhere, which is what absorbing means.
    """
    if kind not in VALID_ADJUSTMENT_TYPES:
        raise ValueError(f"Unknown adjustment type: {kind!r}")
    if amount_piastres <= 0:
        raise ValueError("An adjustment must be for more than nothing")
    if not str(reason or "").strip():
        raise ValueError(
            "An adjustment needs a reason. It is money moving with no bank "
            "record behind it, and the reason is the only thing that makes it "
            "auditable."
        )

    source = get_month(db, affiliate, source_month)
    if source is None:
        raise ValueError(f"{affiliate.name} has no {source_month} to adjust")

    destination = None
    if kind == AdjustmentType.CREDIT:
        if destination_month is None:
            raise ValueError(
                "A credit needs a month to land on. To absorb it instead, "
                "record a write-off."
            )
        # Opened on demand, which is exactly what ADR 0013 says a month row is
        # for: created because somebody asked, not on a schedule.
        #
        # Refusing here instead was a dead end at the one moment this is used.
        # An overpayment is found in early October, when October has not been
        # approved and so has no row - and the refusal said "open that month
        # first", naming a step nothing in the platform could perform. The only
        # way out was to write off money that should have carried forward, or
        # to remember to come back, which §11.5 is entirely about not relying
        # on.
        #
        # The credit sits on the draft month and changes nothing until that
        # month is approved, at which point `credited_into` folds it into the
        # balance. A month opened this way has no snapshots, so it is not one
        # of the reopened-and-forgotten months either.
        destination = open_month(db, affiliate, destination_month)
        if destination.id == source.id:
            raise ValueError(
                "A credit cannot land on the month it came from - that is a "
                "write-off."
            )
    elif destination_month is not None:
        raise ValueError(
            f"A {kind} goes nowhere. Only a credit lands on another month."
        )

    # **Nothing may be settled twice, and nothing more than once over.**
    #
    # ADR 0035. The screen already caps at the difference it displays, and
    # that was not enough: while the displayed difference was itself wrong,
    # the cap moved with it and each settle doubled the figure. A cap the
    # browser cannot see past is the one that holds - so this asks the balance
    # again, here, and refuses anything larger than what is genuinely open.
    #
    # `settling` is what is left after every adjustment already recorded, so
    # two half-settlements are fine and a second full one is not.
    open_difference = balance_for(db, affiliate, source_month)["balance_piastres"]
    settling = abs(open_difference)
    if settling == 0:
        raise ValueError(
            f"{source_month} has nothing left to settle. Its difference has "
            "already been closed."
        )
    if int(amount_piastres) > settling:
        raise ValueError(
            f"That is more than the difference. {source_month} has "
            f"{settling} piastres open, and an adjustment can only close what "
            "is there."
        )

    # **A credit carries an excess. It cannot carry a debt.**
    #
    # A write-off works in either direction - absorbing an overpayment, or
    # forgiving what is still owed - because both end with HBA out of pocket
    # and the month at zero. A credit does not: it says the model *already
    # holds* this money, so the later month needs less sent.
    #
    # From a month that is still owed, that sentence is false twice over. The
    # source would drop by the amount and the destination would drop by it
    # again, and the model would end up short by exactly the credit. Refusing
    # is not a restriction on a legitimate act; there is no such act.
    if kind == AdjustmentType.CREDIT and open_difference > 0:
        raise ValueError(
            f"{source_month} is still owed money, so there is no excess to "
            "carry forward. Pay it, or write it off."
        )

    adjustment = PayrollAdjustment(
        type=kind,
        source_payroll_month_id=source.id,
        destination_payroll_month_id=destination.id if destination else None,
        amount_piastres=int(amount_piastres),
        reason=reason.strip(),
        created_by=actor_id,
    )
    db.add(adjustment)
    db.flush()

    record_audit(
        db,
        action=f"adjustment.{kind}",
        subject=f"affiliate:{affiliate.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        after={
            "source_month": source_month,
            "destination_month": destination_month,
            "amount_piastres": int(amount_piastres),
        },
        reason=reason.strip(),
    )
    return adjustment


def adjustments_for(
    db: Session, affiliate: AffiliateProfile
) -> list[PayrollAdjustment]:
    """Every credit and write-off touching this affiliate, newest first.

    Section 11.5 requires these to be visible to them: a credit they cannot see
    is a credit they cannot check.
    """
    months = select(PayrollMonth.id).where(PayrollMonth.affiliate_id == affiliate.id)
    return list(
        db.scalars(
            select(PayrollAdjustment)
            .where(PayrollAdjustment.source_payroll_month_id.in_(months))
            .order_by(PayrollAdjustment.created_at.desc())
        )
    )
