"""the catalogue, and what was in each order

Three tables the platform has never had, and one scope it has never asked for.

`product` and `product_variant` cache what HBA sells, because a roster of
thirty rows must not be thirty Shopify calls on a screen somebody opens all
month. `order_line_item` records what was actually in an order, which
`order_index` deliberately does not hold - §10.2 keeps that index to what
commission needs, and W11 needs line items for a different job: real
after-discount values and real quantities, rather than sums of listed prices.

## Nothing here is customer data

No name, address, phone or email in any of the three. A line item is a product,
a size, a count and two prices. The recipient's phone that W03 matches on is
**not here** - that belongs to the restricted path in 03B and to nothing else,
and the cheapest way never to leak a field is never to store it.

## Why the snapshots

W01 asks that historical wardrobe items stay accessible when a product is no
longer sold. So `order_line_item` carries its own `title` and `variant_title`
as they were when the order was placed, and its product and variant ids are
**nullable**: a product deleted from Shopify takes its id out of the payload,
and the line is still a real thing that was sent to a real person.

`ON DELETE CASCADE` from `order_index` and not from `product`, deliberately.
Removing an order removes what was in it; removing a product must not remove
the evidence of what somebody was sent.

## Additive, and nothing existing reads it yet

No column on any existing table changes. Commission ingestion does not touch
these, which is the requirement in 03A's prompt: *new recipient field denial
cannot break existing commission sync.* If Shopify refuses a product field
tomorrow, these tables go stale and orders keep indexing.

Revision ID: e7c2a5f1b930
Revises: d4b81c07af22
Create Date: 2026-09-10 09:20:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7c2a5f1b930"
down_revision: Union[str, Sequence[str], None] = "d4b81c07af22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product",
        sa.Column("shopify_product_id", sa.String(length=32), primary_key=True),
        sa.Column("shopify_product_gid", sa.String(length=120), nullable=True),
        sa.Column("title", sa.String(length=400), nullable=False),
        sa.Column("handle", sa.String(length=400), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("image_url", sa.String(length=1000), nullable=True),
        sa.Column("image_alt", sa.String(length=400), nullable=True),
        sa.Column("updated_at_shopify", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived', 'draft')", name="product_status_valid"
        ),
    )
    op.create_index("product_status_idx", "product", ["status"])

    op.create_table(
        "product_variant",
        sa.Column("shopify_variant_id", sa.String(length=32), primary_key=True),
        sa.Column("shopify_variant_gid", sa.String(length=120), nullable=True),
        sa.Column(
            "shopify_product_id",
            sa.String(length=32),
            sa.ForeignKey("product.shopify_product_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("sku", sa.String(length=200), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "product_variant_product_idx", "product_variant", ["shopify_product_id"]
    )

    op.create_table(
        "order_line_item",
        sa.Column("shopify_line_item_id", sa.String(length=32), primary_key=True),
        sa.Column(
            "shopify_order_id",
            sa.String(length=32),
            sa.ForeignKey("order_index.shopify_order_id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Nullable on purpose. A deleted product leaves the line intact; the
        # title snapshot beside it is what keeps the row meaningful.
        sa.Column("shopify_product_id", sa.String(length=32), nullable=True),
        sa.Column("shopify_variant_id", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=400), nullable=False),
        sa.Column("variant_title", sa.String(length=200), nullable=True),
        sa.Column("sku", sa.String(length=200), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("discounted_total_piastres", sa.BigInteger(), nullable=False),
        sa.Column("original_total_piastres", sa.BigInteger(), nullable=False),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("quantity > 0", name="order_line_item_quantity_positive"),
        sa.CheckConstraint(
            "discounted_total_piastres >= 0",
            name="order_line_item_discounted_not_negative",
        ),
    )
    op.create_index("order_line_item_order_idx", "order_line_item", ["shopify_order_id"])
    op.create_index(
        "order_line_item_product_idx", "order_line_item", ["shopify_product_id"]
    )


def downgrade() -> None:
    """Drops a cache and an evidence trail.

    The catalogue is re-fetchable. The line items are not, past Shopify's
    ordinary sixty-day window, so a downgrade here is a decision about
    history rather than about schema.
    """
    op.drop_index("order_line_item_product_idx", table_name="order_line_item")
    op.drop_index("order_line_item_order_idx", table_name="order_line_item")
    op.drop_table("order_line_item")
    op.drop_index("product_variant_product_idx", table_name="product_variant")
    op.drop_table("product_variant")
    op.drop_index("product_status_idx", table_name="product")
    op.drop_table("product")
