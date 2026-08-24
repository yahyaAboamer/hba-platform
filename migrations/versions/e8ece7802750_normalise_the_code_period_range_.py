"""normalise the code period range expression

Revision ID: e8ece7802750
Revises: 53c97d980f4a
Create Date: 2026-08-24 21:51:09.968219

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8ece7802750'
down_revision: Union[str, Sequence[str], None] = '53c97d980f4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make both period tables use the same range expression.

    discount_code_period was created with the `%` operator; compensation_period
    uses `mod()`. They compute the same thing - `%` is the operator form of
    `mod` - so this changes no behaviour.

    It is worth a migration anyway. app/core/periods.py documents itself as
    holding *the* canonical expression that migrations copy, and with two
    different forms stored, that claim was false for one of the two tables.
    One definition, or none.

    `mod()` is the form that survives every path. A percent sign in DDL passed
    through SQLAlchemy's Computed() is escaped for the driver's parameter style
    and reaches Postgres as `%%`, which is not an operator - that is what forced
    the change.

    The column must be dropped and rebuilt, because a generated expression
    cannot be altered in place, and the exclusion constraint depends on it. Both
    tables are empty at the time of writing; on a populated table this would
    rewrite it.
    """
    op.execute(
        "ALTER TABLE discount_code_period "
        "DROP CONSTRAINT discount_code_period_no_overlap"
    )
    op.execute("ALTER TABLE discount_code_period DROP COLUMN effective_range")
    op.execute(
        """
        ALTER TABLE discount_code_period
        ADD COLUMN effective_range daterange
        GENERATED ALWAYS AS (daterange(
        make_date(left(start_month, 4)::int, right(start_month, 2)::int, 1),
        CASE WHEN end_month IS NULL THEN NULL
             ELSE make_date(
                 right(end_month, 2)::int / 12 + left(end_month, 4)::int,
                 mod(right(end_month, 2)::int, 12) + 1,
                 1
             )
        END,
        '[)'
    )) STORED
        """
    )
    op.execute(
        """
        ALTER TABLE discount_code_period
        ADD CONSTRAINT discount_code_period_no_overlap
        EXCLUDE USING gist (code WITH =, effective_range WITH &&)
        """
    )


def downgrade() -> None:
    """Back to the operator form. Same computation either way."""
    op.execute(
        "ALTER TABLE discount_code_period "
        "DROP CONSTRAINT discount_code_period_no_overlap"
    )
    op.execute("ALTER TABLE discount_code_period DROP COLUMN effective_range")
    op.execute(
        """
        ALTER TABLE discount_code_period
        ADD COLUMN effective_range daterange
        GENERATED ALWAYS AS (daterange(
            make_date(left(start_month, 4)::int, right(start_month, 2)::int, 1),
            CASE WHEN end_month IS NULL THEN NULL
                 ELSE make_date(
                     right(end_month, 2)::int / 12 + left(end_month, 4)::int,
                     right(end_month, 2)::int % 12 + 1,
                     1
                 )
            END,
            '[)'
        )) STORED
        """
    )
    op.execute(
        """
        ALTER TABLE discount_code_period
        ADD CONSTRAINT discount_code_period_no_overlap
        EXCLUDE USING gist (code WITH =, effective_range WITH &&)
        """
    )
