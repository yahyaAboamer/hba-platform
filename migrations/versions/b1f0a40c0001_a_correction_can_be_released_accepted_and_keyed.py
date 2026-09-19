"""a correction can be released, accepted, and keyed

Batch 1 follow-up, R1 and R2.

**Two more kinds of adjustment, and a name for one decision.**

`release` un-applies the part of a carried correction that its destination
month could not take once that month was agreed. `accepted` records that HBA
absorbed a difference on a month nothing was sent for, without touching what
is still owed. Both are append-only rows like every other adjustment; neither
edits or deletes anything.

`operation_key` gives one decision one identity, so the same request arriving
twice is one row rather than two recoveries. It is nullable and unique -
Postgres treats NULLs as distinct - so every row written before this exists
keeps working untouched.

Revision ID: b1f0a40c0001
Revises: a17f4c9b2e30
Create Date: 2026-09-19 21:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b1f0a40c0001"
down_revision: Union[str, Sequence[str], None] = "a17f4c9b2e30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payroll_adjustment",
        sa.Column("operation_key", sa.String(length=80), nullable=True),
    )
    op.create_unique_constraint(
        "payroll_adjustment_operation_key_unique",
        "payroll_adjustment",
        ["operation_key"],
    )
    op.create_index(
        "payroll_adjustment_destination_idx",
        "payroll_adjustment",
        ["destination_payroll_month_id"],
    )
    # The table is append-only by trigger, so the constraint is replaced rather
    # than relaxed in place: dropping and recreating a CHECK touches no rows.
    op.drop_constraint(
        "payroll_adjustment_type_valid", "payroll_adjustment", type_="check"
    )
    op.create_check_constraint(
        "payroll_adjustment_type_valid",
        "payroll_adjustment",
        "type IN ('credit', 'writeoff', 'correction', 'release', 'accepted')",
    )


def downgrade() -> None:
    # **Refuses rather than deletes.** Going back means the two new kinds
    # cannot be represented, and any row using one is a decision somebody
    # made about real money. Dropping them silently would lose it; the
    # operator is told to settle them first.
    conn = op.get_bind()
    stranded = conn.execute(
        sa.text(
            "SELECT count(*) FROM payroll_adjustment "
            "WHERE type IN ('release', 'accepted')"
        )
    ).scalar_one()
    if stranded:
        raise RuntimeError(
            f"{stranded} adjustment(s) are of a kind this downgrade removes. "
            "Resolve or export them before going back; this migration will "
            "not delete a record of money."
        )

    op.drop_constraint(
        "payroll_adjustment_type_valid", "payroll_adjustment", type_="check"
    )
    op.create_check_constraint(
        "payroll_adjustment_type_valid",
        "payroll_adjustment",
        "type IN ('credit', 'writeoff', 'correction')",
    )
    op.drop_index("payroll_adjustment_destination_idx", table_name="payroll_adjustment")
    op.drop_constraint(
        "payroll_adjustment_operation_key_unique",
        "payroll_adjustment",
        type_="unique",
    )
    op.drop_column("payroll_adjustment", "operation_key")
