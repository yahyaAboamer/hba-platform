"""append only guards

Revision ID: c16349c64e62
Revises: 3b20c2882d2f
Create Date: 2026-08-23 00:20:00.512140

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c16349c64e62'
down_revision: Union[str, Sequence[str], None] = '3b20c2882d2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make append-only tables physically append-only.

    reject_mutation() is written once here and reused by every append-only
    table added in later phases: payment_transaction, payment_allocation,
    payroll_snapshot.

    Two triggers are needed, not one. A row-level BEFORE UPDATE OR DELETE
    trigger does NOT fire on TRUNCATE - verified against Postgres - so without
    the statement-level guard a single TRUNCATE would erase the whole audit
    trail silently.
    """
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'append-only table: % cannot be modified by %',
                TG_TABLE_NAME, lower(TG_OP)
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_event_no_update_or_delete
        BEFORE UPDATE OR DELETE ON audit_event
        FOR EACH ROW EXECUTE FUNCTION reject_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_event_no_truncate
        BEFORE TRUNCATE ON audit_event
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_event_no_truncate ON audit_event;")
    op.execute("DROP TRIGGER IF EXISTS audit_event_no_update_or_delete ON audit_event;")
    op.execute("DROP FUNCTION IF EXISTS reject_mutation();")
