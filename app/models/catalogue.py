"""The Shopify catalogue, and what was in each order.

Two subjects that arrive from the same API and answer different questions.

**The catalogue** is what HBA sells: a product, its variants, and a picture.
Cached locally because a product roster showing thirty rows would otherwise be
thirty Shopify calls, on a screen somebody opens all month (`BACKEND_CONTRACTS`:
*don't make a Shopify call per visible row*).

**Line items** are what was actually in an order. `order_index` deliberately
does not hold them - §10.2 keeps it to what commission needs - and W11 needs
them for a different reason entirely: *top-seller analytics must use real
attributed line items and discounts/quantities, not item name/undiscounted
price sums.*

## Nothing here is customer data

No name, no address, no phone, no email. A line item is a product, a size, a
count and a price. The structural test that keeps `order_index` and
`attributed_order` free of personal data applies to these tables too, and for
the same reason: the cheapest way to never leak a field is to never store it.

The recipient's phone, which W03 matches on, is **not here.** That belongs to
the restricted path in 03B and to nothing else.

## Why snapshots, and not just ids

W01: *keep historical wardrobe items accessible if no longer sold*, and
preserve title/size evidence when a product is archived, renamed or removed.

So a line item carries its own copy of the title and the variant title as they
were when the order was placed. A product renamed in March does not rewrite
what a model was sent in January, and a product deleted from Shopify does not
turn her wardrobe into a list of blanks. The ids stay too, so a live product
can still be joined for its current picture - but the row does not depend on
that join surviving.
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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProductStatus:
    """Shopify's own three, lowercased on the way in."""

    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"


VALID_PRODUCT_STATUSES = frozenset(
    value for name, value in vars(ProductStatus).items() if not name.startswith("_")
)

_STATUS_LIST = ", ".join(f"'{status}'" for status in sorted(VALID_PRODUCT_STATUSES))


class Product(Base):
    """One product in the shop, as HBA last saw it."""

    __tablename__ = "product"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_LIST})", name="product_status_valid"),
        Index("product_status_idx", "status"),
    )

    #: Shopify's numeric id as a string, matching `order_index`'s convention.
    #: The GID is kept beside it because the GraphQL API speaks in GIDs and
    #: reconstructing one by string concatenation is how an API version change
    #: breaks a join quietly.
    shopify_product_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    shopify_product_gid: Mapped[str | None] = mapped_column(String(120))

    title: Mapped[str] = mapped_column(String(400), nullable=False)
    handle: Mapped[str | None] = mapped_column(String(400))

    #: W01: the catalogue defaults to active products and *All products*
    #: includes draft and archived ones. Kept rather than filtered on ingest,
    #: because a product archived in Shopify is still in somebody's wardrobe.
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    #: One picture. The roster shows a thumbnail, not a gallery, and storing
    #: every image would be storing what nothing reads. A deleted source image
    #: leaves this pointing nowhere, which the interface renders as an honest
    #: fallback rather than a broken frame.
    image_url: Mapped[str | None] = mapped_column(String(1000))
    image_alt: Mapped[str | None] = mapped_column(String(400))

    #: Shopify's own timestamp, for deciding whether a row is behind.
    updated_at_shopify: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    #: **Freshness.** When HBA last heard from Shopify about this row - which is
    #: a different fact from when Shopify last changed it, and the one a screen
    #: needs in order to say "as of" rather than implying "now".
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ProductVariant(Base):
    """A size. W01: colour belongs in the product name; size is the variant."""

    __tablename__ = "product_variant"
    __table_args__ = (Index("product_variant_product_idx", "shopify_product_id"),)

    shopify_variant_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    shopify_variant_gid: Mapped[str | None] = mapped_column(String(120))

    shopify_product_id: Mapped[str] = mapped_column(
        ForeignKey("product.shopify_product_id", ondelete="CASCADE"), nullable=False
    )

    #: "M", "42", "One size". Shopify's variant title.
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(200))
    #: Shopify's ordering, so sizes list as S/M/L rather than alphabetically.
    position: Mapped[int | None] = mapped_column(Integer)

    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class OrderLineItem(Base):
    """One line of one order: a product, a size, a count and a price.

    Kept apart from `order_index` on purpose. That index is what commission
    reads and is deliberately narrow; this is what the wardrobe and the
    top-seller figures read, and joining them is a decision each caller makes
    rather than a shape forced on both.

    **Money is integer piastres**, like everywhere else, and both figures are
    kept: W11 wants after-discount values, and the original is what says a
    discount happened at all.
    """

    __tablename__ = "order_line_item"
    __table_args__ = (
        Index("order_line_item_order_idx", "shopify_order_id"),
        Index("order_line_item_product_idx", "shopify_product_id"),
        CheckConstraint("quantity > 0", name="order_line_item_quantity_positive"),
        CheckConstraint(
            "discounted_total_piastres >= 0",
            name="order_line_item_discounted_not_negative",
        ),
    )

    shopify_line_item_id: Mapped[str] = mapped_column(String(32), primary_key=True)

    shopify_order_id: Mapped[str] = mapped_column(
        ForeignKey("order_index.shopify_order_id", ondelete="CASCADE"), nullable=False
    )

    #: Nullable, both of them. A product deleted from Shopify takes its id out
    #: of the payload, and the line is still a real thing that was sent to a
    #: real person - which is what the snapshots below are for.
    shopify_product_id: Mapped[str | None] = mapped_column(String(32))
    shopify_variant_id: Mapped[str | None] = mapped_column(String(32))

    #: **As it was when the order was placed.** W01: a product renamed or
    #: archived later must not rewrite what she was sent.
    title: Mapped[str] = mapped_column(String(400), nullable=False)
    variant_title: Mapped[str | None] = mapped_column(String(200))
    sku: Mapped[str | None] = mapped_column(String(200))

    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    #: After the customer's discounts, which is the basis W11 asks for.
    discounted_total_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: Before them. Their difference is the only evidence a discount applied.
    original_total_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False)

    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
