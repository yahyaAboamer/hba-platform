"""payout destination

Revision ID: e7f91548c3d9
Revises: e8ece7802750
Create Date: 2026-08-24 21:59:07.377955

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f91548c3d9'
down_revision: Union[str, Sequence[str], None] = 'e8ece7802750'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Where money is sent, append-only.

    Alembic writes the table. The append-only guards are added below, and they
    differ from every other append-only table here: this one permits exactly
    one update, the supersession stamp.
    """
    op.create_table('payout_destination',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('affiliate_id', sa.Integer(), nullable=False),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('instapay_address_url', sa.String(length=500), nullable=True),
    sa.Column('instapay_phone', sa.String(length=40), nullable=True),
    sa.Column('bank_name', sa.String(length=120), nullable=True),
    sa.Column('bank_account_holder', sa.String(length=200), nullable=True),
    sa.Column('bank_account_number', sa.String(length=64), nullable=True),
    sa.Column('wallet_phone', sa.String(length=40), nullable=True),
    sa.Column('approved_by', sa.Integer(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('superseded_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("method IN ('bank', 'instapay', 'wallet')", name='payout_destination_method_valid'),
    sa.ForeignKeyConstraint(['affiliate_id'], ['affiliate_profile.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['approved_by'], ['user_account.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('payout_destination_affiliate_idx', 'payout_destination', ['affiliate_id'], unique=False)
    op.create_index('payout_destination_current_idx', 'payout_destination', ['affiliate_id'], unique=False, postgresql_where=sa.text('superseded_at IS NULL'))
    # ### end Alembic commands ###

    # Append-only, with one deliberate exception.
    #
    # Every other append-only table reuses reject_mutation() and refuses UPDATE
    # outright. This one cannot: superseding a destination *is* an update, and
    # it is what makes the history a history rather than a pile of rows with no
    # order.
    #
    # So the trigger permits a change to superseded_at and refuses everything
    # else. Without that narrowness the exception would be a loophole: an
    # UPDATE could set superseded_at and quietly repoint the address in the
    # same statement.
    #
    # It also refuses clearing superseded_at, because un-superseding would
    # resurrect an old destination as the current one - two current
    # destinations, or the wrong one.
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

            IF ROW(NEW.*) IS DISTINCT FROM
               ROW(OLD.id, OLD.affiliate_id, OLD.method,
                   OLD.instapay_address_url, OLD.instapay_phone,
                   OLD.bank_name, OLD.bank_account_holder,
                   OLD.bank_account_number, OLD.wallet_phone,
                   OLD.approved_by, OLD.approved_at, OLD.created_at,
                   NEW.superseded_at)
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
    op.execute(
        """
        CREATE TRIGGER payout_destination_append_only
        BEFORE UPDATE OR DELETE ON payout_destination
        FOR EACH ROW EXECUTE FUNCTION reject_payout_destination_mutation();
        """
    )
    # A row-level trigger does not fire on TRUNCATE - verified in Phase 1 -
    # so without this one statement would erase every destination silently.
    op.execute(
        """
        CREATE TRIGGER payout_destination_no_truncate
        BEFORE TRUNCATE ON payout_destination
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DROP TRIGGER IF EXISTS payout_destination_no_truncate ON payout_destination"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS payout_destination_append_only ON payout_destination"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_payout_destination_mutation()")
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('payout_destination_current_idx', table_name='payout_destination', postgresql_where=sa.text('superseded_at IS NULL'))
    op.drop_index('payout_destination_affiliate_idx', table_name='payout_destination')
    op.drop_table('payout_destination')
    # ### end Alembic commands ###
