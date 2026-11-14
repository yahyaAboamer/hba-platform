"""post-delivery feedback: an owner's test question

ADR 0083. One new column, nothing else.

- `feedback_survey.is_test`: true for a question an administrator sent to a
  number of his choosing to try the flow. It is never asked of a delivered
  order, never counted in the Feedback sheet, Today or the sidebar, and never
  stands in the way of a real question for the same phone. Every existing row
  is a real one, so the default is false.

Downgrade drops the column. A test survey that exists then becomes an
ordinary row: delete tests first (`DELETE FROM feedback_survey WHERE is_test`)
if the older code is to run.

Revision ID: d4f1b6c80031
Revises: c3e9a5b70030
Create Date: 2026-11-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4f1b6c80031"
down_revision: Union[str, Sequence[str], None] = "c3e9a5b70030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "feedback_survey",
        sa.Column("is_test", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("feedback_survey", "is_test")
