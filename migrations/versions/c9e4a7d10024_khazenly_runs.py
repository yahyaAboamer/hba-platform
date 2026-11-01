"""Khazenly runs: each bulk-confirm file built, with its summary (ADR 0072)

One new table, `ops_khazenly_run`, owned by Operations. Orders are stored
by number only. Nothing existing is changed.

Downgrade drops the table and with it the history of runs; nothing else
depends on it.

Revision ID: c9e4a7d10024
Revises: b2d7f4a10023
Create Date: 2026-11-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c9e4a7d10024"
down_revision: Union[str, Sequence[str], None] = "b2d7f4a10023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ops_khazenly_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "built_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "built_by",
            sa.Integer(),
            sa.ForeignKey("user_account.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("shopify_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rows_read", sa.Integer(), nullable=False),
        sa.Column("stated_count", sa.Integer(), nullable=True),
        sa.Column("skipped_rows", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("confirmed", sa.Integer(), nullable=False),
        sa.Column("not_confirmed", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=80), nullable=True),
        sa.Column("confirmed_orders", postgresql.JSONB(), nullable=False),
        sa.Column("left_out", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_ops_khazenly_run_built_at", "ops_khazenly_run", ["built_at"])


def downgrade() -> None:
    op.drop_index("ix_ops_khazenly_run_built_at", table_name="ops_khazenly_run")
    op.drop_table("ops_khazenly_run")
