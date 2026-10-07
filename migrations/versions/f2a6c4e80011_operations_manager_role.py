"""the operations manager role, and only one at a time

ADR 0057. A new staff role, `operations_manager`, holding the operations
dashboard and nothing else.

- `role_assignment_role_valid` and `invitation_role_valid` are rebuilt with
  the role in their list. The lists are written out here rather than read
  from `app.core.permissions`, so this revision means the same thing however
  the code changes later.
- `role_assignment_one_operations_manager`: a partial unique index on the
  live (unrevoked) operations-manager assignment. One person holds the role
  at a time; the service refuses a second with the reason, and this is what
  holds when two invitations race.

No data is written or moved. Downgrade restores both lists without the role
and drops the index; it fails while an operations-manager row exists, which
is the point - the access would otherwise vanish without a trace.

Revision ID: f2a6c4e80011
Revises: e1a5c3b70010
Create Date: 2026-10-05 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f2a6c4e80011"
down_revision: Union[str, Sequence[str], None] = "e1a5c3b70010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BEFORE = "'admin', 'affiliate', 'affiliate_manager', 'content_manager'"
AFTER = "'admin', 'affiliate', 'affiliate_manager', 'content_manager', 'operations_manager'"


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
    op.create_index(
        "role_assignment_one_operations_manager",
        "role_assignment",
        ["role"],
        unique=True,
        postgresql_where=sa.text("role = 'operations_manager' AND revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("role_assignment_one_operations_manager", table_name="role_assignment")
    _roles(BEFORE)
