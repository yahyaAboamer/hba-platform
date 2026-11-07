"""Production moves in (ADR 0069, ADR 0076).

Production's own tables, empty: its data arrives by the one-off import
(`scripts/production_import.py`) from the private export, and is reconciled
count by count. Nothing existing changes. Downgrading drops them, with
whatever Production holds by then.

It also lets a person hold Production's four levels (ADR 0076 decision 5):
`role_assignment_role_valid` and `invitation_role_valid` are rebuilt with
them, the lists written out here as earlier role revisions do. Downgrading
puts the old lists back `NOT VALID`, so an assignment already given stays
(and grants nothing to older code) instead of blocking the rollback.

Revision ID: d1b4f0a10025
Revises: c9e4a7d10024
Create Date: 2026-11-07 01:51:12.420965

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd1b4f0a10025'
down_revision: Union[str, Sequence[str], None] = 'c9e4a7d10024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BEFORE = (
    "'admin', 'affiliate', 'affiliate_manager', 'content_manager', 'customer_service', 'operations_manager'"
)
AFTER = (
    "'admin', 'affiliate', 'affiliate_manager', 'content_manager', 'customer_service', 'operations_manager', "
    "'production_manager', 'production_qc', 'production_staff', 'production_viewer'"
)
ROLE_CHECKS = (("role_assignment", "role_assignment_role_valid"), ("invitation", "invitation_role_valid"))


def upgrade() -> None:
    """Upgrade schema."""
    # Read on every sign-in: give up rather than queue sign-ins (as f2a6c4e80011).
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table, name in ROLE_CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"role IN ({AFTER})")
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
    op.create_table('production_supplier_category',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
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
    op.create_table('production_supplier',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('code', sa.String(length=80), nullable=False),
    sa.Column('name', sa.String(length=180), nullable=False),
    sa.Column('category_id', sa.String(length=80), nullable=True),
    sa.Column('contact_person', sa.String(length=180), nullable=True),
    sa.Column('phone', sa.String(length=180), nullable=True),
    sa.Column('whatsapp', sa.String(length=180), nullable=True),
    sa.Column('city', sa.String(length=180), nullable=True),
    sa.Column('payment_terms', sa.String(length=180), nullable=True),
    sa.Column('normal_lead_time_days', sa.Integer(), nullable=True),
    sa.Column('maximum_capacity', sa.Integer(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('services', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('legacy_position', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['category_id'], ['production_supplier_category.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
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


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table, name in ROLE_CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK (role IN ({BEFORE})) NOT VALID")
    op.drop_table('production_stage_update')
    op.drop_table('production_qc_check')
    op.drop_table('production_order_stage')
    op.drop_index('production_order_created', table_name='production_order')
    op.drop_table('production_order')
    op.drop_table('production_supplier')
    op.drop_index('production_document_record', table_name='production_document')
    op.drop_table('production_document')
    op.drop_index('production_activity_created', table_name='production_activity')
    op.drop_table('production_activity')
    op.drop_table('production_task')
    op.drop_table('production_supplier_category')
    op.drop_table('production_sample')
    op.drop_table('production_product')
    op.drop_table('production_phase')
    op.drop_table('production_fixture')
