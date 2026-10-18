"""an order's message can be a payment request

ADR 0062. An international order that still owes money is sent a payment
link instead of the confirmation, in the same table so it keeps the
confirmation's guarantees: one row per order, claimed before sending.

Six columns, all either defaulted or empty, so no row is rewritten beyond
`kind` taking its default:

- `kind`: `confirmation` (every existing row) or `payment`, checked.
- `country`: where a payment request's order ships.
- `reminded_at`, `paid_at`: the one reminder, and when it was seen paid.
- `invoice_at`, `invoice_error`: Shopify asked to email the invoice, once.

Downgrade drops them, and fails while a payment request exists rather than
turn it silently into a confirmation that was never sent.

Revision ID: f5b8d2e60017
Revises: e4a7c1d50016
Create Date: 2026-10-18 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f5b8d2e60017"
down_revision: Union[str, Sequence[str], None] = "e4a7c1d50016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "order_confirmation"
KIND_VALID = "order_confirmation_kind_valid"


def upgrade() -> None:
    # The engine writes to this table as orders arrive. Give up after five
    # seconds (and retry the deploy) rather than queue those writes behind a
    # lock for as long as some other transaction holds the table.
    op.execute("SET LOCAL lock_timeout = '5s'")
    # A constant default: Postgres records it without rewriting the table.
    op.add_column(
        TABLE,
        sa.Column("kind", sa.String(12), nullable=False, server_default="confirmation"),
    )
    op.create_check_constraint(KIND_VALID, TABLE, "kind IN ('confirmation', 'payment')")
    op.add_column(TABLE, sa.Column("country", sa.String(2)))
    op.add_column(TABLE, sa.Column("reminded_at", sa.DateTime(timezone=True)))
    op.add_column(TABLE, sa.Column("paid_at", sa.DateTime(timezone=True)))
    op.add_column(TABLE, sa.Column("invoice_at", sa.DateTime(timezone=True)))
    op.add_column(TABLE, sa.Column("invoice_error", sa.String(300)))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM order_confirmation WHERE kind = 'payment') THEN
            RAISE EXCEPTION 'order_confirmation holds payment requests (ADR 0062); '
              'they would become confirmations that were never sent';
          END IF;
        END $$;
        """
    )
    for column in ("invoice_error", "invoice_at", "paid_at", "reminded_at", "country"):
        op.drop_column(TABLE, column)
    op.drop_constraint(KIND_VALID, TABLE, type_="check")
    op.drop_column(TABLE, "kind")
