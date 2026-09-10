"""a request to feature a product

W09. One row per product, and deliberately nothing per model.

The rule lists what this must not become: *no model Done button,
acknowledgement, completion tracking or automatic target change.* A table with
a row per model per request is how it becomes those things, so there is not
one. Who sees a request is computed from her wardrobe when it is asked (W10),
because eligibility changes with current shipment state and a stored audience
would be wrong the moment a replacement shipped.

`visible` is a flag rather than a deletion because W09 asks for three verbs -
make visible, hide, remove - and hiding a request keeps its wording while
removing it does not.

Revision ID: a2f47b8e1c53
Revises: f1a93d6c48e2
Create Date: 2026-09-10 16:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2f47b8e1c53"
down_revision: Union[str, Sequence[str], None] = "f1a93d6c48e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_feature_request",
        sa.Column("shopify_product_id", sa.String(length=32), primary_key=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "visible", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "updated_by",
            sa.Integer(),
            sa.ForeignKey("user_account.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("product_feature_request")
