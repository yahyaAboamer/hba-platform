"""a retry identifies one payment

Revision ID: 1c4b06a5f8d2
Revises: a2f47b8e1c53
Create Date: 2026-09-10 14:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "1c4b06a5f8d2"
down_revision: Union[str, Sequence[str], None] = "a2f47b8e1c53"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Give new transfer records a durable, unique retry identity.

    Nullable preserves every append-only row recorded before 06A. The key is
    assigned only on INSERT; no historical transaction is rewritten.
    """
    op.add_column(
        "payment_transaction",
        sa.Column("operation_key", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "payment_transaction_operation_key_unique",
        "payment_transaction",
        ["operation_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "payment_transaction_operation_key_unique",
        "payment_transaction",
        type_="unique",
    )
    op.drop_column("payment_transaction", "operation_key")
