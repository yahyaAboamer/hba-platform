"""the customer service role

ADR 0059. A new staff role, `customer_service`, holding the customer inbox
and nothing else.

`role_assignment_role_valid` and `invitation_role_valid` are rebuilt with the
role in their list. The lists are written out here rather than read from
`app.core.permissions`, so this revision means the same thing however the
code changes later.

Any number of people may hold the role, so there is no index like the
operations manager's.

No data is written or moved. Downgrade restores both lists without the role;
it fails while a customer-service row exists, which is the point - the access
would otherwise vanish without a trace.

Revision ID: b1d4f7a20013
Revises: f6b2d8a41c57
Create Date: 2026-10-11 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b1d4f7a20013"
down_revision: Union[str, Sequence[str], None] = "f6b2d8a41c57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BEFORE = "'admin', 'affiliate', 'affiliate_manager', 'content_manager', 'operations_manager'"
AFTER = (
    "'admin', 'affiliate', 'affiliate_manager', 'content_manager', "
    "'customer_service', 'operations_manager'"
)


def _roles(roles: str) -> None:
    for table, name in (
        ("role_assignment", "role_assignment_role_valid"),
        ("invitation", "invitation_role_valid"),
    ):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"role IN ({roles})")


def upgrade() -> None:
    # Both tables are read on every sign-in. Rebuilding a constraint takes a
    # lock that queues every sign-in behind it while it waits; give up after
    # five seconds (and retry the deploy) rather than stall sign-ins for as
    # long as some other transaction holds the table.
    op.execute("SET LOCAL lock_timeout = '5s'")
    _roles(AFTER)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    _roles(BEFORE)
