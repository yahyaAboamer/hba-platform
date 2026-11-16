"""Production starts from zero (ADR 0085).

Revision ID: e5b9a3d70038
Revises: d4a8f2c60037
Create Date: 2026-11-16

Drops the old framed Production app's eleven tables, children first:
``production_stage_update``, ``production_order_stage``, ``production_qc_check``,
``production_order``, ``production_product``, ``production_phase``,
``production_activity``, ``production_document``, ``production_task``,
``production_sample`` and ``production_fixture``. Their records are taken to a
backup file before this runs, in each environment (ADR 0085, decision 3); this
migration does not copy them anywhere.

Kept, untouched: ``production_supplier`` and ``production_supplier_category``
(the suppliers are the new Suppliers list), and every ``prod_*`` table with the
foreign keys it holds to ``production_supplier``. None of the dropped tables is
referenced by a kept one (only the other way round), so nothing kept is altered.
The audit log is not touched.

Downgrade recreates the eleven tables **empty**, exactly as ``d1b4f0a10025``
made them; the records come back only from the backup file.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5b9a3d70038"
down_revision: Union[str, Sequence[str], None] = "d4a8f2c60037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Children first: each table below is dropped before the ones it points at.
OLD_TABLES = (
    "production_stage_update",
    "production_order_stage",
    "production_qc_check",
    "production_order",
    "production_product",
    "production_phase",
    "production_activity",
    "production_document",
    "production_task",
    "production_sample",
    "production_fixture",
)


def upgrade() -> None:
    """Upgrade schema."""
    # Give up rather than queue behind a long query on the supplier table.
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table in OLD_TABLES:
        op.drop_table(table)  # its indexes and foreign keys go with it


def downgrade() -> None:
    """Downgrade schema: the old tables again, empty."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('production_fixture',
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('production_phase',
    sa.Column('id', sa.String(length=120), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('production_product',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('style_code', sa.String(length=120), nullable=False),
    sa.Column('name', sa.String(length=180), nullable=False),
    sa.Column('category', sa.String(length=120), nullable=True),
    sa.Column('collection', sa.String(length=120), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=True),
    sa.Column('gsm', sa.Integer(), nullable=True),
    sa.Column('target_production_cost_piastres', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('production_sample',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('name', sa.String(length=180), nullable=False),
    sa.Column('material', sa.String(length=180), nullable=True),
    sa.Column('priority', sa.String(length=20), nullable=True),
    sa.Column('progress', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('stage', sa.String(length=40), nullable=True),
    sa.Column('latest_progress', sa.Text(), nullable=True),
    sa.Column('updated_at_source', sa.Date(), nullable=True),
    sa.Column('next_step', sa.Text(), nullable=True),
    sa.Column('deadline', sa.Date(), nullable=True),
    sa.Column('owner', sa.String(length=120), nullable=True),
    sa.Column('supplier', sa.String(length=180), nullable=True),
    sa.Column('approved_by', sa.String(length=120), nullable=True),
    sa.Column('approval_date', sa.Date(), nullable=True),
    sa.Column('manufacturing_notes', sa.Text(), nullable=True),
    sa.Column('updates', sa.Integer(), nullable=False),
    sa.Column('done_override', sa.Boolean(), nullable=True),
    sa.Column('done_override_by', sa.String(length=120), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('production_task',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('name', sa.String(length=180), nullable=False),
    sa.Column('supplier', sa.String(length=180), nullable=True),
    sa.Column('supplier_type', sa.String(length=80), nullable=True),
    sa.Column('stage', sa.String(length=100), nullable=True),
    sa.Column('next_action', sa.Text(), nullable=True),
    sa.Column('owner', sa.String(length=120), nullable=True),
    sa.Column('action_date', sa.Date(), nullable=True),
    sa.Column('deadline', sa.Date(), nullable=True),
    sa.Column('progress', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('priority', sa.String(length=20), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('confirmed_by', sa.String(length=120), nullable=True),
    sa.Column('legacy_position', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('production_activity',
    sa.Column('id', sa.String(length=120), nullable=False),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('module', sa.String(length=60), nullable=True),
    sa.Column('record_id', sa.String(length=180), nullable=True),
    sa.Column('old_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['user_account.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('production_activity_created', 'production_activity', ['created_at'], unique=False)
    op.create_table('production_document',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('document_type', sa.String(length=80), nullable=False),
    sa.Column('storage_key', sa.String(length=400), nullable=False),
    sa.Column('mime_type', sa.String(length=120), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('module', sa.String(length=80), nullable=False),
    sa.Column('record_id', sa.String(length=180), nullable=False),
    sa.Column('confidential', sa.Boolean(), nullable=False),
    sa.Column('uploaded_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['uploaded_by_id'], ['user_account.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('production_document_record', 'production_document', ['module', 'record_id'], unique=False)
    op.create_table('production_order',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('code', sa.String(length=80), nullable=False),
    sa.Column('product_id', sa.String(length=80), nullable=False),
    sa.Column('collection', sa.String(length=120), nullable=True),
    sa.Column('color', sa.String(length=80), nullable=True),
    sa.Column('tracker_order_number', sa.Integer(), nullable=True),
    sa.Column('tracker_model', sa.String(length=180), nullable=True),
    sa.Column('fabric', sa.String(length=180), nullable=True),
    sa.Column('fabric_kg', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('size_breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('total_ordered_quantity', sa.Integer(), nullable=False),
    sa.Column('actual_accepted_quantity', sa.Integer(), nullable=True),
    sa.Column('progress_percentage', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('current_stage_name', sa.String(length=120), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=True),
    sa.Column('priority', sa.String(length=20), nullable=True),
    sa.Column('target_unit_cost_piastres', sa.BigInteger(), nullable=False),
    sa.Column('target_total_cost_piastres', sa.BigInteger(), nullable=False),
    sa.Column('actual_total_cost_piastres', sa.BigInteger(), nullable=False),
    sa.Column('target_delivery_date', sa.Date(), nullable=True),
    sa.Column('planned_start_date', sa.Date(), nullable=True),
    sa.Column('planned_completion_date', sa.Date(), nullable=True),
    sa.Column('forecast_completion_date', sa.Date(), nullable=True),
    sa.Column('actual_completion_date', sa.Date(), nullable=True),
    sa.Column('delay_days', sa.Integer(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('blocking_reason', sa.Text(), nullable=True),
    sa.Column('cpo_approval_status', sa.String(length=40), nullable=True),
    sa.Column('main_manufacturer_id', sa.String(length=80), nullable=True),
    sa.Column('phase_id', sa.String(length=120), nullable=True),
    sa.Column('legacy_position', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['main_manufacturer_id'], ['production_supplier.id'], ),
    sa.ForeignKeyConstraint(['phase_id'], ['production_phase.id'], ),
    sa.ForeignKeyConstraint(['product_id'], ['production_product.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_index('production_order_created', 'production_order', ['created_at'], unique=False)
    op.create_table('production_order_stage',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('order_id', sa.String(length=80), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('supplier_id', sa.String(length=80), nullable=True),
    sa.Column('planned_start', sa.Date(), nullable=True),
    sa.Column('planned_finish', sa.Date(), nullable=True),
    sa.Column('forecast_finish', sa.Date(), nullable=True),
    sa.Column('planned_lead_time_days', sa.Integer(), nullable=False),
    sa.Column('input_quantity', sa.Integer(), nullable=False),
    sa.Column('completed_quantity', sa.Integer(), nullable=False),
    sa.Column('accepted_quantity', sa.Integer(), nullable=False),
    sa.Column('rejected_quantity', sa.Integer(), nullable=False),
    sa.Column('rework_quantity', sa.Integer(), nullable=False),
    sa.Column('progress_percentage', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['production_order.id'], ),
    sa.ForeignKeyConstraint(['supplier_id'], ['production_supplier.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('production_qc_check',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('order_id', sa.String(length=80), nullable=False),
    sa.Column('step', sa.String(length=40), nullable=False),
    sa.Column('item', sa.Integer(), nullable=False),
    sa.Column('result', sa.String(length=20), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('checked_by', sa.String(length=120), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['production_order.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('order_id', 'step', 'item', name='production_qc_check_one')
    )
    op.create_table('production_stage_update',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('stage_id', sa.String(length=80), nullable=False),
    sa.Column('supplier_id', sa.String(length=80), nullable=True),
    sa.Column('proposed_status', sa.String(length=40), nullable=False),
    sa.Column('quantity_completed', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('rejected_quantity', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('expected_completion_date', sa.String(length=10), nullable=True),
    sa.Column('delay_expected', sa.Boolean(), nullable=False),
    sa.Column('delay_reason', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('review_status', sa.String(length=20), nullable=False),
    sa.Column('submitted_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['stage_id'], ['production_order_stage.id'], ),
    sa.ForeignKeyConstraint(['submitted_by_id'], ['user_account.id'], ),
    sa.ForeignKeyConstraint(['supplier_id'], ['production_supplier.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
