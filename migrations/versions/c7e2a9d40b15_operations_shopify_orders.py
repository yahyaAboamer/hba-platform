"""the open, unshipped Shopify orders Operations counts

ADR 0057, the Shopify tab. `ops_shopify_order` holds the orders still open in
Shopify and not fully shipped, as the last clean read found them: number,
when placed, tags, how far shipped. Every read replaces the whole set.

No customer details are stored. Nothing existing is touched; downgrade drops
the table, which the next read rebuilds within 5 minutes.

Revision ID: c7e2a9d40b15
Revises: b3d81f6a2c07
Create Date: 2026-10-05 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c7e2a9d40b15"
down_revision: Union[str, Sequence[str], None] = "b3d81f6a2c07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ops_shopify_order",
        sa.Column("shopify_order_id", sa.String(length=32), nullable=False),
        sa.Column("order_number", sa.String(length=40), nullable=False),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "tags", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("fulfillment_status", sa.String(length=40), nullable=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("shopify_order_id"),
    )


def downgrade() -> None:
    op.drop_table("ops_shopify_order")
