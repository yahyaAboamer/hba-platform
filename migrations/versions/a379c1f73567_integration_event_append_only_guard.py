"""integration event append only guard

Revision ID: a379c1f73567
Revises: eca106cab1f7
Create Date: 2026-08-23 16:48:40.957664

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a379c1f73567'
down_revision: Union[str, Sequence[str], None] = 'eca106cab1f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make integration_event physically append-only.

    Reuses reject_mutation(), written in c16349c64e62 for audit_event.

    Two triggers, not one. A row-level BEFORE UPDATE OR DELETE trigger does not
    fire on TRUNCATE, so without the statement-level guard a single TRUNCATE
    would erase every receipt silently.
    """
    op.execute(
        """
        CREATE TRIGGER integration_event_no_update_or_delete
        BEFORE UPDATE OR DELETE ON integration_event
        FOR EACH ROW EXECUTE FUNCTION reject_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER integration_event_no_truncate
        BEFORE TRUNCATE ON integration_event
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS integration_event_no_truncate ON integration_event;"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS integration_event_no_update_or_delete "
        "ON integration_event;"
    )
