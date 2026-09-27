"""what each ordered line was, by option: size, colour and the rest

Owner, 27 September (ADR 0050): an opened order shows each product with its
size. Shopify's `variantTitle` is only the option values run together ("XL",
or "M / Black"), and HBA's catalogue names its size option 32 different ways
("Size", "size", "Sizs", "T-shirt Size", "BLACK HBA CLUB PUMP COVER (Size)"),
so which value is the size is only known from the variant's
`selectedOptions` - name and value, as Shopify returns them.

Additive only: one nullable JSONB column, no default, no index, so no table
rewrite. NULL means *never read with options*; the hourly line-item sweep
fills it. `[]` means read, and the variant had none or no longer exists.
Downgrade drops it; the screen falls back to `variant_title`.

Revision ID: e3f1a9c70004
Revises: d7a2c4e10003
Create Date: 2026-09-27 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e3f1a9c70004"
down_revision: Union[str, Sequence[str], None] = "d7a2c4e10003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "order_line_item",
        sa.Column("selected_options", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_line_item", "selected_options")
