"""Production tasks added by hand (ADR 0084, batch 2).

Revision ID: a7c4e9f20034
Revises: f6b3d8e10033
Create Date: 2026-11-14

Creates ``prod_task``: the tasks somebody types in on the Tasks screen. The
tasks the orders generate are never stored (they are worked out on every
read), so this table holds only the hand-added ones. Nothing old is touched.

Downgrade refuses while any task exists, rather than lose it; with none, it
drops the table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c4e9f20034"
down_revision: Union[str, Sequence[str], None] = "f6b3d8e10033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _user(name: str) -> sa.Column:
    return sa.Column(name, sa.Integer(), sa.ForeignKey("user_account.id", ondelete="SET NULL"))


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.create_table(
        "prod_task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("due_on", sa.Date()),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("prod_order.id")),
        sa.Column("note", sa.Text()),
        sa.Column("for_owner", sa.Boolean(), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True)),
        _user("done_by"),
        _user("created_by"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("char_length(title) BETWEEN 1 AND 200", name="prod_task_title_length"),
    )
    op.create_index("ix_prod_task_order", "prod_task", ["order_id"])


def downgrade() -> None:
    tasks = op.get_bind().execute(sa.text("SELECT count(*) FROM prod_task")).scalar_one()
    if tasks:
        raise RuntimeError(
            f"Refusing to downgrade: {tasks} production task(s) exist and would be lost. "
            "Keep this revision, or move them out first."
        )
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index("ix_prod_task_order", table_name="prod_task")
    op.drop_table("prod_task")
