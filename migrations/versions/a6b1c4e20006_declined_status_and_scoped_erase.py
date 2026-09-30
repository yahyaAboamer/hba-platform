"""a declined status, and the append-only guards let one model be erased

ADR 0052 (owner, 29-30 September):

- `affiliate_profile.status` may be `declined`: an application turned down,
  which *Reconsider* can return to `pending`.
- The guards on `payout_destination` and `audit_event` refuse DELETE unless
  the transaction has set `hba.erasing_affiliate`, `hba.erasing_user` and
  `hba.erasing_subjects` locally, and then only for that model's rows. UPDATE and TRUNCATE stay
  refused. `audit_event` had the generic `reject_mutation()` shared with other
  tables, so it gets its own function rather than loosening theirs.

Catalogue changes only: a check constraint swapped and two trigger functions
replaced. No table rewrite.

Downgrade restores both guards to refusing every DELETE, and refuses to run
while any profile is `declined`, because the old check would reject the row.

Revision ID: a6b1c4e20006
Revises: f4a2b8d10005
Create Date: 2026-09-30 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a6b1c4e20006"
down_revision: Union[str, Sequence[str], None] = "f4a2b8d10005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUSES_NOW = "'active', 'archived', 'declined', 'inactive', 'pending'"
_STATUSES_BEFORE = "'active', 'archived', 'inactive', 'pending'"


def _payout_guard(delete_branch: str) -> str:
    """The destination guard, identical to `bbaeddd20dee` but for DELETE."""
    return f"""
        CREATE OR REPLACE FUNCTION reject_payout_destination_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                {delete_branch}
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


# Only the erasing transaction's own model. `current_setting(..., true)` is
# NULL when unset, and NULL never equals anything, so outside an erase this
# branch cannot return.
_PAYOUT_ERASE = """
                IF OLD.affiliate_id::text = current_setting('hba.erasing_affiliate', true) THEN
                    RETURN OLD;
                END IF;
"""


def upgrade() -> None:
    op.execute("ALTER TABLE affiliate_profile DROP CONSTRAINT affiliate_profile_status_valid")
    op.execute(
        "ALTER TABLE affiliate_profile ADD CONSTRAINT affiliate_profile_status_valid "
        f"CHECK (status IN ({_STATUSES_NOW}))"
    )

    op.execute(_payout_guard(_PAYOUT_ERASE))

    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_audit_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            -- ADR 0052: erasing a model removes the entries she made and the
            -- entries about her, in that transaction only.
            -- `hba.erasing_subjects` lists her subjects (affiliate:, user:
            -- and the invitation: rows sent to her), comma-separated.
            IF TG_OP = 'DELETE' AND (
                OLD.subject = ANY (
                    string_to_array(current_setting('hba.erasing_subjects', true), ',')
                )
                OR OLD.actor_id::text = current_setting('hba.erasing_user', true)
            ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION '% is append-only; % is not permitted',
                TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS audit_event_no_update_or_delete ON audit_event")
    op.execute(
        """
        CREATE TRIGGER audit_event_no_update_or_delete
        BEFORE UPDATE OR DELETE ON audit_event
        FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM affiliate_profile WHERE status = 'declined') THEN
                RAISE EXCEPTION
                    'Profiles are declined. Reconsider or archive them before '
                    'downgrading; the old status check would reject them.';
            END IF;
        END $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS audit_event_no_update_or_delete ON audit_event")
    op.execute(
        """
        CREATE TRIGGER audit_event_no_update_or_delete
        BEFORE UPDATE OR DELETE ON audit_event
        FOR EACH ROW EXECUTE FUNCTION reject_mutation();
        """
    )
    op.execute("DROP FUNCTION IF EXISTS reject_audit_event_mutation()")

    op.execute(_payout_guard(""))

    op.execute("ALTER TABLE affiliate_profile DROP CONSTRAINT affiliate_profile_status_valid")
    op.execute(
        "ALTER TABLE affiliate_profile ADD CONSTRAINT affiliate_profile_status_valid "
        f"CHECK (status IN ({_STATUSES_BEFORE}))"
    )
