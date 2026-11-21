"""feedback follow-up: claim the "we tried to call you" message before sending

ADR 0088, decision 4.

`feedback_survey` gains `tried_claimed_round` and `tried_claimed_at`: the
round whose tried-to-call message was taken for sending, and when. The claim
is committed in a transaction of its own before WhatsApp is asked, so a crash
after WhatsApp took the message can never send it twice. Both are set or
neither (`feedback_survey_tried_claim_whole`).

Nothing to backfill: no claim exists before this revision. Downgrade drops
the two columns; a claim only matters for the ten minutes a send can take.

Revision ID: b3d5f7a90041
Revises: a7c1e2f30040
Create Date: 2026-11-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3d5f7a90041"
down_revision: Union[str, Sequence[str], None] = "a7c1e2f30040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("feedback_survey", sa.Column("tried_claimed_round", sa.Integer()))
    op.add_column("feedback_survey", sa.Column("tried_claimed_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "feedback_survey_tried_claim_whole",
        "feedback_survey",
        "(tried_claimed_round IS NULL) = (tried_claimed_at IS NULL)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint("feedback_survey_tried_claim_whole", "feedback_survey", type_="check")
    op.drop_column("feedback_survey", "tried_claimed_at")
    op.drop_column("feedback_survey", "tried_claimed_round")
