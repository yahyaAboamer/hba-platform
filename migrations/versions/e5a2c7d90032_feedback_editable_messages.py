"""post-delivery feedback: the wording can be edited

ADR 0083. One new column, nothing else.

- `feedback_settings.messages`: the wording an admin has changed, as
  `{message key: text}` (JSONB). Only what was changed is kept: a message that
  is not in it says its built-in words. Every existing row starts empty, so
  nothing a customer is sent changes until somebody edits it.

Downgrade drops the column. Any wording an admin saved is lost, and the
messages go back to the built-in words of the older code.

Revision ID: e5a2c7d90032
Revises: d4f1b6c80031
Create Date: 2026-11-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5a2c7d90032"
down_revision: Union[str, Sequence[str], None] = "d4f1b6c80031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "feedback_settings",
        sa.Column(
            "messages",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("feedback_settings", "messages")
