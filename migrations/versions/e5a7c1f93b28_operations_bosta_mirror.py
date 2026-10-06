"""the Bosta mirror Operations counts from

ADR 0057, the Bosta tab. `ops_bosta_delivery` mirrors every order HBA has on
Bosta - tracking number, type, state, when it was created, collected from
HBA and had its airway bill printed, Bosta's "waiting for HBA" flag and the
Shopify order number - kept and upserted, never with the receiver's name,
phone, address, notes or cash. `ops_bosta_sync` is one row saying how far
back the mirror has read.

New tables only; nothing existing is touched. Downgrade drops both: the
mirror is rebuilt from Bosta by reading it again.

Revision ID: e5a7c1f93b28
Revises: d4f1b8e62a39
Create Date: 2026-10-06 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5a7c1f93b28"
down_revision: Union[str, Sequence[str], None] = "d4f1b8e62a39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ops_bosta_delivery",
        sa.Column("bosta_id", sa.String(length=40), nullable=False),
        sa.Column("tracking_number", sa.String(length=40), nullable=False),
        sa.Column("type_value", sa.String(length=60), nullable=False),
        sa.Column("state_code", sa.SmallInteger(), nullable=False),
        sa.Column("state_value", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_bosta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("awb_printed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "waiting_for_action", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("shopify_order_number", sa.String(length=60), nullable=True),
        sa.Column("unfinished", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("bosta_id"),
        sa.UniqueConstraint("tracking_number", name="ops_bosta_delivery_tracking_number"),
    )
    op.create_index("ix_ops_bosta_delivery_state_code", "ops_bosta_delivery", ["state_code"])
    op.create_index("ix_ops_bosta_delivery_created_at", "ops_bosta_delivery", ["created_at"])
    op.create_index("ix_ops_bosta_delivery_collected_at", "ops_bosta_delivery", ["collected_at"])
    op.create_table(
        "ops_bosta_sync",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("backfill_next", sa.Date(), nullable=True),
        sa.Column("high_water", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name="ops_bosta_sync_one_row"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("ops_bosta_sync")
    op.drop_index("ix_ops_bosta_delivery_collected_at", table_name="ops_bosta_delivery")
    op.drop_index("ix_ops_bosta_delivery_created_at", table_name="ops_bosta_delivery")
    op.drop_index("ix_ops_bosta_delivery_state_code", table_name="ops_bosta_delivery")
    op.drop_table("ops_bosta_delivery")
