"""post-delivery feedback: the survey table and its settings

ADR 0083. Two new tables and nothing else; no existing table is touched.

- `feedback_survey`: one row per delivered order that was asked, or decided
  not to be (with the reason). It is the guard against a second question
  (`shopify_order_id` is unique), and it carries the customer's answers and
  the follow-up an unhappy answer is owed. It holds a phone, a first name and
  product titles, so, like the rest of the inbox, nothing outside the inbox
  reads it.
- `feedback_settings`: one row at most. `started_at` is when the feature
  first ran switched on, so nothing delivered earlier is ever asked.

The settings row is made by the code on first use, not here.

Downgrade drops both, **and every answer in them**. Take a dump first once
the feature has been switched on.

Revision ID: c3e9a5b70030
Revises: b2d8f4a60029
Create Date: 2026-11-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3e9a5b70030"
down_revision: Union[str, Sequence[str], None] = "b2d8f4a60029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATES = "('pending', 'would_send', 'sending', 'sent', 'no_whatsapp', 'failed', 'skipped')"
RATINGS = "('loved', 'okay', 'unhappy')"
REORDERS = "('very_likely', 'maybe', 'unlikely')"
STEPS = "('rating', 'reason', 'comment', 'support', 'solved', 'reorder', 'done')"


def upgrade() -> None:
    op.create_table(
        "feedback_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_url", sa.Text(), nullable=True),
        sa.Column("reply_hours", sa.Integer(), server_default="24", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("id = 1", name="feedback_settings_single_row"),
        sa.CheckConstraint("reply_hours > 0", name="feedback_settings_reply_hours_positive"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "feedback_survey",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shopify_order_id", sa.String(length=64), nullable=False),
        sa.Column("order_name", sa.String(length=40), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("courier", sa.String(length=80), nullable=True),
        sa.Column("products", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("customer_name", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=12), server_default="pending", nullable=False),
        sa.Column("skip_reason", sa.String(length=40), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.Column("wa_message_id", sa.String(length=200), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rating", sa.String(length=10), nullable=True),
        sa.Column("rated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=20), nullable=True),
        sa.Column("reason_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("comment_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reorder", sa.String(length=12), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("solved_asked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("solved", sa.Boolean(), nullable=True),
        sa.Column("solved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reopened_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("code", sa.String(length=40), nullable=True),
        sa.Column("code_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("code_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("code_order_name", sa.String(length=40), nullable=True),
        sa.Column("step", sa.String(length=10), server_default="rating", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(f"state IN {STATES}", name="feedback_survey_state_valid"),
        sa.CheckConstraint(f"rating IS NULL OR rating IN {RATINGS}", name="feedback_survey_rating_valid"),
        sa.CheckConstraint(f"reorder IS NULL OR reorder IN {REORDERS}", name="feedback_survey_reorder_valid"),
        sa.CheckConstraint(f"step IN {STEPS}", name="feedback_survey_step_valid"),
        sa.CheckConstraint("attempts >= 0", name="feedback_survey_attempts_not_negative"),
        sa.CheckConstraint("reopened_count >= 0", name="feedback_survey_reopened_not_negative"),
        sa.ForeignKeyConstraint(["conversation_id"], ["inbox_conversation.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by"], ["user_account.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shopify_order_id"),
        sa.UniqueConstraint("wa_message_id"),
    )
    op.create_index(
        "feedback_survey_due", "feedback_survey", ["next_attempt_at"],
        unique=False, postgresql_where=sa.text("state = 'pending'"),
    )
    op.create_index("feedback_survey_phone", "feedback_survey", ["phone", "created_at"], unique=False)
    op.create_index(
        "feedback_survey_follow_up", "feedback_survey", ["rated_at"],
        unique=False, postgresql_where=sa.text("rating = 'unhappy' AND step = 'support'"),
    )
    op.create_index(
        "feedback_survey_delivered", "feedback_survey",
        [sa.literal_column("delivered_at DESC NULLS LAST"), sa.literal_column("id DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("feedback_survey_delivered", table_name="feedback_survey")
    op.drop_index(
        "feedback_survey_follow_up", table_name="feedback_survey",
        postgresql_where=sa.text("rating = 'unhappy' AND step = 'support'"),
    )
    op.drop_index("feedback_survey_phone", table_name="feedback_survey")
    op.drop_index(
        "feedback_survey_due", table_name="feedback_survey",
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.drop_table("feedback_survey")
    op.drop_table("feedback_settings")
