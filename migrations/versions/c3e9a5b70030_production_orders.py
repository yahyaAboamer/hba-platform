"""Production orders, as platform screens (ADR 0084, batch 1).

Revision ID: c3e9a5b70030
Revises: b2d8f4a60029
Create Date: 2026-11-14

Creates the ``prod_`` tables: the production order, its sizes, its ten
stages, the reasons a count dropped, the delivery-date history, the
factory's deliveries with Khazenly's counts, the order's files, and the
typical days per stage, seeded with the owner's first figures. No old
``production_*`` table is touched: the framed Production keeps working.

Downgrade refuses while any production order exists, rather than lose it;
with none, it drops the new tables.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3e9a5b70030"
down_revision: Union[str, Sequence[str], None] = "b2d8f4a60029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SIZES = "'XS', 'S', 'M', 'L', 'XL', 'XXL'"
STAGES = (
    "'plan', 'sample', 'materials', 'fabric_check', 'pattern_check', 'cutting', 'making', "
    "'final_inspection', 'warehouse', 'settle'"
)
STAGES_WITH_DAYS = (
    "'sample', 'materials', 'fabric_check', 'pattern_check', 'cutting', 'making', "
    "'final_inspection', 'warehouse', 'settle'"
)
PARTS = ("fabric", "manufacturing", "printing", "accessories", "packaging")

#: The owner's first figures (build plan, 14 November 2026); changed later
#: on the settings screen.
STAGE_DAYS = {
    "sample": 7,
    "materials": 7,
    "fabric_check": 2,
    "pattern_check": 3,
    "cutting": 2,
    "making": 17,
    "final_inspection": 1,
    "warehouse": 3,
    "settle": 7,
}

NEW_TABLES = (
    "prod_order_file",
    "prod_delivery_size",
    "prod_delivery",
    "prod_order_date_change",
    "prod_order_reason",
    "prod_order_stage",
    "prod_order_size",
    "prod_order",
    "prod_stage_days",
)


def _user(name: str) -> sa.Column:
    return sa.Column(name, sa.Integer(), sa.ForeignKey("user_account.id", ondelete="SET NULL"))


def _now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    stage_days = op.create_table(
        "prod_stage_days",
        sa.Column("stage", sa.String(20), primary_key=True),
        sa.Column("days", sa.Integer(), nullable=False),
        _now("updated_at"),
        _user("updated_by"),
        sa.CheckConstraint(f"stage IN ({STAGES_WITH_DAYS})", name="prod_stage_days_stage_valid"),
        sa.CheckConstraint("days BETWEEN 0 AND 365", name="prod_stage_days_days_range"),
    )
    op.bulk_insert(stage_days, [{"stage": stage, "days": days} for stage, days in STAGE_DAYS.items()])

    op.create_table(
        "prod_order",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("style_name", sa.String(180), nullable=False),
        sa.Column("colour", sa.String(80), nullable=False),
        sa.Column("shopify_product_id", sa.String(32)),
        sa.Column("factory_id", sa.String(80), sa.ForeignKey("production_supplier.id"), nullable=False),
        sa.Column("fabric_bought_by", sa.String(10), nullable=False),
        sa.Column("printing", sa.String(10), nullable=False),
        sa.Column("print_supplier_id", sa.String(80), sa.ForeignKey("production_supplier.id")),
        sa.Column("repeat_run", sa.Boolean(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("delivery_date", sa.Date(), nullable=False),
        *(sa.Column(f"target_{part}_piastres", sa.BigInteger(), nullable=False) for part in PARTS),
        *(sa.Column(f"actual_{part}_piastres", sa.BigInteger()) for part in PARTS),
        sa.Column("sample_status", sa.String(10), nullable=False),
        sa.Column("sample_note", sa.Text()),
        _user("sample_decided_by"),
        sa.Column("sample_decided_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("settled_payable_piastres", sa.BigInteger()),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        _user("settled_by"),
        sa.Column("notes", sa.Text()),
        _user("created_by"),
        _now("created_at"),
        _now("updated_at"),
        sa.UniqueConstraint("code", name="prod_order_code_unique"),
        sa.CheckConstraint("fabric_bought_by IN ('hba', 'factory')", name="prod_order_fabric_buyer_valid"),
        sa.CheckConstraint("printing IN ('factory', 'outside', 'none')", name="prod_order_printing_valid"),
        sa.CheckConstraint(
            "(printing = 'outside') = (print_supplier_id IS NOT NULL)", name="prod_order_print_supplier_when_outside"
        ),
        sa.CheckConstraint(
            "sample_status IN ('none', 'pending', 'approved', 'changes')", name="prod_order_sample_status_valid"
        ),
        sa.CheckConstraint("status IN ('open', 'closed', 'cancelled')", name="prod_order_status_valid"),
        sa.CheckConstraint(
            " AND ".join(f"target_{part}_piastres >= 0" for part in PARTS),
            name="prod_order_target_cost_not_negative",
        ),
        sa.CheckConstraint(
            " AND ".join(f"(actual_{part}_piastres IS NULL OR actual_{part}_piastres >= 0)" for part in PARTS),
            name="prod_order_actual_cost_not_negative",
        ),
        sa.CheckConstraint(
            "(settled_at IS NULL) = (settled_payable_piastres IS NULL)", name="prod_order_settlement_whole"
        ),
        sa.CheckConstraint("status <> 'closed' OR settled_at IS NOT NULL", name="prod_order_closed_is_settled"),
    )
    op.create_index("ix_prod_order_status", "prod_order", ["status"])

    op.create_table(
        "prod_order_size",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("prod_order.id"), nullable=False),
        sa.Column("size", sa.String(4), nullable=False),
        sa.Column("planned", sa.Integer(), nullable=False),
        sa.Column("cut", sa.Integer()),
        sa.Column("passed", sa.Integer()),
        sa.Column("to_fix", sa.Integer()),
        sa.Column("rejected", sa.Integer()),
        sa.UniqueConstraint("order_id", "size", name="prod_order_size_once"),
        sa.CheckConstraint(f"size IN ({SIZES})", name="prod_order_size_valid"),
        sa.CheckConstraint(
            "planned >= 0 AND (cut IS NULL OR cut >= 0) AND (passed IS NULL OR passed >= 0) "
            "AND (to_fix IS NULL OR to_fix >= 0) AND (rejected IS NULL OR rejected >= 0)",
            name="prod_order_size_not_negative",
        ),
    )

    op.create_table(
        "prod_order_stage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("prod_order.id"), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("expected_date", sa.Date()),
        sa.Column("done_on", sa.Date()),
        _user("done_by"),
        sa.Column("note", sa.Text()),
        sa.UniqueConstraint("order_id", "stage", name="prod_order_stage_once"),
        sa.CheckConstraint(f"stage IN ({STAGES})", name="prod_order_stage_valid"),
        sa.CheckConstraint("position BETWEEN 1 AND 10", name="prod_order_stage_position_range"),
        sa.CheckConstraint("status IN ('todo', 'done', 'skipped')", name="prod_order_stage_status_valid"),
        sa.CheckConstraint("(status = 'done') = (done_on IS NOT NULL)", name="prod_order_stage_done_has_date"),
    )

    op.create_table(
        "prod_order_reason",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("prod_order.id"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        _user("created_by"),
        _now("created_at"),
        sa.CheckConstraint("kind IN ('cut_short', 'rejected', 'to_fix')", name="prod_order_reason_kind_valid"),
        sa.CheckConstraint("quantity > 0", name="prod_order_reason_quantity_positive"),
    )
    op.create_index("ix_prod_order_reason_order", "prod_order_reason", ["order_id"])

    op.create_table(
        "prod_order_date_change",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("prod_order.id"), nullable=False),
        sa.Column("old_date", sa.Date()),
        sa.Column("new_date", sa.Date(), nullable=False),
        sa.Column("set_by", sa.String(10), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        _user("created_by"),
        _now("created_at"),
        sa.CheckConstraint("set_by IN ('owner', 'factory')", name="prod_order_date_change_set_by_valid"),
    )
    op.create_index("ix_prod_order_date_change_order", "prod_order_date_change", ["order_id"])

    op.create_table(
        "prod_delivery",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("prod_order.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("shipped_on", sa.Date(), nullable=False),
        sa.Column("counted_on", sa.Date()),
        sa.Column("mismatch_reason", sa.Text()),
        _user("created_by"),
        _now("created_at"),
        _now("updated_at"),
        sa.UniqueConstraint("order_id", "number", name="prod_delivery_number_once"),
        sa.CheckConstraint("number >= 1", name="prod_delivery_number_positive"),
        sa.CheckConstraint("kind IN ('finished', 'fix')", name="prod_delivery_kind_valid"),
        sa.CheckConstraint(
            "counted_on IS NULL OR counted_on >= shipped_on", name="prod_delivery_counted_after_shipped"
        ),
    )

    op.create_table(
        "prod_delivery_size",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("delivery_id", sa.Integer(), sa.ForeignKey("prod_delivery.id"), nullable=False),
        sa.Column("size", sa.String(4), nullable=False),
        sa.Column("shipped", sa.Integer(), nullable=False),
        sa.Column("counted", sa.Integer()),
        sa.UniqueConstraint("delivery_id", "size", name="prod_delivery_size_once"),
        sa.CheckConstraint(f"size IN ({SIZES})", name="prod_delivery_size_valid"),
        sa.CheckConstraint(
            "shipped >= 0 AND (counted IS NULL OR counted >= 0)", name="prod_delivery_size_not_negative"
        ),
    )

    op.create_table(
        "prod_order_file",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("prod_order.id"), nullable=False),
        sa.Column("stage", sa.String(20)),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(300), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        _user("uploaded_by"),
        _now("created_at"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(f"stage IS NULL OR stage IN ({STAGES})", name="prod_order_file_stage_valid"),
        sa.CheckConstraint("size_bytes >= 0", name="prod_order_file_size_not_negative"),
    )
    op.create_index("ix_prod_order_file_order", "prod_order_file", ["order_id"])


def downgrade() -> None:
    orders = op.get_bind().execute(sa.text("SELECT count(*) FROM prod_order")).scalar_one()
    if orders:
        raise RuntimeError(
            f"Refusing to downgrade: {orders} production order(s) exist and would be lost. "
            "Keep this revision, or move them out first."
        )
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index("ix_prod_order_file_order", table_name="prod_order_file")
    op.drop_index("ix_prod_order_date_change_order", table_name="prod_order_date_change")
    op.drop_index("ix_prod_order_reason_order", table_name="prod_order_reason")
    op.drop_index("ix_prod_order_status", table_name="prod_order")
    for table in NEW_TABLES:
        op.drop_table(table)
