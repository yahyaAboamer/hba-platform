"""feedback follow-up: a record of every call, note and close

ADR 0087 (amends ADR 0083, decisions 4 and 6).

- `feedback_follow_up`: one row per thing done on an unhappy answer's
  follow-up - a call with no answer, a note, *Resolved* with what was agreed,
  *Couldn't reach* - and per thing the platform did on its own. Append-only:
  nothing edits or deletes a row. Indexed on `(survey_id, at)`.
- `feedback_survey` gains `follow_up_round` (0 upward) and
  `round_started_at`, what the waiting clock runs from, and `unreached_at` /
  `unreached_by` for a follow-up closed as *Couldn't reach*.

Backfill, so nothing already there reads blank:

- An unhappy answer's round is its `reopened_count` (each *No* started one),
  and the round started when she said *No* (`solved_at`) or, in round 0,
  when she gave her reason (`reason_at`), or else when she rated.
- A survey already resolved gets one `resolved` entry, with no note, at
  `resolved_at`, by `resolved_by`.

Downgrade refuses while the history holds anything a person wrote or did
(anything but the backfilled `resolved` entries) or a follow-up is closed as
*Couldn't reach*, rather than lose it; with none, it takes them away.

Revision ID: a7c1e2f30040
Revises: f1c2d3e40039
Create Date: 2026-11-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c1e2f30040"
down_revision: Union[str, Sequence[str], None] = "f1c2d3e40039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KINDS = (
    "('no_answer', 'note', 'resolved', 'unreached', "
    "'message_sent', 'message_failed', 'wrote_back', 'returned')"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.add_column(
        "feedback_survey",
        sa.Column("follow_up_round", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "feedback_survey_round_not_negative", "feedback_survey", "follow_up_round >= 0"
    )
    op.add_column("feedback_survey", sa.Column("round_started_at", sa.DateTime(timezone=True)))
    op.add_column("feedback_survey", sa.Column("unreached_at", sa.DateTime(timezone=True)))
    op.add_column(
        "feedback_survey",
        sa.Column(
            "unreached_by",
            sa.Integer(),
            sa.ForeignKey(
                "user_account.id", ondelete="SET NULL", name="feedback_survey_unreached_by_fkey"
            ),
        ),
    )

    op.create_table(
        "feedback_follow_up",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "survey_id",
            sa.Integer(),
            sa.ForeignKey("feedback_survey.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("user_account.id", ondelete="SET NULL")),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(f"kind IN {KINDS}", name="feedback_follow_up_kind_valid"),
        sa.CheckConstraint("round >= 0", name="feedback_follow_up_round_not_negative"),
    )
    op.create_index("feedback_follow_up_survey", "feedback_follow_up", ["survey_id", "at"])

    # Every unhappy answer is in the round its reopenings put it in, started
    # when the last one began.
    op.execute(
        """
        UPDATE feedback_survey
        SET follow_up_round = reopened_count,
            round_started_at = CASE
                WHEN reopened_count > 0 THEN coalesce(solved_at, reason_at, rated_at)
                ELSE coalesce(reason_at, rated_at)
            END
        WHERE rating = 'unhappy'
        """
    )
    # A follow-up resolved before the history existed still shows who did it.
    op.execute(
        """
        INSERT INTO feedback_follow_up (survey_id, round, kind, note, actor_id, at)
        SELECT id, reopened_count, 'resolved', NULL, resolved_by, resolved_at
        FROM feedback_survey
        WHERE resolved_at IS NOT NULL
        """
    )


#: What only this revision can hold, each with the words a refusal uses. The
#: backfilled ``resolved`` entries (no note) are rebuilt by the next upgrade.
_HELD = (
    (
        "SELECT count(*) FROM feedback_follow_up WHERE NOT (kind = 'resolved' AND note IS NULL)",
        "follow-up history entr(ies)",
    ),
    ("SELECT count(*) FROM feedback_survey WHERE unreached_at IS NOT NULL", "follow-up(s) closed as couldn't reach"),
)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    for query, words in _HELD:
        found = bind.execute(sa.text(query)).scalar_one()
        if found:
            raise RuntimeError(
                f"Refusing to downgrade: {found} {words} exist and would be lost. "
                "Keep this revision, or move them out first."
            )
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.drop_index("feedback_follow_up_survey", table_name="feedback_follow_up")
    op.drop_table("feedback_follow_up")
    op.drop_column("feedback_survey", "unreached_by")
    op.drop_column("feedback_survey", "unreached_at")
    op.drop_column("feedback_survey", "round_started_at")
    op.drop_constraint("feedback_survey_round_not_negative", "feedback_survey", type_="check")
    op.drop_column("feedback_survey", "follow_up_round")
