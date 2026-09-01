"""policy version append only guard

Revision ID: b7c4e1a92f30
Revises: 0cf0101323e5
Create Date: 2026-09-01 20:45:00.000000

Closing a gap in 0cf0101323e5, which created `policy_version` without the
guards its own plan promised it: *"Nothing is ever edited or deleted - a rule
change is a new row with a later effective_month, exactly the append-only
discipline every other money-adjacent table in this platform already holds
to."* The service layer offers no update or delete, so nothing in the app was
wrong - but nothing in the database said so either, and the discipline in this
project is that the database is what says so.

Checked rather than assumed, before writing this: `pg_trigger` on
`policy_version` returned nothing, an UPDATE of a version's text succeeded,
and a DELETE removed the row.

**Why it matters more here than the empty table suggests.** A policy version
is the platform's record of *what a model was told the rules were* when their
month was calculated. `payroll_snapshot.policy_version_id` has `ondelete
RESTRICT`, so a version some month depends on cannot be deleted - but RESTRICT
says nothing about the text, and rewriting `summary_markdown` in place changes
what an already-approved, already-paid month claims it was calculated under,
leaving no trace. That is precisely the harm every other guard here exists to
prevent.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c4e1a92f30'
down_revision: Union[str, Sequence[str], None] = '0cf0101323e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make policy_version physically append-only.

    Reuses reject_mutation(), written in c16349c64e62 for audit_event.

    Two triggers, not one, for the reason a379c1f73567 spells out: a row-level
    BEFORE UPDATE OR DELETE trigger does not fire on TRUNCATE, so without the
    statement-level guard one TRUNCATE erases the lot silently.
    """
    op.execute(
        """
        CREATE TRIGGER policy_version_no_update_or_delete
        BEFORE UPDATE OR DELETE ON policy_version
        FOR EACH ROW EXECUTE FUNCTION reject_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER policy_version_no_truncate
        BEFORE TRUNCATE ON policy_version
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS policy_version_no_truncate ON policy_version;"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS policy_version_no_update_or_delete "
        "ON policy_version;"
    )
