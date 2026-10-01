"""a line an order edit removed was not sent

An order edit does not remove a line in Shopify: it keeps it at its original
`quantity` and drops `currentQuantity` to 0. The line reader took `quantity`,
so Ali's wardrobe showed an XL he was swapped out of before #21585 shipped.

- `order_line_item.ordered_quantity` - Shopify's `quantity`, what was first
  ordered; `quantity` is now what is still the order's. NULL means read before
  this was asked; the hourly line-item sweep reads those orders again, and a
  removed line drops out when it does.

Additive only: one nullable column, no default, no index, so no table rewrite.
Downgrade drops it; the code reads its absence as unread.

Revision ID: e1a5c3b70010
Revises: d9e4f7a50009
Create Date: 2026-10-01 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1a5c3b70010"
down_revision: Union[str, Sequence[str], None] = "d9e4f7a50009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "order_line_item",
        sa.Column("ordered_quantity", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_line_item", "ordered_quantity")
