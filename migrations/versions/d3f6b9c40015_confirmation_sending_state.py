"""an order's confirmation can be "sending"

ADR 0059. The sender claims an order in a transaction of its own, just before
it asks WhatsApp, by moving it from `pending` to `sending`. A crash after
WhatsApp accepted the message then leaves the order `sending`, which is never
sent again on its own - somebody looks first.

`order_confirmation_state_valid` is rebuilt with the state in its list,
written out here rather than read from the models. No row is written or
moved. Downgrade restores the list without it and fails while a row is
`sending`, which is the point.

Revision ID: d3f6b9c40015
Revises: c2e5a8b30014
Create Date: 2026-10-11 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d3f6b9c40015"
down_revision: Union[str, Sequence[str], None] = "c2e5a8b30014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BEFORE = (
    "'pending', 'would_send', 'sent', 'failed', "
    "'not_needed', 'no_phone', 'bad_phone', 'no_whatsapp'"
)
AFTER = (
    "'pending', 'sending', 'would_send', 'sent', 'failed', "
    "'not_needed', 'no_phone', 'bad_phone', 'no_whatsapp'"
)

NAME = "order_confirmation_state_valid"


def _states(states: str) -> None:
    op.drop_constraint(NAME, "order_confirmation", type_="check")
    op.create_check_constraint(NAME, "order_confirmation", f"state IN ({states})")


def upgrade() -> None:
    # The engine writes to this table as orders arrive. Give up after five
    # seconds (and retry the deploy) rather than queue those writes behind a
    # lock for as long as some other transaction holds the table.
    op.execute("SET LOCAL lock_timeout = '5s'")
    _states(AFTER)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    _states(BEFORE)
