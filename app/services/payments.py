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


def adjusted_against(db: Session, payroll_month: PayrollMonth) -> int:
    """Credits and write-offs reducing what this month still owes.

    A **credit** moves the excess to a later month, so it reduces the source and
    is expected to increase the destination. A **write-off** reduces the source
    and goes nowhere - HBA absorbs it.
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
    paid = allocated_to(db, snapshot)
    adjusted = adjusted_against(db, payroll_month)
    credited = credited_into(db, payroll_month)

    balance = obligation + credited - paid - adjusted

    return {
        "month": month,
        "state": SettlementState.of(obligation + credited, paid + adjusted),
        # Payments allocate to a **snapshot**, not to a month (§11.5): money
        # paid against a superseded version has to stay attached to the version
        # it settled. Anything recording a payment therefore needs this id, so
        # the balance that says what is owed also says what to pay it against.
        "payroll_snapshot_id": snapshot.id,
        "version": snapshot.version,
        "obligation_piastres": obligation,
        "paid_piastres": paid,
        "adjusted_piastres": adjusted,
        "credited_piastres": credited,
        "balance_piastres": balance,
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
    """Everything she has been paid, newest first."""
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

    Section 11.5 requires these to be visible to her: a credit she cannot see
    is a credit she cannot check.
    """
    months = select(PayrollMonth.id).where(PayrollMonth.affiliate_id == affiliate.id)
    return list(
        db.scalars(
            select(PayrollAdjustment)
            .where(PayrollAdjustment.source_payroll_month_id.in_(months))
            .order_by(PayrollAdjustment.created_at.desc())
        )
    )
