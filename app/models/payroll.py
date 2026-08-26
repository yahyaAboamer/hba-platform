"""Payroll months, and the snapshots that freeze them.

§11. Everything before this recalculates: ask what April is worth twice and you
may get two answers, because an order was delivered in between. That is right
while a month is open and **intolerable once somebody has been paid.**

## Two states, not one

§11.1, and this is a defect being fixed. The old dashboard had a single column
and produced the awkward *"Approved · Partially paid"*.

**Calculation state** lives here: `historical`, `draft`, `approved`.

**Settlement is derived, never stored:**

    balance_due = approved obligation - allocations - credits and write-offs

A stored settlement disagrees with the ledger the moment an allocation is
recorded and nobody re-runs whatever was meant to update it. Deriving it also
makes a reopened month unambiguous - the calculation returns to `draft` while the
platform still knows exactly how much cash went out against the old snapshot.

## A snapshot that recomputes is not a snapshot

`payload_json` holds the **whole calculation** - every order, its base, the terms
applied, the target that unlocked a guarantee - rather than references to them.
The point is that it survives what happens next: a code changing hands, a rate
correction, a target re-verified. A snapshot storing ids would quietly recompute
to something different the day any of those changed, and the audit trail would be
describing a figure that no longer exists.

## Append-only, by trigger

§17, ADR 0008. A snapshot that can be edited is not a snapshot. Versions increase
per month, so re-approving after a reopen creates version 2 while version 1
survives with the payments made against it.

**There are no `reopened_at` / `reopen_reason` columns**, though §8's field list
mentions them. They cannot both exist and be append-only: writing them means
updating a row the trigger refuses, and carving an exception for three columns
turns "this table cannot change" into "this table cannot change except when it
can" - which is the kind of rule people stop believing.

§11.5 already puts the reason where it belongs: *"requires a written reason,
recorded in the audit log."* `audit_event` is append-only, already carries a
`reason`, and already records who and when. Which version is in force is answered
by `payroll_month.active_snapshot_id`, so a superseded snapshot is recognisable
without a column saying so. §8 is explicitly indicative.

**And no `policy_version` column yet.** §16's versioned rules arrive in Phase 10;
a column nothing writes reads as a feature and is a lie (the same reasoning that
deferred `settled_in_snapshot_id` out of Phase 4). Phase 10 adds it with the
thing that fills it.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class CalculationState:
    """§11.1. Has the amount been agreed?"""

    #: Before go-live. Imported and visible, **never payable, never approvable**
    #: - money already settled outside the platform (§11.2, ADR 0014).
    HISTORICAL = "historical"

    #: Live, and recalculating. The only state the system sets by itself.
    DRAFT = "draft"

    #: Frozen. The obligation is fixed and a person fixed it.
    APPROVED = "approved"


VALID_CALCULATION_STATES = frozenset(
    value
    for name, value in vars(CalculationState).items()
    if not name.startswith("_") and isinstance(value, str)
)


class PayrollMonth(Base):
    """One affiliate's month, and what state its figure is in."""

    __tablename__ = "payroll_month"
    __table_args__ = (
        # §17. Two rows would be two answers to "what is she owed for August?",
        # and whichever the query read first would decide a payment.
        UniqueConstraint("affiliate_id", "month", name="payroll_month_one_per_month"),
        CheckConstraint(
            "calculation_state IN ('historical', 'draft', 'approved')",
            name="payroll_month_state_valid",
        ),
        Index("payroll_month_month_idx", "month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    affiliate_id: Mapped[int] = mapped_column(
        # RESTRICT, not CASCADE. This row is the record that money was agreed.
        # Deleting an affiliate who has been paid should fail loudly rather
        # than quietly erase what she was paid for.
        ForeignKey("affiliate_profile.id", ondelete="RESTRICT"), nullable=False
    )
    month: Mapped[str] = mapped_column(String(7), nullable=False)

    calculation_state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=CalculationState.DRAFT
    )

    #: The version in force. Re-approving a reopened month moves this pointer
    #: rather than overwriting anything, so version 1 survives with the
    #: payments made against it.
    active_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "payroll_snapshot.id",
            ondelete="RESTRICT",
            # The two tables point at each other, so this one is added by ALTER
            # after both exist. Naming it is what lets `alembic check` match it
            # rather than proposing to add it on every run.
            name="payroll_month_active_snapshot_fkey",
            use_alter=True,
        )
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    affiliate = relationship("AffiliateProfile", lazy="joined")
    active_snapshot = relationship(
        "PayrollSnapshot", foreign_keys=[active_snapshot_id], lazy="joined"
    )

    @property
    def is_approved(self) -> bool:
        return self.calculation_state == CalculationState.APPROVED

    @property
    def is_editable(self) -> bool:
        """§11.1. Only a draft month may change.

        This is what `assert_correctable` (compensation) and
        `assert_recordable` (targets) have been waiting for since Phase 3 and
        Phase 5.
        """
        return self.calculation_state == CalculationState.DRAFT

    def __repr__(self) -> str:
        return (
            f"<PayrollMonth affiliate={self.affiliate_id} {self.month} "
            f"{self.calculation_state}>"
        )


class PayrollSnapshot(Base):
    """A frozen calculation. Append-only, versioned, and never recomputed."""

    __tablename__ = "payroll_snapshot"
    __table_args__ = (
        # §17. Versions unique and monotonically increasing per month.
        UniqueConstraint(
            "payroll_month_id", "version", name="payroll_snapshot_version_unique"
        ),
        CheckConstraint("version >= 1", name="payroll_snapshot_version_positive"),
        CheckConstraint(
            "approved_obligation_piastres >= 0",
            name="payroll_snapshot_obligation_not_negative",
        ),
        # §9.6, ADR 0004. A payout is always whole pounds; the exact figure
        # beside it is what the audit shows was calculated.
        #
        # mod(), never `%`. SQLAlchemy escapes `%` for the driver paramstyle
        # and Postgres is handed `%%`, which is not an operator. The same trap
        # cost a migration in Phase 3 and is in docs/limits.md.
        CheckConstraint(
            "mod(approved_obligation_piastres, 100) = 0",
            name="payroll_snapshot_obligation_is_whole_pounds",
        ),
        Index("payroll_snapshot_month_idx", "payroll_month_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    payroll_month_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_month.id", ondelete="RESTRICT"), nullable=False
    )

    #: 1, then 2 after a reopen and re-approval. Never reused.
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    #: The **whole** calculation, not references to it. See the module
    #: docstring: a snapshot storing ids recomputes, and a snapshot that
    #: recomputes is not a snapshot.
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    #: SHA-256 over the payload. "Did this month's figures change?" becomes one
    #: comparison rather than a diff nobody reads.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    #: What was agreed, rounded half-up to whole pounds (ADR 0004).
    approved_obligation_piastres: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )

    #: What was calculated, exactly. Stored as text because it carries
    #: fractional piastres and a float would undo the exactness the whole
    #: arithmetic exists to guarantee.
    exact_unrounded_piastres: Mapped[str] = mapped_column(String(40), nullable=False)

    approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    month = relationship("PayrollMonth", foreign_keys=[payroll_month_id], lazy="joined")

    def __repr__(self) -> str:
        return (
            f"<PayrollSnapshot month={self.payroll_month_id} v{self.version} "
            f"{self.approved_obligation_piastres}p>"
        )
