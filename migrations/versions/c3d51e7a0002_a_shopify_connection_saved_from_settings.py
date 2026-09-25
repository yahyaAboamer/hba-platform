"""a Shopify connection saved from Settings

Owner, decision b (25 September): the connection is edited in Settings, as
the approved export draws it. One row at most; the client secret is stored
encrypted and never read back out.

Additive only: a new table, nothing else touched. Downgrade drops it, and the
platform falls back to the environment's connection, which is what it used
before this revision.

Revision ID: c3d51e7a0002
Revises: b1f0a40c0001
Create Date: 2026-09-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d51e7a0002"
down_revision: Union[str, Sequence[str], None] = "b1f0a40c0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shopify_connection",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shop_domain", sa.String(length=255), nullable=False),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("client_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("shop_name", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("id = 1", name="shopify_connection_single_row"),
    )


def downgrade() -> None:
    op.drop_table("shopify_connection")
