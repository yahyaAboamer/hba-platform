"""an order keeps what it was placed at

Shopify zeroes an order's `current*` totals when it is cancelled. The platform
stores those, correctly - §9.3 pays commission on what the customer actually
paid - and the consequence reached a model's screen: a cancelled order printed
a struck-through E£0.00, because the figure the screen wanted no longer existed
anywhere in the database.

These two columns keep the order as it was placed, for display only.

**Nullable on purpose.** Every row indexed before this migration has no answer,
and a zero default would be indistinguishable from an order that was genuinely
free. `NULL` means *we never asked Shopify for this*, which is the truth until
a re-import fills it in.

**Never read by `calculate.py`.** Paying on these would pay for parcels that
were cancelled.

Revision ID: 04e0ba7f4166
Revises: e0d115c57f7e
Create Date: 2026-09-03 15:07:37.796684

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "04e0ba7f4166"
down_revision: Union[str, Sequence[str], None] = "e0d115c57f7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the placed-at totals."""
    op.add_column(
        "order_index",
        sa.Column("original_subtotal_piastres", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "order_index",
        sa.Column("original_total_piastres", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    """Drop them again. No commission figure depends on either."""
    op.drop_column("order_index", "original_total_piastres")
    op.drop_column("order_index", "original_subtotal_piastres")
