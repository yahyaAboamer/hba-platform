"""each fulfilment's facts, the cash paid by delivery, and exchange lines

ADR 0051 (owner, 28 September): a return freezes the order, and a cancelled
fulfilment carries nothing. Three facts make that answerable from the
database rather than from a fresh Shopify audit:

- `order_index.fulfilments` - each fulfilment's status, created and delivered
  times and courier. The reduced `delivery_state` is explained by it.
- `order_index.paid_by_delivery_piastres` - the payments up to delivery; the
  frozen base of an order with a return. NULL means not read.
- `order_line_item.after_delivery` - the line only a post-delivery fulfilment
  carried: an exchange item. NULL means read before this was asked; the
  hourly line-item sweep reads those orders again.

Additive only: three nullable columns, no default, no index, so no table
rewrite and no lock beyond the catalogue change. Downgrade drops them; the
code reads each as absent and behaves as before ADR 0051.

Revision ID: f4a2b8d10005
Revises: e3f1a9c70004
Create Date: 2026-09-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f4a2b8d10005"
down_revision: Union[str, Sequence[str], None] = "e3f1a9c70004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "order_index",
        sa.Column("fulfilments", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "order_index",
        sa.Column("paid_by_delivery_piastres", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "order_line_item",
        sa.Column("after_delivery", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_line_item", "after_delivery")
    op.drop_column("order_index", "paid_by_delivery_piastres")
    op.drop_column("order_index", "fulfilments")
