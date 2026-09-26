"""a model paid outside Egypt applies without a payout destination

Owner, 26 September: choosing *Outside Egypt* on the application must still
let her send it. Every destination the platform holds is Egyptian, so she
applies with none and this flag says why (ADR 0046).

Additive only: one boolean column, false for every existing row. Downgrade
drops it; nothing else reads it.

Revision ID: d7a2c4e10003
Revises: d4e7a2c90003
Create Date: 2026-09-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d7a2c4e10003"
down_revision: Union[str, Sequence[str], None] = "d4e7a2c90003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "affiliate_profile",
        sa.Column(
            "payout_abroad",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("affiliate_profile", "payout_abroad")
