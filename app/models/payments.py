"""Money that actually moved, and how it is applied.

§14, §8. Phase 6 produced an **obligation** - a frozen figure somebody agreed.
This is the record that it was **settled**.

## The Pay button changes nothing

§14's first line, and the reason nothing here is written automatically. The
button opens InstaPay with the address filled in and alters no state; the
maintainer sends the money by hand, screenshots the confirmation, and *then*
records it. **A button that both opens a payment app and marks a debt settled
will eventually mark one settled that failed.**

Everything in this module is a record of something a person did outside the
platform, and it must stay that way.

## Three entities, because one transfer is not one month

A single E£10,000 transfer allocates E£7,000 to August and E£3,000 to September
**without pretending two transfers occurred**. InstaPay limits make the reverse
just as ordinary - two transfers settling one month. The old system could
represent neither.

## Allocations point at a snapshot, not a month

§11.5 requires that payments made against a superseded version remain intact and
visible after a reopen. That is only expressible if the allocation names the
**version** it settled: a month can be reopened and re-approved, and the money
that moved was against a particular figure agreed on a particular day.

## Append-only, all of it

§17. A payment that can be edited is a payment nobody can reconcile against a
bank statement. Corrections are `payroll_adjustment` rows, which say what they
are.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    LargeBinary,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class AdjustmentType:
    """§11.5. Money moving without a transfer."""

    #: They were overpaid, and the excess is applied against a later month.
    CREDIT = "credit"

    #: They were overpaid, and HBA absorbs it. Nothing is recovered.
    WRITEOFF = "writeoff"

    #: A bookkeeping correction that is neither of the above.
    CORRECTION = "correction"


VALID_ADJUSTMENT_TYPES = frozenset(
    value
    for name, value in vars(AdjustmentType).items()
    if not name.startswith("_") and isinstance(value, str)
)


class ProofFile(Base):
    """One payment screenshot.

    **Its own table, deliberately** (ADR 0026). A blob column on
    `payment_transaction` would be loaded by every query that touched a
    payment - the payments list, the settlement calculation, the audit render -
    because selecting a row selects its columns.
    """

    __tablename__ = "proof_file"

    #: The content hash, which makes re-uploading the same screenshot
    #: idempotent rather than duplicating the bytes.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    #: Who it belongs to. Checked on every read - a URL is not a permission.
    affiliate_id: Mapped[int] = mapped_column(
        ForeignKey("affiliate_profile.id", ondelete="RESTRICT"), nullable=False
    )

    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_type: Mapped[str] = mapped_column(String(40), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    uploaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    affiliate = relationship("AffiliateProfile", lazy="joined")

    def __repr__(self) -> str:
        return f"<ProofFile {self.id[:12]} {self.size_bytes}b>"


class PaymentTransaction(Base):
    """Money that left HBA and reached a model."""

    __tablename__ = "payment_transaction"
    __table_args__ = (
        # §17. A payment of zero is not a payment, and a negative one is an
        # adjustment wearing the wrong hat - payroll_adjustment has the right
        # one.
        CheckConstraint(
            "amount_piastres > 0", name="payment_transaction_amount_positive"
        ),
        Index("payment_transaction_affiliate_idx", "affiliate_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    affiliate_id: Mapped[int] = mapped_column(
        # RESTRICT. Deleting somebody who has been paid should fail loudly
        # rather than quietly erase the record that they were.
        ForeignKey("affiliate_profile.id", ondelete="RESTRICT"), nullable=False
    )

    amount_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False)

    #: When the money moved, which is not when it was recorded. A transfer sent
    #: on Friday and entered on Monday belongs to Friday.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    #: Where it went, **masked** and frozen (§6.4.4). Not a foreign key:
    #: payout_destination is append-only precisely so a past payment resolves
    #: the destination in force at the time, and copying the masked values means
    #: this record still reads correctly however many times that row is later
    #: superseded.
    #:
    #: Never the raw destination. `mask_destination` is the only sanctioned
    #: representation outside the owner's own screen, and this is not that
    #: screen.
    destination_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    #: The proof screenshot (§14). Optional - a bank transfer with a reference
    #: number is still a payment.
    proof_file_id: Mapped[str | None] = mapped_column(String(64))

    #: The bank or InstaPay reference, if there is one.
    reference: Mapped[str | None] = mapped_column(String(120))

    #: §14. **Required whenever the amount differs from balance_due** - the note
    #: is what separates a deliberate partial payment from a typo, and only the
    #: person recording it knows which.
    note: Mapped[str | None] = mapped_column(Text)

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    affiliate = relationship("AffiliateProfile", lazy="joined")
    allocations = relationship(
        "PaymentAllocation", back_populates="transaction", lazy="selectin"
    )

    @property
    def allocated_piastres(self) -> int:
        return sum(row.allocated_piastres for row in self.allocations)

    @property
    def unallocated_piastres(self) -> int:
        """Money received and not yet applied to any month.

        Allowed: a transfer may arrive before anybody has decided which months
        it covers, and forcing a split at the moment of recording would invent
        an answer.
        """
        return self.amount_piastres - self.allocated_piastres

    def __repr__(self) -> str:
        return (
            f"<PaymentTransaction affiliate={self.affiliate_id} "
            f"{self.amount_piastres}p>"
        )


class PaymentAllocation(Base):
    """How one transfer is applied to one agreed figure."""

    __tablename__ = "payment_allocation"
    __table_args__ = (
        CheckConstraint(
            "allocated_piastres > 0", name="payment_allocation_amount_positive"
        ),
        Index("payment_allocation_snapshot_idx", "payroll_snapshot_id"),
        Index("payment_allocation_transaction_idx", "payment_transaction_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("payment_transaction.id", ondelete="RESTRICT"), nullable=False
    )

    #: The **version** that was settled, not the month. See the module
    #: docstring: a month can be reopened and re-approved, and the money that
    #: moved was against a particular figure agreed on a particular day.
    payroll_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_snapshot.id", ondelete="RESTRICT"), nullable=False
    )

    allocated_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    transaction = relationship("PaymentTransaction", back_populates="allocations")
    snapshot = relationship("PayrollSnapshot", lazy="joined")

    def __repr__(self) -> str:
        return (
            f"<PaymentAllocation transaction={self.payment_transaction_id} "
            f"snapshot={self.payroll_snapshot_id} {self.allocated_piastres}p>"
        )


class PayrollAdjustment(Base):
    """Money moving without a transfer: a credit, a write-off, a correction.

    §11.5. This is where the sentence Phase 6 left unfinished ends. Re-approving
    a reopened month may find a model **overpaid**, and the maintainer chooses
    between applying the excess against a later month and absorbing it. The
    platform reports the difference and refuses to choose.
    """

    __tablename__ = "payroll_adjustment"
    __table_args__ = (
        CheckConstraint(
            "type IN ('credit', 'writeoff', 'correction')",
            name="payroll_adjustment_type_valid",
        ),
        CheckConstraint(
            "amount_piastres > 0", name="payroll_adjustment_amount_positive"
        ),
        Index("payroll_adjustment_source_idx", "source_payroll_month_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)

    #: The month the money is owed *from*.
    source_payroll_month_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_month.id", ondelete="RESTRICT"), nullable=False
    )

    #: Where a credit lands. NULL on a write-off, which goes nowhere - HBA
    #: absorbs it.
    destination_payroll_month_id: Mapped[int | None] = mapped_column(
        ForeignKey("payroll_month.id", ondelete="RESTRICT")
    )

    amount_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False)

    #: **Required.** An adjustment is money moving without a transfer, and the
    #: only thing that makes it auditable is why.
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    source_month = relationship(
        "PayrollMonth", foreign_keys=[source_payroll_month_id], lazy="joined"
    )
    destination_month = relationship(
        "PayrollMonth", foreign_keys=[destination_payroll_month_id], lazy="joined"
    )

    def __repr__(self) -> str:
        return f"<PayrollAdjustment {self.type} {self.amount_piastres}p>"
