"""staff preferences: Settings → Appearance's two switches

The approved export's *Show pop-up notices on Home* and *Weekly reminder to
record achieved content* (Admin lines 749-757, 3600-3611), saved per staff
account so they survive a reload and a different device. A row exists only
once somebody turns a switch off: absence means on, as the export's defaults.

Additive only: a new table, nothing else touched. Downgrade drops it, and
every switch reads as on again - which is what the platform did before this
revision (it had no switches).

Revision ID: d4e7a2c90003
Revises: c3d51e7a0002
Create Date: 2026-09-25 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e7a2c90003"
down_revision: Union[str, Sequence[str], None] = "c3d51e7a0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "staff_preference",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_account_id",
            sa.Integer(),
            sa.ForeignKey("user_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_account_id", "key", name="staff_preference_unique"),
        sa.CheckConstraint(
            "key IN ('home_notices', 'weekly_targets_reminder')",
            name="staff_preference_key_valid",
        ),
    )


def downgrade() -> None:
    op.drop_table("staff_preference")
