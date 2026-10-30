"""indexes for what Today reads every 30 seconds

Phase 2, Batch 2.2. Three indexes, nothing else:

- `order_confirmation (conversation_id, created_at, id)`: a conversation's
  latest answer, which Chats' "Wants a change" and Today ask of every
  conversation;
- `ops_bosta_delivery (shopify_order_number)`: which of a week's orders Bosta
  holds;
- `order_index (placed_at)`: the last seven days' orders.

No data is written or moved and no query changes its answer. Downgrade drops
the three indexes and loses nothing but speed.

Revision ID: b2d7f4a10023
Revises: a8c4e2f10022
Create Date: 2026-10-30 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b2d7f4a10023"
down_revision: Union[str, Sequence[str], None] = "a8c4e2f10022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "order_confirmation_conversation_latest",
        "order_confirmation",
        ["conversation_id", "created_at", "id"],
    )
    op.create_index(
        "ix_ops_bosta_delivery_shopify_order_number",
        "ops_bosta_delivery",
        ["shopify_order_number"],
    )
    op.create_index("order_index_placed_at_idx", "order_index", ["placed_at"])


def downgrade() -> None:
    op.drop_index("order_index_placed_at_idx", table_name="order_index")
    op.drop_index("ix_ops_bosta_delivery_shopify_order_number", table_name="ops_bosta_delivery")
    op.drop_index("order_confirmation_conversation_latest", table_name="order_confirmation")
