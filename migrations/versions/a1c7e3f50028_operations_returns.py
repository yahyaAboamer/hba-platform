"""Operations → Returns, and Operations' viewer and staff levels (ADR 0079).

Revision ID: a1c7e3f50028
Revises: f8d4b1c30027
Create Date: 2026-11-10

Creates ``ops_refund``: one customer owed a refund, Khazenly's timeline for
it, and whether it was paid. It starts empty; the old Google Sheet is not
imported. Widens the role checks to take ``operations_viewer`` and
``operations_staff``.

Downgrade drops the table and narrows the checks. It refuses while anybody
holds, or is invited to, either new level, rather than take access away
silently.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1c7e3f50028"
down_revision: Union[str, Sequence[str], None] = "f8d4b1c30027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BEFORE = (
    "'admin', 'affiliate', 'affiliate_manager', 'content_manager', 'customer_service', 'operations_manager', "
    "'production_manager', 'production_staff', 'production_viewer'"
)
AFTER = (
    "'admin', 'affiliate', 'affiliate_manager', 'content_manager', 'customer_service', 'operations_manager', "
    "'operations_staff', 'operations_viewer', 'production_manager', 'production_staff', 'production_viewer'"
)
ROLE_CHECKS = (("role_assignment", "role_assignment_role_valid"), ("invitation", "invitation_role_valid"))


def upgrade() -> None:
    # Read on every sign-in: give up rather than queue sign-ins (as e3c5a9d20026).
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table, name in ROLE_CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"role IN ({AFTER})")

    op.create_table(
        "ops_refund",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("khazenly_number", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("merchant_order", sa.String(60)),
        sa.Column("order_number", sa.String(40)),
        sa.Column("customer_name", sa.String(120)),
        sa.Column("customer_phone", sa.String(30)),
        sa.Column("amount", sa.Numeric(12, 2)),
        sa.Column("method", sa.String(20)),
        sa.Column("refund_to", sa.String(200)),
        sa.Column("step", sa.String(80)),
        sa.Column("step_at", sa.DateTime(timezone=True)),
        sa.Column(
            "timeline",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("check_error", sa.String(200)),
        sa.Column("paid_on", sa.Date()),
        sa.Column("paid_recorded_at", sa.DateTime(timezone=True)),
        sa.Column("paid_by", sa.Integer(), sa.ForeignKey("user_account.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user_account.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("user_account.id", ondelete="SET NULL")),
        sa.UniqueConstraint("khazenly_number", name="ops_refund_khazenly_number"),
        sa.CheckConstraint("kind IN ('return', 'exchange')", name="ops_refund_kind_valid"),
        sa.CheckConstraint(
            "method IS NULL OR method IN ('instapay', 'vodafone_cash', 'bank_transfer', 'other')",
            name="ops_refund_method_valid",
        ),
        sa.CheckConstraint("amount IS NULL OR amount > 0", name="ops_refund_amount_positive"),
        sa.CheckConstraint(
            "(paid_on IS NULL) = (paid_recorded_at IS NULL)", name="ops_refund_paid_whole"
        ),
        sa.CheckConstraint(
            "paid_on IS NULL OR (received_at IS NOT NULL AND amount IS NOT NULL "
            "AND method IS NOT NULL AND refund_to IS NOT NULL)",
            name="ops_refund_paid_complete",
        ),
    )
    op.create_index("ix_ops_refund_paid_on", "ops_refund", ["paid_on"])
    op.create_index(
        "ix_ops_refund_waiting",
        "ops_refund",
        ["checked_at"],
        postgresql_where=sa.text("received_at IS NULL"),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    held = op.get_bind().execute(
        sa.text(
            "SELECT (SELECT count(*) FROM role_assignment WHERE revoked_at IS NULL "
            "AND role IN ('operations_viewer', 'operations_staff')) + "
            "(SELECT count(*) FROM invitation WHERE role IN ('operations_viewer', 'operations_staff') "
            "AND accepted_at IS NULL AND withdrawn_at IS NULL)"
        )
    ).scalar()
    if held:
        raise RuntimeError(
            f"{held} people hold or are invited to an Operations viewer or staff level; "
            "move them first, so nobody loses access without being told."
        )
    op.drop_index("ix_ops_refund_waiting", table_name="ops_refund")
    op.drop_index("ix_ops_refund_paid_on", table_name="ops_refund")
    op.drop_table("ops_refund")
    # Revoked rows and settled invitations of the new roles would fail the
    # narrowed check; they carry nothing live, so they are removed.
    op.execute("DELETE FROM role_assignment WHERE role IN ('operations_viewer', 'operations_staff')")
    op.execute("DELETE FROM invitation WHERE role IN ('operations_viewer', 'operations_staff')")
    for table, name in ROLE_CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"role IN ({BEFORE})")
