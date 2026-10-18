"""where an answer was given, and the tags Shopify really has

ADR 0063. The team tags an order Confirmed, Edit or Cancelled in Shopify
after calling the customer; the platform now reads that back as the order's
answer. Three empty columns, so no row is rewritten:

- `answered_in`: `whatsapp`, `inbox` or `shopify`, checked. Empty for an
  answer from before this.
- `shopify_tags`, `tags_read_at`: the platform's own tags as Shopify last had
  them on the order, and when that was read.

Downgrade drops them. An answer read from Shopify stays the order's answer,
without saying where it came from.

Revision ID: a6c9e3f70018
Revises: f5b8d2e60017
Create Date: 2026-10-18 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a6c9e3f70018"
down_revision: Union[str, Sequence[str], None] = "f5b8d2e60017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "order_confirmation"
ANSWERED_IN_VALID = "order_confirmation_answered_in_valid"


def upgrade() -> None:
    # The engine writes to this table as orders arrive. Give up after five
    # seconds (and retry the deploy) rather than queue those writes behind a
    # lock for as long as some other transaction holds the table.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(TABLE, sa.Column("answered_in", sa.String(8)))
    op.create_check_constraint(
        ANSWERED_IN_VALID,
        TABLE,
        "answered_in IS NULL OR answered_in IN ('whatsapp', 'inbox', 'shopify')",
    )
    op.add_column(TABLE, sa.Column("shopify_tags", sa.String(160)))
    op.add_column(TABLE, sa.Column("tags_read_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column(TABLE, "tags_read_at")
    op.drop_column(TABLE, "shopify_tags")
    op.drop_constraint(ANSWERED_IN_VALID, TABLE, type_="check")
    op.drop_column(TABLE, "answered_in")
