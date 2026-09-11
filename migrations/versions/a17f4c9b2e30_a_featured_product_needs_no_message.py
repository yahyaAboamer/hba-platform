"""a featured product needs no message

Revision ID: a17f4c9b2e30
Revises: c93f2a17d4e8
Create Date: 2026-09-12 01:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a17f4c9b2e30"
down_revision: Union[str, Sequence[str], None] = "c93f2a17d4e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """D12: the note beside a featured product is optional.

    The approved design shows a featured product as a card with the product's
    picture, and the note as something added when there is something extra to
    say - *before Thursday*, *mention the shade*. The column was `NOT NULL`,
    so featuring ten products for one campaign meant typing ten sentences that
    all said the same thing, which is how a message becomes noise a model
    stops reading.

    Additive: a column that accepted every existing value still accepts them.
    """
    op.alter_column(
        "product_feature_request", "message", existing_type=sa.Text(), nullable=True
    )


def downgrade() -> None:
    """Put the constraint back, and say what that costs.

    A request written without a note cannot exist under the old schema. Rather
    than delete it - which would silently un-feature a product somebody chose -
    the note becomes the one word that is true of every such row. **It is a
    placeholder, not something anybody wrote**, and that is the honest price
    of going backwards.
    """
    op.execute(
        "UPDATE product_feature_request SET message = 'Featured' WHERE message IS NULL"
    )
    op.alter_column(
        "product_feature_request", "message", existing_type=sa.Text(), nullable=False
    )
