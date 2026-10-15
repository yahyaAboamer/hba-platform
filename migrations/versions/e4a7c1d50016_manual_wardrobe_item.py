"""a product staff say a model has, with no order behind it

ADR 0061. Models sometimes collect a piece from the warehouse; no Shopify
order records it, so staff assign it on the product. One new table; nothing
existing is touched. Downgrade drops it, and the manual assignments with it.

Revision ID: e4a7c1d50016
Revises: d3f6b9c40015
Create Date: 2026-10-15 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e4a7c1d50016"
down_revision: Union[str, Sequence[str], None] = "d3f6b9c40015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "manual_wardrobe_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "affiliate_id",
            sa.Integer(),
            sa.ForeignKey("affiliate_profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shopify_product_id",
            sa.String(32),
            sa.ForeignKey("product.shopify_product_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("size", sa.String(200)),
        sa.Column(
            "assigned_by_id",
            sa.Integer(),
            sa.ForeignKey("user_account.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "affiliate_id", "shopify_product_id", name="manual_wardrobe_item_once"
        ),
    )
    op.create_index(
        "manual_wardrobe_item_product_idx",
        "manual_wardrobe_item",
        ["shopify_product_id"],
    )


def downgrade() -> None:
    op.drop_index("manual_wardrobe_item_product_idx", table_name="manual_wardrobe_item")
    op.drop_table("manual_wardrobe_item")
