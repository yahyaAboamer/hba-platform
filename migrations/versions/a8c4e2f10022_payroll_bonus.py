"""a bonus HBA adds to a model's month

ADR 0070. One new table, `payroll_bonus`: an amount in whole pounds on one
payroll month, an optional staff-only reason, who added it, and who withdrew
it if it was taken back before the month was agreed.

No data is written or moved, and nothing existing changes: a month with no
bonus calculates exactly as it did. Downgrade drops the table, and nothing
stops it: **run it only before any bonus exists.** Dropping it after a bonus
has been agreed loses the record of why an agreed month is worth what it is.

Revision ID: a8c4e2f10022
Revises: e7b3d1f60021
Create Date: 2026-10-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a8c4e2f10022"
down_revision: Union[str, Sequence[str], None] = "e7b3d1f60021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_bonus",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "payroll_month_id",
            sa.Integer(),
            sa.ForeignKey("payroll_month.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount_piastres", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("operation_key", sa.String(80), nullable=True),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("user_account.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "withdrawn_by",
            sa.Integer(),
            sa.ForeignKey("user_account.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint("amount_piastres > 0", name="payroll_bonus_amount_positive"),
        sa.CheckConstraint(
            "amount_piastres % 100 = 0", name="payroll_bonus_whole_pounds"
        ),
        sa.UniqueConstraint("operation_key", name="payroll_bonus_operation_key_unique"),
    )
    op.create_index("payroll_bonus_month_idx", "payroll_bonus", ["payroll_month_id"])


def downgrade() -> None:
    op.drop_index("payroll_bonus_month_idx", table_name="payroll_bonus")
    op.drop_table("payroll_bonus")
