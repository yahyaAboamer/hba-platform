"""The order index.

Every Shopify order gets a row here, whether or not it used an affiliate code.
The row is deliberately small - roughly 150 bytes - because the point is
breadth, not depth. Full financial detail for attributed orders arrives in a
later phase, once affiliates exist to attribute them to.

Keeping the unattributed orders is what makes two things possible: registering
a code later and instantly finding the orders that already used it, and
alerting on a code that is live in Shopify but belongs to no affiliate.
Discarding them would leave both questions answerable only by re-scanning all
of Shopify.
"""

from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, DateTime, Index, String, text
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
    fulfillment_status: Mapped[str | None] = mapped_column(String(40))
    discount_codes: Mapped[list[str]] = mapped_column(
        ARRAY(String(120)), nullable=False, server_default="{}"
    )
    # BigInteger throughout: piastres are 100x the pound figure, so a 32-bit
    # column would overflow at roughly E£21 million.
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
