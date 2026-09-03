"""The order index.

Every Shopify order gets a row here, whether or not it used an affiliate code.
The row is deliberately small - roughly 150 bytes - because the point is
breadth, not depth. Full financial detail for attributed orders lives in
``attributed_order``.

Delivery, returns and refunds are carried **here** rather than only on the
attributed rows, which costs about 40 bytes an order - a megabyte a year at
HBA's volume. The alternative is worse than it looks: registering a code
backfills its history, and if the delivery facts lived only on attributed rows
that backfill would need one Shopify call per order to learn what it could have
read locally.

Keeping the unattributed orders is what makes two things possible: registering
a code later and instantly finding the orders that already used it, and
alerting on a code that is live in Shopify but belongs to no affiliate.
Discarding them would leave both questions answerable only by re-scanning all
of Shopify.
"""

from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, Boolean, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class OrderIndex(Base):
    __tablename__ = "order_index"
    __table_args__ = (
        Index("order_index_business_month_idx", "business_month"),
        # GIN over the code array. "Which orders used NOUR10?" is the question
        # this table exists to answer, and a btree cannot answer it.
        Index(
            "order_index_discount_codes_idx",
            "discount_codes",
            postgresql_using="gin",
        ),
    )

    shopify_order_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    shopify_order_gid: Mapped[str | None] = mapped_column(String(120))
    order_number: Mapped[str] = mapped_column(String(40), nullable=False)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    business_month: Mapped[str] = mapped_column(String(7), nullable=False)
    updated_at_shopify: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    financial_status: Mapped[str | None] = mapped_column(String(40))

    #: Shopify's **order-level** status. Two values across 529 real orders,
    #: fulfilled and unfulfilled: it says the parcel left, not that it arrived.
    fulfillment_status: Mapped[str | None] = mapped_column(String(40))

    #: What the fulfilments reduce to: delivered, failed, or in_flight. This is
    #: what ADR 0012 pays on. In a live sample of 50 orders the order-level
    #: status called fulfilled, only 35 were actually delivered - so paying on
    #: fulfillment_status would have paid for fifteen parcels the customer did
    #: not have.
    delivery_state: Mapped[str | None] = mapped_column(String(16))

    #: Shopify's own word for it, kept so a new courier status is recognisable
    #: in the data rather than only in a log line.
    delivery_status: Mapped[str | None] = mapped_column(String(40))

    #: When the customer had all of it. The latest delivery across the
    #: fulfilments, because a split shipment is not delivered until the last
    #: parcel lands.
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    return_status: Mapped[str | None] = mapped_column(String(40))

    #: **Still being decided.** Blocks the order from earning (§9.4) - it is
    #: neither paid nor voided while somebody is deciding.
    return_open: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    #: **Anything ever happened.** Freezes the base permanently (ADR 0011),
    #: including after the return finishes - the subtotal E-stebdal leaves
    #: behind is the inflated number the freeze exists to keep out.
    #:
    #: Two columns because they are two questions. Using one for both parks
    #: every completed return in pending for ever.
    return_activity: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    #: **Both numbers, deliberately.** They disagree on the case that matters:
    #: an exchange records returned merchandise with nothing refunded, and
    #: subtracting the merchandise would underpay a model whose customer paid
    #: in full and swapped for goods of equal value. Task 3 decides; storing
    #: one of them would decide it here, wrongly.
    refunded_total_piastres: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    refunded_merchandise_piastres: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    discount_codes: Mapped[list[str]] = mapped_column(
        ARRAY(String(120)), nullable=False, server_default="{}"
    )
    # BigInteger throughout: piastres are 100x the pound figure, so a 32-bit
    # column would overflow at roughly E£21 million.
    #: **The order as it was placed.** Display only, and never paid on.
    #:
    #: Shopify zeroes the `current*` totals when an order is cancelled. That is
    #: right for commission - §9.3 pays on what the customer actually paid -
    #: and it left a model's Orders screen printing a struck-through E£0.00 for
    #: a cancelled order, because the figure it wanted no longer existed
    #: anywhere. These keep it.
    #:
    #: Nullable, because every row indexed before this existed has no answer
    #: and a zero would be indistinguishable from a genuinely free order. A
    #: re-import fills them in.
    #:
    #: **Never read by `calculate.py`.** Paying on these would pay for parcels
    #: that were cancelled.
    original_subtotal_piastres: Mapped[int | None] = mapped_column(BigInteger)
    original_total_piastres: Mapped[int | None] = mapped_column(BigInteger)

    subtotal_piastres: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    total_piastres: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    shipping_piastres: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    tax_piastres: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False, server_default="EGP")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
