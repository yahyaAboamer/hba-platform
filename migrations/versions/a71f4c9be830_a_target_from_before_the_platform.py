"""a target from before the platform records an outcome, not counts

ADR 0036. The old dashboard kept whether a month's target was met. It did not
keep the video and story numbers, and it never will.

So a backfilled month carries `recorded_outcome` — *met* or *missed* — and no
requirements and no actuals at all. Inventing counts to reach a known outcome
would be fabricating evidence for a figure that decides money, and a model's
Targets card would draw a bar against a number nobody ever set.

The two shapes are kept apart by a check constraint rather than by convention:
a row has requirements and may have actuals, **or** it has an outcome and
neither. A row carrying both a requirement of 8 and an outcome of *met* invites
"met against what?" and has no answer.

`required_videos` and `required_stories` become nullable to allow it. That
nullability is the one risk in this migration — an absent requirement compares
as achieved in most naive readings — and the check constraint is what confines
it to rows that carry an outcome, where nothing compares anything.

Revision ID: a71f4c9be830
Revises: c6c0571a0dc2
Create Date: 2026-09-04 18:20:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a71f4c9be830"
down_revision: Union[str, Sequence[str], None] = "c6c0571a0dc2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "monthly_target",
        sa.Column("recorded_outcome", sa.String(length=8), nullable=True),
    )
    op.alter_column("monthly_target", "required_videos", nullable=True)
    op.alter_column("monthly_target", "required_stories", nullable=True)

    op.create_check_constraint(
        "monthly_target_outcome_valid",
        "monthly_target",
        "recorded_outcome IS NULL OR recorded_outcome IN ('met', 'missed')",
    )
    op.create_check_constraint(
        "monthly_target_counts_or_an_outcome_never_both",
        "monthly_target",
        "(recorded_outcome IS NULL"
        " AND required_videos IS NOT NULL"
        " AND required_stories IS NOT NULL)"
        " OR (recorded_outcome IS NOT NULL"
        " AND required_videos IS NULL"
        " AND required_stories IS NULL"
        " AND actual_videos IS NULL"
        " AND actual_stories IS NULL)",
    )

    # Verifying an outcome is verifying the whole of what was recorded, because
    # the outcome is the whole of what was recorded. The original wording asked
    # for actuals and would have refused every backfilled month.
    op.drop_constraint(
        "monthly_target_cannot_verify_the_unrecorded",
        "monthly_target",
        type_="check",
    )
    op.create_check_constraint(
        "monthly_target_cannot_verify_the_unrecorded",
        "monthly_target",
        "verified_at IS NULL "
        "OR actual_videos IS NOT NULL "
        "OR recorded_outcome IS NOT NULL",
    )


def downgrade() -> None:
    """Reversible only while no outcome has been recorded.

    A row with an outcome has no requirements to restore — the counts it
    replaced were never kept, so there is nothing to put back and inventing a
    zero would say *nothing was asked of her*. The `NOT NULL` below therefore
    fails loudly on such a row rather than filling one in, which is the correct
    direction for a downgrade nobody should be running against real history.
    """
    op.drop_constraint(
        "monthly_target_cannot_verify_the_unrecorded",
        "monthly_target",
        type_="check",
    )
    op.create_check_constraint(
        "monthly_target_cannot_verify_the_unrecorded",
        "monthly_target",
        "verified_at IS NULL OR actual_videos IS NOT NULL",
    )
    op.drop_constraint(
        "monthly_target_counts_or_an_outcome_never_both",
        "monthly_target",
        type_="check",
    )
    op.drop_constraint(
        "monthly_target_outcome_valid", "monthly_target", type_="check"
    )
    op.alter_column("monthly_target", "required_stories", nullable=False)
    op.alter_column("monthly_target", "required_videos", nullable=False)
    op.drop_column("monthly_target", "recorded_outcome")
