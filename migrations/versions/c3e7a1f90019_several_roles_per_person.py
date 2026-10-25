"""several roles per person, and the department of each audit entry

ADR 0067, decisions 1 and 7. A person may now hold several roles at once, and
what they may do is everything their live roles grant together.

- **The operations manager's Inbox becomes a second assignment.** Until now
  `operations_manager` granted `inbox.use` itself (ADR 0059). From this
  revision the code's `operations_manager` grants only `order_ops.view`, so
  every person holding the role live is given a `customer_service`
  assignment here. `granted_by` is left empty: nobody granted it - this
  migration moved access the person already had, without changing it. The
  same people can do exactly the same things before and after.
- `role_assignment_one_live_role_per_person`: a partial unique index, so one
  person cannot hold the same role twice at once. The one-operations-manager
  index stays as it is.
- `audit_event.department`: an empty column, filled from here on by
  `record_audit`. No existing entry is touched - the table is append-only.

**Refused, rather than guessed at, while anybody holds two live roles.**
Before this revision the newest live assignment was a person's whole access,
and any older live one was ignored. Reading roles together would quietly
widen such a person's access, so the upgrade stops and names them; somebody
decides which assignment is real and revokes the other first. The old code
never leaves that state behind, so on a healthy database nothing is refused.

**Downgrade** removes the `customer_service` assignments this upgrade made
(live, `granted_by` empty, on a person holding `operations_manager` live),
drops the index and the column. It too is refused while anybody still holds
two live roles: the old code would see only the newest of them, so a person
given a second role since would silently lose the first. An entry's
department is lost with the column; the entries themselves are not.

Revision ID: c3e7a1f90019
Revises: a6c9e3f70018
Create Date: 2026-10-25 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c3e7a1f90019"
down_revision: Union[str, Sequence[str], None] = "a6c9e3f70018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ONE_LIVE_ROLE = "role_assignment_one_live_role_per_person"


def _refuse_two_live_roles(when: str) -> None:
    op.execute(
        f"""
        DO $$
        DECLARE
            people text;
        BEGIN
            SELECT string_agg(user_account_id::text, ', ' ORDER BY user_account_id)
              INTO people
              FROM (
                SELECT user_account_id
                  FROM role_assignment
                 WHERE revoked_at IS NULL
                 GROUP BY user_account_id
                HAVING count(*) > 1
              ) AS several;
            IF people IS NOT NULL THEN
                RAISE EXCEPTION
                    'These accounts hold more than one live role: %. {when}',
                    people;
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    # `role_assignment` is read on every request. Give up after five seconds
    # (and retry the deploy) rather than queue sign-ins behind a lock for as
    # long as some other transaction holds the table.
    op.execute("SET LOCAL lock_timeout = '5s'")

    _refuse_two_live_roles(
        "Until now only the newest counted; revoke the one that should not, "
        "then upgrade."
    )

    # ADR 0067: the operations manager's Inbox, moved from inside his role to
    # an assignment of its own. granted_by stays empty - this is the same
    # access he already had, moved by this migration, not given by anybody.
    op.execute(
        """
        INSERT INTO role_assignment (user_account_id, role, granted_by)
        SELECT user_account_id, 'customer_service', NULL
          FROM role_assignment
         WHERE role = 'operations_manager' AND revoked_at IS NULL
        """
    )

    op.create_index(
        ONE_LIVE_ROLE,
        "role_assignment",
        ["user_account_id", "role"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    # Nullable, no default: adding it rewrites no row of the append-only trail.
    op.add_column("audit_event", sa.Column("department", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.drop_column("audit_event", "department")
    op.drop_index(ONE_LIVE_ROLE, table_name="role_assignment")

    # Exactly what the upgrade added: the operations manager's own Inbox
    # assignment, which the old code's `operations_manager` grants by itself.
    op.execute(
        """
        DELETE FROM role_assignment AS inbox
         WHERE inbox.role = 'customer_service'
           AND inbox.revoked_at IS NULL
           AND inbox.granted_by IS NULL
           AND EXISTS (
                SELECT 1 FROM role_assignment AS ops
                 WHERE ops.user_account_id = inbox.user_account_id
                   AND ops.role = 'operations_manager'
                   AND ops.revoked_at IS NULL
           )
        """
    )

    _refuse_two_live_roles(
        "The old code reads only the newest; take the extra roles away first, "
        "then downgrade."
    )
