"""The factory's own login (ADR 0084, batch 6b).

Revision ID: d4a8f2c60037
Revises: c9e6a2b40036
Create Date: 2026-11-16

Adds the role ``factory`` to the two role checks (``role_assignment``,
``invitation``); it grants no permission and makes nobody staff. Creates
``prod_factory_access`` (a supplier's login: email, invitation, account; at most
one live row per supplier and per account) and ``prod_cut_report`` (what the
factory says it cut, waiting for the QC manager; at most one waiting per
order). Nothing old is altered.

Downgrade refuses while any ``factory`` role or invitation (live or not), any
login row or any cut report exists, rather than lose who had a login and what a
factory reported; with none, it drops the two tables and narrows the checks.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "d4a8f2c60037"
down_revision: Union[str, Sequence[str], None] = "c9e6a2b40036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BEFORE = (
    "'admin', 'affiliate', 'affiliate_manager', 'content_manager', 'customer_service', 'operations_manager', "
    "'operations_staff', 'operations_viewer', 'production_manager', 'production_staff', 'production_viewer'"
)
AFTER = (
    "'admin', 'affiliate', 'affiliate_manager', 'content_manager', 'customer_service', 'factory', "
    "'operations_manager', 'operations_staff', 'operations_viewer', 'production_manager', 'production_staff', "
    "'production_viewer'"
)
ROLE_CHECKS = (("role_assignment", "role_assignment_role_valid"), ("invitation", "invitation_role_valid"))


def _user(name: str) -> sa.Column:
    return sa.Column(name, sa.Integer(), sa.ForeignKey("user_account.id", ondelete="SET NULL"))


def _now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def upgrade() -> None:
    # The role checks are read on every sign-in: give up rather than queue them.
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table, name in ROLE_CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"role IN ({AFTER})")

    op.create_table(
        "prod_factory_access",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_id", sa.String(80), sa.ForeignKey("production_supplier.id"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("invitation_id", sa.Integer(), sa.ForeignKey("invitation.id", ondelete="SET NULL")),
        _user("user_account_id"),
        _user("created_by"),
        _now("created_at"),
        sa.Column("switched_off_at", sa.DateTime(timezone=True)),
        _user("switched_off_by"),
        sa.CheckConstraint(
            "email = lower(email) AND char_length(email) BETWEEN 3 AND 320", name="prod_factory_access_email_valid"
        ),
        sa.CheckConstraint(
            "switched_off_at IS NOT NULL OR switched_off_by IS NULL", name="prod_factory_access_off_by_only_when_off"
        ),
    )
    op.create_index(
        "uq_prod_factory_access_live_supplier",
        "prod_factory_access",
        ["supplier_id"],
        unique=True,
        postgresql_where=sa.text("switched_off_at IS NULL"),
    )
    op.create_index(
        "uq_prod_factory_access_live_account",
        "prod_factory_access",
        ["user_account_id"],
        unique=True,
        postgresql_where=sa.text("switched_off_at IS NULL AND user_account_id IS NOT NULL"),
    )
    op.create_index("ix_prod_factory_access_invitation", "prod_factory_access", ["invitation_id"])
    op.create_index("ix_prod_factory_access_account", "prod_factory_access", ["user_account_id"])

    op.create_table(
        "prod_cut_report",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("prod_order.id"), nullable=False),
        sa.Column("sizes", JSONB(), nullable=False),
        sa.Column("note", sa.Text()),
        _user("reported_by"),
        _now("reported_at"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("replaced_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("note IS NULL OR char_length(note) <= 500", name="prod_cut_report_note_length"),
        sa.CheckConstraint("confirmed_at IS NULL OR replaced_at IS NULL", name="prod_cut_report_confirmed_or_replaced"),
    )
    op.create_index("ix_prod_cut_report_order", "prod_cut_report", ["order_id"])
    op.create_index(
        "uq_prod_cut_report_waiting",
        "prod_cut_report",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("confirmed_at IS NULL AND replaced_at IS NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    found = {
        "factory role assignment(s)": "SELECT count(*) FROM role_assignment WHERE role = 'factory'",
        "factory invitation(s)": "SELECT count(*) FROM invitation WHERE role = 'factory'",
        "factory login(s)": "SELECT count(*) FROM prod_factory_access",
        "factory cut report(s)": "SELECT count(*) FROM prod_cut_report",
    }
    counts = {what: bind.execute(sa.text(query)).scalar_one() for what, query in found.items()}
    present = [f"{count} {what}" for what, count in counts.items() if count]
    if present:
        raise RuntimeError(
            f"Refusing to downgrade: {', '.join(present)} exist and would be lost. "
            "Keep this revision, or move them out first."
        )
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index("uq_prod_cut_report_waiting", table_name="prod_cut_report")
    op.drop_index("ix_prod_cut_report_order", table_name="prod_cut_report")
    op.drop_table("prod_cut_report")
    op.drop_index("ix_prod_factory_access_account", table_name="prod_factory_access")
    op.drop_index("ix_prod_factory_access_invitation", table_name="prod_factory_access")
    op.drop_index("uq_prod_factory_access_live_account", table_name="prod_factory_access")
    op.drop_index("uq_prod_factory_access_live_supplier", table_name="prod_factory_access")
    op.drop_table("prod_factory_access")
    for table, name in ROLE_CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"role IN ({BEFORE})")
