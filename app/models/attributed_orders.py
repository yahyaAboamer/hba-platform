"""Attributed orders - the second tier of §10.2, and where money begins.

``order_index`` holds every order Shopify has, thinly. This table holds the
financial detail, and only for orders that belong to somebody. At roughly 1.4 KB
a row against 150 bytes, storing every order this way would be spending about
nine times the space to record that nothing is owed.

**A row existing means the order is attributed.** There is no such thing as an
attributed order with no affiliate, so ``affiliate_id`` is NOT NULL. An
unattributed order is simply an ``order_index`` row with no row here, and
attaching an orphan later (§9.2) is an INSERT rather than filling in a blank.
The alternative - nullable ``affiliate_id``, a row for every order - would
duplicate ``order_index`` at nine times the cost and hand every future reader a
column that is usually null.

## What is frozen, and what is not

The commission base legitimately moves. An order edited before it ships should
reflect the edit, so this table is **not** append-only; making it so would force
a new row per fulfilment event to protect two fields that a trigger protects for
nothing.

Two fields never move, and the database enforces both:

``affiliate_id`` - §9.2 and §17. Orders do not move between models. Reassigning
one would change what an already-calculated month was worth, and the month would
silently disagree with itself.

``business_month`` - the month the order was **placed**, derived in Cairo
(ADR 0005) and copied here rather than joined. Copying is what stops a month's
figures shifting underneath an approved payroll. If it could change, money would
move between months, which is the same failure wearing a different hat.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class CommissionState:
    """§9.4. Only ``EARNED`` counts toward a payout."""

    #: In transit, or an exchange is open. Shown separately, never hidden - a
    #: model should be able to see what is coming.
    PENDING = "pending"

    #: Delivered, with no open return or exchange. This is the one that pays.
    EARNED = "earned"

    #: Cancelled, fully refunded, or failed delivery.
    VOID = "void"


VALID_COMMISSION_STATES = frozenset(
    value
    for name, value in vars(CommissionState).items()
    if not name.startswith("_") and isinstance(value, str)
)


class AttributedOrder(Base):
    """One order, and what it is worth to one affiliate."""

    __tablename__ = "attributed_order"
    __table_args__ = (
        CheckConstraint(
            "commission_state IN ('pending', 'earned', 'void')",
            name="attributed_order_state_valid",
        ),
        CheckConstraint(
            "commission_base_piastres >= 0",
            name="attributed_order_base_not_negative",
        ),
        CheckConstraint(
            "refunded_merchandise_piastres >= 0",
            name="attributed_order_refund_not_negative",
        ),
        # "What did she earn in August?" - the question this table exists to
        # answer, asked once per affiliate per month for every payroll run.
        Index(
            "attributed_order_affiliate_month_idx", "affiliate_id", "business_month"
        ),
        # The same question across everybody, for a whole-programme month view.
        Index("attributed_order_business_month_idx", "business_month"),
    )

    #: Shared with order_index, so the thin row and the financial row are the
    #: same order by construction rather than by a join key someone maintains.
    shopify_order_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("order_index.shopify_order_id", ondelete="CASCADE"),
        primary_key=True,
    )

    #: RESTRICT, deliberately, where discount_code_period cascades. A code
    #: period is a fact about arrangement and can go with the affiliate; this
    #: row is a fact about money. Deleting an affiliate who has been paid should
    #: fail loudly rather than quietly erase what she was paid for. Affiliates
    #: are archived (Phase 3), not deleted, so this should never fire - which is
    #: exactly when a guard is worth having.
    affiliate_id: Mapped[int] = mapped_column(
        ForeignKey("affiliate_profile.id", ondelete="RESTRICT"), nullable=False
    )

    #: Copied from order_index, never recomputed. See the module docstring.
    business_month: Mapped[str] = mapped_column(String(7), nullable=False)

    #: Total the customer pays, minus shipping, minus tax (§9.3, ADR 0011).
    #: BigInteger because piastres are 100x the pound figure and a 32-bit
    #: column overflows at about E£21 million.
    commission_base_piastres: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )

    #: Merchandise the customer was genuinely refunded for, which reduces the
    #: base while the month is still draft. Stored separately from the base so
    #: the reduction is visible rather than baked into one number nobody can
    #: explain later.
    refunded_merchandise_piastres: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )

    commission_state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=CommissionState.PENDING
    )

    #: When the base stopped moving - the delivery, since delivery is final
    #: (ADR 0025). NULL means the order has not arrived yet.
    base_frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    financial_status: Mapped[str | None] = mapped_column(String(40))
    fulfillment_status: Mapped[str | None] = mapped_column(String(40))

    #: When Shopify reported the parcel delivered. This is what makes an order
    #: earned (ADR 0012), and the signal that can die silently (ADR 0023).
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Shopify's return state for the order. Any activity here freezes the base.
    return_status: Mapped[str | None] = mapped_column(String(40))

    attributed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    affiliate = relationship("AffiliateProfile", lazy="joined")
    order = relationship("OrderIndex", lazy="joined")

    @property
    def is_frozen(self) -> bool:
        return self.base_frozen_at is not None

    @property
    def counts_toward_payout(self) -> bool:
        """§9.4. Only earned orders do."""
        return self.commission_state == CommissionState.EARNED

    def __repr__(self) -> str:
        return (
            f"<AttributedOrder {self.shopify_order_id} "
            f"affiliate={self.affiliate_id} {self.commission_state}>"
        )
