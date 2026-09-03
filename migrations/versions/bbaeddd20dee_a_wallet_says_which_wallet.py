"""a wallet says which wallet

Vodafone Cash, Orange Money, Etisalat Cash and WE Pay all take the same
eleven-digit Egyptian mobile number, so the number alone does not say where a
transfer should go. Whoever sends it has been guessing from the prefix, and
prefixes have been portable in Egypt for years - so the guess is wrong often
enough to matter when the thing being guessed at is somebody's pay.

Nullable: every wallet destination recorded before this has no answer, and
inventing one would be worse than the guess it replaces.

Not a credential. It names a company, so `_VISIBLE` shows it in full.

Revision ID: bbaeddd20dee
Revises: 04e0ba7f4166
Create Date: 2026-09-03 15:20:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bbaeddd20dee"
down_revision: Union[str, Sequence[str], None] = "04e0ba7f4166"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the provider, and stop the append-only trigger counting columns."""
    op.add_column(
        "payout_destination",
        sa.Column("wallet_provider", sa.String(length=60), nullable=True),
    )

    # The trigger listed every column by name and position, so adding one made
    # `ROW(NEW.*)` and `ROW(OLD.id, ...)` different lengths and every UPDATE
    # died with "unequal number of entries in row expressions". The suite
    # caught it immediately, which is the only reason this is a footnote
    # rather than an outage.
    #
    # Rewritten to compare the rows as JSON with `superseded_at` removed.
    # Same rule - **only `superseded_at` may change** - and it no longer
    # depends on how many columns the table has or what order they are in, so
    # the next column to be added does not break it.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_payout_destination_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION
                    'payout_destination is append-only: a past payment must '
                    'always resolve where it was sent'
                    USING ERRCODE = 'restrict_violation';
            END IF;

            IF NEW.superseded_at IS NULL THEN
                RAISE EXCEPTION
                    'payout_destination.superseded_at cannot be cleared: '
                    'un-superseding would resurrect an old destination'
                    USING ERRCODE = 'restrict_violation';
            END IF;

            IF (to_jsonb(NEW) - 'superseded_at')
               IS DISTINCT FROM (to_jsonb(OLD) - 'superseded_at')
            THEN
                RAISE EXCEPTION
                    'payout_destination is append-only: only superseded_at may '
                    'change, and this statement changed something else'
                    USING ERRCODE = 'restrict_violation';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    """Drop it. No payment resolves through this column.

    The trigger is left on its JSON comparison: it is correct for the table
    with or without this column, and restoring the positional version would
    reintroduce the fragility for no gain.
    """
    op.drop_column("payout_destination", "wallet_provider")
