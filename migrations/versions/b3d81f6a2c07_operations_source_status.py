"""how each operations source was last read

ADR 0057 §6. `ops_source_status` keeps one row per source the operations
dashboard reads (Shopify, Bosta, E-stebdal): when it was last tried, when it
last read cleanly, the plain-words reason the latest read failed, and whether
there was a key to read with at all. Every number Operations shows carries
this, so a number is never shown without its time and a failure is never
shown as 0.

A new table; nothing existing is touched. Downgrade drops it - it holds
nothing that is not read again within 5 minutes.

Revision ID: b3d81f6a2c07
Revises: f2a6c4e80011
Create Date: 2026-10-05 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3d81f6a2c07"
down_revision: Union[str, Sequence[str], None] = "f2a6c4e80011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ops_source_status",
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("connected", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "source IN ('shopify', 'bosta', 'estebdal')", name="ops_source_status_source_valid"
        ),
        sa.PrimaryKeyConstraint("source"),
    )


def downgrade() -> None:
    op.drop_table("ops_source_status")
