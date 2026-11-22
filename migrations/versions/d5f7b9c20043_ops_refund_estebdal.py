"""Operations → Returns: marking the refund received in E-stebdal (ADR 0090).

Revision ID: d5f7b9c20043
Revises: c4e6a8b10042
Create Date: 2026-11-22

Seven columns on ``ops_refund``, all empty or defaulted, and one partial
index for the rows due to be sent. ``estebdal_notify`` is true for new rows
and set false here on every row already paid: those are sent without the
customer email (ADR 0090, decision 4).

Downgrade drops the columns, and with them the record of which refunds were
marked received in E-stebdal. E-stebdal itself keeps them received.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "d5f7b9c20043"
down_revision: Union[str, Sequence[str], None] = "c4e6a8b10042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DUE = "paid_on IS NOT NULL AND received_at IS NOT NULL AND estebdal_state IS DISTINCT FROM 'done'"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("ops_refund", sa.Column("estebdal_state", sa.String(10)))
    op.add_column("ops_refund", sa.Column("estebdal_note", sa.String(200)))
    op.add_column(
        "ops_refund",
        sa.Column("estebdal_choices", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column("ops_refund", sa.Column("estebdal_request", sa.String(40)))
    op.add_column("ops_refund", sa.Column("estebdal_tried_at", sa.DateTime(timezone=True)))
    op.add_column("ops_refund", sa.Column("estebdal_done_at", sa.DateTime(timezone=True)))
    op.add_column(
        "ops_refund",
        sa.Column("estebdal_notify", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_check_constraint(
        "ops_refund_estebdal_state_valid",
        "ops_refund",
        "estebdal_state IS NULL OR estebdal_state IN ('waiting', 'choose', 'missing', 'refused', 'done')",
    )
    op.create_index(
        "ix_ops_refund_estebdal_due",
        "ops_refund",
        ["estebdal_tried_at"],
        postgresql_where=sa.text(DUE),
    )
    # Paid before this: sent without the email, weeks late (decision 4).
    op.execute("UPDATE ops_refund SET estebdal_notify = false WHERE paid_on IS NOT NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_ops_refund_estebdal_due", table_name="ops_refund")
    op.drop_constraint("ops_refund_estebdal_state_valid", "ops_refund", type_="check")
    for column in (
        "estebdal_notify",
        "estebdal_done_at",
        "estebdal_tried_at",
        "estebdal_request",
        "estebdal_choices",
        "estebdal_note",
        "estebdal_state",
    ):
        op.drop_column("ops_refund", column)
