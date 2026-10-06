"""the Bosta and E-stebdal keys saved from Settings

ADR 0057 §10. `ops_integration_key` holds a key saved from Settings for
Bosta or E-stebdal, encrypted with SETTINGS_ENCRYPTION_KEY as the Shopify
client secret is (ADR 0045): the Fernet token, its last four characters for
telling two keys apart, when it last answered, and who saved it. Without a
row the server's own variable (BOSTA_API_KEY, ESTEBDAL_API_KEY) is used.

A new table only. Downgrade drops it, and the server's variables are used
again.

Revision ID: f6b2d8a41c57
Revises: e5a7c1f93b28
Create Date: 2026-10-07 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6b2d8a41c57"
down_revision: Union[str, Sequence[str], None] = "e5a7c1f93b28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ops_integration_key",
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("hint", sa.String(length=8), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "provider IN ('bosta', 'estebdal')", name="ops_integration_key_provider_valid"
        ),
        sa.PrimaryKeyConstraint("provider"),
    )


def downgrade() -> None:
    op.drop_table("ops_integration_key")
