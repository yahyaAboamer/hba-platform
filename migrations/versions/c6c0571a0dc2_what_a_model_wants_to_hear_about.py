"""what a model wants to hear about

Two kinds of message, and a row only where somebody has turned one **off**.

There is deliberately no row for the default. "Absence means on" is then a
property of the schema rather than a convention somebody has to remember to
seed - and the alternative, writing a row per model per kind at sign-up, is a
migration that silently mutes anybody it misses.

Revision ID: c6c0571a0dc2
Revises: bbaeddd20dee
Create Date: 2026-09-03 15:34:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6c0571a0dc2"
down_revision: Union[str, Sequence[str], None] = "bbaeddd20dee"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """One row per affiliate per kind, and only where it is off."""
    op.create_table(
        "notification_preference",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "affiliate_id",
            sa.Integer(),
            sa.ForeignKey("affiliate_profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("affiliate_id", "kind", name="notification_preference_unique"),
    )


def downgrade() -> None:
    """Drop it. Every model goes back to hearing about both, which is the
    default this table only ever departs from."""
    op.drop_table("notification_preference")
