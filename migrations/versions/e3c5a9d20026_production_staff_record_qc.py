"""Production staff also record QC; Production QC is no longer a role (ADR 0077).

Revision ID: e3c5a9d20026
Revises: d1b4f0a10025
Create Date: 2026-11-07

Anyone holding Production QC, or invited to it, is moved to Production staff,
which now records QC checks. A live QC row beside a live staff or manager row
is revoked instead (a person never holds one role twice). Then the role checks
are narrowed so Production QC cannot be given again. On the day it shipped
nobody held or was invited to Production QC on staging or production.

Downgrade widens the checks again; it cannot tell which staff were once QC.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e3c5a9d20026"
down_revision: Union[str, Sequence[str], None] = "d1b4f0a10025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WITH_QC = (
    "'admin', 'affiliate', 'affiliate_manager', 'content_manager', 'customer_service', 'operations_manager', "
    "'production_manager', 'production_qc', 'production_staff', 'production_viewer'"
)
WITHOUT_QC = (
    "'admin', 'affiliate', 'affiliate_manager', 'content_manager', 'customer_service', 'operations_manager', "
    "'production_manager', 'production_staff', 'production_viewer'"
)
ROLE_CHECKS = (("role_assignment", "role_assignment_role_valid"), ("invitation", "invitation_role_valid"))


def upgrade() -> None:
    # Read on every sign-in: give up rather than queue sign-ins (as d1b4f0a10025).
    op.execute("SET LOCAL lock_timeout = '5s'")
    # Already staff or manager: the QC row is revoked, not doubled.
    op.execute(
        """
        UPDATE role_assignment AS qc SET revoked_at = now()
        WHERE qc.role = 'production_qc' AND qc.revoked_at IS NULL
          AND EXISTS (
            SELECT 1 FROM role_assignment AS other
            WHERE other.user_account_id = qc.user_account_id AND other.revoked_at IS NULL
              AND other.role IN ('production_staff', 'production_manager')
          )
        """
    )
    op.execute("UPDATE role_assignment SET role = 'production_staff' WHERE role = 'production_qc'")
    op.execute("UPDATE invitation SET role = 'production_staff' WHERE role = 'production_qc'")
    for table, name in ROLE_CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"role IN ({WITHOUT_QC})")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table, name in ROLE_CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"role IN ({WITH_QC})")
