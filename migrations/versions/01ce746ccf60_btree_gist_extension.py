"""btree gist extension

Revision ID: 01ce746ccf60
Revises: b66a237ed72f
Create Date: 2026-08-24 21:05:49.317934

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '01ce746ccf60'
down_revision: Union[str, Sequence[str], None] = 'b66a237ed72f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable btree_gist, which every effective-dated period depends on.

    A gist exclusion constraint can compare ranges out of the box. It cannot
    compare a plain integer - so `affiliate_id WITH =` is not something Postgres
    will accept until this extension exists, and every period table would fail
    to migrate.

    Separated into its own migration because it is a database-level capability
    rather than a table: it is installed once and then assumed by Tasks 3 and 4.
    """
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")


def downgrade() -> None:
    # Only drops if nothing depends on it, which is the behaviour we want: a
    # period table still standing means this is still needed.
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
