"""Which parcel went to which model.

W03 and W06. One row per order that HBA looked at and either attached to a
model or could not — because *"could not, and here is why"* is a state the
business has to be able to see and act on (W12), and a missing row is
indistinguishable from a parcel nobody has examined.

**The recipient token is a normalised phone and is not anonymised.**
`BACKEND_CONTRACTS.md` says so outright: an unkeyed hash does not anonymise a
predictable eleven-digit number. What protects it is that it lives here, on a
permission-gated path, and in `order_index` or a model's own payload never.
"""

from datetime import datetime

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
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Classification:
    """W04, decided from the order's **original** net.

    A later cancellation zeroes Shopify's current totals, and reading those
    would turn every cancelled purchase into a gift - a parcel she paid for,
    recorded as one HBA gave her.
    """

    #: Original net zero. HBA sent it.
    GIFT = "gift"
    #: Original net positive. She bought it.
    PURCHASE = "purchase"
    #: No authoritative original value. **Not a gift.** W04: unknown stays
    #: unknown, because guessing here decides whether something is hers.
    UNKNOWN = "unknown"


class ModelShipment(Base):
    """One order, matched to one model or explained."""

    __tablename__ = "model_shipment"
    __table_args__ = (
        CheckConstraint(
            "classification IN ('gift', 'purchase', 'unknown')",
            name="model_shipment_classification_valid",
        ),
        # A matched row carries when; an unmatched row carries why. Neither
        # half-written state can read as the other.
        CheckConstraint(
            "(affiliate_id IS NOT NULL AND matched_at IS NOT NULL)"
            " OR (affiliate_id IS NULL AND match_reason IS NOT NULL)",
            name="model_shipment_matched_or_explained",
        ),
        UniqueConstraint("shopify_order_id", name="model_shipment_one_per_order"),
        Index("model_shipment_affiliate_idx", "affiliate_id"),
        Index("model_shipment_token_idx", "recipient_token"),
        Index(
            "model_shipment_unmatched_idx",
            "match_reason",
            postgresql_where=text("affiliate_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    shopify_order_id: Mapped[str] = mapped_column(
        ForeignKey("order_index.shopify_order_id", ondelete="CASCADE"), nullable=False
    )

    #: `None` for a parcel that could not be attached. Most of the shop's
    #: orders are customers, and that is not a failure.
    affiliate_id: Mapped[int | None] = mapped_column(
        ForeignKey("affiliate_profile.id", ondelete="CASCADE")
    )

    recipient_token: Mapped[str | None] = mapped_column(String(20))
    match_reason: Mapped[str | None] = mapped_column(String(24))
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    classification: Mapped[str] = mapped_column(String(16), nullable=False)
    original_net_piastres: Mapped[int | None] = mapped_column(BigInteger)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
