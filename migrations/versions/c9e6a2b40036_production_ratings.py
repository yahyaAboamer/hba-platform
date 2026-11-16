"""Production ratings: one supplier's stars on one settled order (ADR 0084, batch 6a).

Revision ID: c9e6a2b40036
Revises: b8d5f1a30035
Create Date: 2026-11-15

Creates ``prod_rating``: for one order and one supplier that worked on it, the
owner's quality, timing and dealing stars (1 to 5) and an optional note. One row
per order and supplier (edited in place; there is no delete). Nothing old is
altered.

Downgrade refuses while any rating exists, rather than lose the owner's
judgements; with none, it drops the table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9e6a2b40036"
down_revision: Union[str, Sequence[str], None] = "b8d5f1a30035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _user(name: str) -> sa.Column:
    return sa.Column(name, sa.Integer(), sa.ForeignKey("user_account.id", ondelete="SET NULL"))


def _now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "prod_rating",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("prod_order.id"), nullable=False),
        sa.Column("supplier_id", sa.String(80), sa.ForeignKey("production_supplier.id"), nullable=False),
        sa.Column("quality", sa.SmallInteger(), nullable=False),
        sa.Column("timing", sa.SmallInteger(), nullable=False),
        sa.Column("dealing", sa.SmallInteger(), nullable=False),
        sa.Column("note", sa.Text()),
        _user("created_by"),
        _now("created_at"),
        _user("updated_by"),
        _now("updated_at"),
        sa.UniqueConstraint("order_id", "supplier_id", name="prod_rating_once"),
        sa.CheckConstraint("quality BETWEEN 1 AND 5", name="prod_rating_quality_range"),
        sa.CheckConstraint("timing BETWEEN 1 AND 5", name="prod_rating_timing_range"),
        sa.CheckConstraint("dealing BETWEEN 1 AND 5", name="prod_rating_dealing_range"),
        sa.CheckConstraint("note IS NULL OR char_length(note) <= 1000", name="prod_rating_note_length"),
    )
    op.create_index("ix_prod_rating_supplier", "prod_rating", ["supplier_id"])


def downgrade() -> None:
    bind = op.get_bind()
    count = bind.execute(sa.text("SELECT count(*) FROM prod_rating")).scalar_one()
    if count:
        raise RuntimeError(
            f"Refusing to downgrade: {count} supplier rating(s) exist and would be lost. "
            "Keep this revision, or move them out first."
        )
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index("ix_prod_rating_supplier", table_name="prod_rating")
    op.drop_table("prod_rating")
