"""a notice somebody has chosen to stop seeing

Revision ID: c93f2a17d4e8
Revises: 1c4b06a5f8d2
Create Date: 2026-09-11 01:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c93f2a17d4e8"
down_revision: Union[str, Sequence[str], None] = "1c4b06a5f8d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Where a muted notice is remembered.

    A10 asks for three different things and only this one needs storing: a
    **temporary hide** lives in the browser and comes back, **resolving** the
    issue stops the notice being generated at all, and a **mute** has to
    outlive the tab it was clicked in.

    Keyed by the notice's own key, so a mute follows the *kind* of problem
    rather than a row that may not exist tomorrow. Not an audit table - it is
    a preference, and it says who set it so the reason can be asked for.
    """
    op.create_table(
        "notice_mute",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column(
            "muted_by",
            sa.Integer(),
            sa.ForeignKey("user_account.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "muted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("notice_mute")
