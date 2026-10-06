"""the E-stebdal requests waiting for review

ADR 0057, the E-stebdal tab. `ops_estebdal_return` holds the return and
exchange requests whose status on E-stebdal is "Needs Review", as the last
clean read found them: E-stebdal's id, the request and order numbers, and
when it was requested. Every read replaces the whole set.

E-stebdal's answer also carries the customer's name, phone and address and
the items; none of it is stored. Nothing existing is touched; downgrade drops
the table, which the next read rebuilds within 5 minutes.

Revision ID: d4f1b8e62a39
Revises: c7e2a9d40b15
Create Date: 2026-10-06 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4f1b8e62a39"
down_revision: Union[str, Sequence[str], None] = "c7e2a9d40b15"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ops_estebdal_return",
        sa.Column("estebdal_id", sa.String(length=40), nullable=False),
        sa.Column("return_number", sa.String(length=40), nullable=False),
        sa.Column("order_number", sa.String(length=40), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("estebdal_id"),
    )


def downgrade() -> None:
    op.drop_table("ops_estebdal_return")
