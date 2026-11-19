"""Production: product details, task follow-up, payments with several photos.

Revision ID: f1c2d3e40039
Revises: e5b9a3d70038
Create Date: 2026-11-19

Build contract ``docs/plans/2026-11-19-production-product-tasks-payments-build.md``.

* ``prod_order`` gains four nullable product details: ``colour_code``,
  ``fabric_type``, ``decoration_type`` and ``decoration_width_cm`` (above 0, at
  most 999.9).
* ``prod_order_file`` gains ``kind`` (``pattern`` | ``size_chart`` | null).
* ``prod_task`` gains ``next_action`` (at most 500 characters), and the new
  ``prod_task_update`` holds each follow-up line on a task; rows are never edited.
* A payment may hold several photos: the partial unique index
  ``uq_prod_supplier_receipt_live`` goes, and a plain index on ``entry_id``
  takes its place. ``prod_supplier_entry`` (append-only) is not touched.

Only columns, a table and indexes are added; nothing is dropped but that one
index. Downgrade refuses while anything only this revision can hold exists (a
task update or next action, a product detail, a file's kind, a payment with more
than one live photo), rather than lose it; with none, it takes them away.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1c2d3e40039"
down_revision: Union[str, Sequence[str], None] = "e5b9a3d70038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.add_column("prod_order", sa.Column("colour_code", sa.String(40)))
    op.add_column("prod_order", sa.Column("fabric_type", sa.String(120)))
    op.add_column("prod_order", sa.Column("decoration_type", sa.String(120)))
    op.add_column("prod_order", sa.Column("decoration_width_cm", sa.Numeric(6, 1)))
    op.create_check_constraint(
        "prod_order_decoration_width_range",
        "prod_order",
        "decoration_width_cm IS NULL OR (decoration_width_cm > 0 AND decoration_width_cm <= 999.9)",
    )

    op.add_column("prod_order_file", sa.Column("kind", sa.String(12)))
    op.create_check_constraint(
        "prod_order_file_kind_valid", "prod_order_file", "kind IS NULL OR kind IN ('pattern', 'size_chart')"
    )

    op.add_column("prod_task", sa.Column("next_action", sa.Text()))
    op.create_check_constraint(
        "prod_task_next_action_length",
        "prod_task",
        "next_action IS NULL OR char_length(next_action) BETWEEN 1 AND 500",
    )
    op.create_table(
        "prod_task_update",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("prod_task.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("next_action", sa.Text()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user_account.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("char_length(text) BETWEEN 1 AND 2000", name="prod_task_update_text_length"),
        sa.CheckConstraint(
            "next_action IS NULL OR char_length(next_action) BETWEEN 1 AND 500",
            name="prod_task_update_next_action_length",
        ),
    )
    op.create_index("ix_prod_task_update_task", "prod_task_update", ["task_id"])

    op.drop_index("uq_prod_supplier_receipt_live", table_name="prod_supplier_receipt")
    op.create_index("ix_prod_supplier_receipt_entry", "prod_supplier_receipt", ["entry_id"])


#: What only this revision can hold, each with the words a refusal uses.
_HELD = (
    ("SELECT count(*) FROM prod_task_update", "task update(s)"),
    ("SELECT count(*) FROM prod_task WHERE next_action IS NOT NULL", "task next action(s)"),
    (
        "SELECT count(*) FROM prod_order WHERE colour_code IS NOT NULL OR fabric_type IS NOT NULL "
        "OR decoration_type IS NOT NULL OR decoration_width_cm IS NOT NULL",
        "production order(s) with product details",
    ),
    ("SELECT count(*) FROM prod_order_file WHERE kind IS NOT NULL", "pattern file(s) or size chart(s)"),
    (
        "SELECT count(*) FROM (SELECT entry_id FROM prod_supplier_receipt WHERE deleted_at IS NULL "
        "GROUP BY entry_id HAVING count(*) > 1) AS many",
        "payment(s) with more than one photo",
    ),
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

    op.drop_index("ix_prod_supplier_receipt_entry", table_name="prod_supplier_receipt")
    op.create_index(
        "uq_prod_supplier_receipt_live", "prod_supplier_receipt", ["entry_id"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.drop_index("ix_prod_task_update_task", table_name="prod_task_update")
    op.drop_table("prod_task_update")
    op.drop_constraint("prod_task_next_action_length", "prod_task", type_="check")
    op.drop_column("prod_task", "next_action")

    op.drop_constraint("prod_order_file_kind_valid", "prod_order_file", type_="check")
    op.drop_column("prod_order_file", "kind")

    op.drop_constraint("prod_order_decoration_width_range", "prod_order", type_="check")
    for column in ("decoration_width_cm", "decoration_type", "fabric_type", "colour_code"):
        op.drop_column("prod_order", column)
