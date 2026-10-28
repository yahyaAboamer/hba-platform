"""email codes and remembered browsers

ADR 0067, decision 5 as amended by the owner on 27 October 2026 (Phase 1,
batch 1.3b). The second step is asked only on a browser that is not
remembered; the owner gives an authenticator code, anybody else who can
approve or pay money a code sent by email, other staff whichever they turned
on.

- `trusted_browser`: a browser remembered for 30 days, with the kind of code
  that proved it. Only the hash of its cookie's token is kept. Forgotten by
  setting `revoked_at`, never deleted.
- `pending_sign_in` gains `method` ('authenticator' | 'email'), the emailed
  code as a keyed hash, when it was sent, how many were sent and how many
  wrong codes were typed - all
  nullable, so every existing row reads as an authenticator sign-in, which is
  what each of them was.
- `user_account.two_step_email_at`: when somebody turned email codes on.
  Nullable with no default, so adding it rewrites no row and holds the table
  for a moment only.

**Additive.** Nobody's sign-in changes by deploying this: nobody has email
codes on and nobody is required to until `TWO_STEP_ENFORCED` is set.

**Downgrade** drops the table and the columns. Every remembered browser is
forgotten (the next sign-in asks again), email-code sign-ins half done stop
working, and whoever had turned email codes on has to turn them on again if
the upgrade is reapplied.

Revision ID: e7b3d1f60021
Revises: d5a2c8e40020
Create Date: 2026-10-27 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e7b3d1f60021"
down_revision: Union[str, Sequence[str], None] = "d5a2c8e40020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

METHOD_VALID = "pending_sign_in_method_valid"


def upgrade() -> None:
    # `user_account` is read on every request: give up after five seconds
    # (and retry the deploy) rather than queue sign-ins behind a lock.
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.add_column(
        "user_account",
        sa.Column("two_step_email_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column("pending_sign_in", sa.Column("method", sa.String(length=20), nullable=True))
    op.add_column(
        "pending_sign_in", sa.Column("email_code_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "pending_sign_in",
        sa.Column("email_code_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pending_sign_in", sa.Column("email_codes_sent", sa.Integer(), nullable=True)
    )
    op.add_column("pending_sign_in", sa.Column("wrong_codes", sa.Integer(), nullable=True))
    op.create_check_constraint(
        METHOD_VALID,
        "pending_sign_in",
        "method IS NULL OR method IN ('authenticator', 'email')",
    )

    op.create_table(
        "trusted_browser",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_account_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_account_id"], ["user_account.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
        sa.CheckConstraint(
            "method IN ('authenticator', 'email')", name="trusted_browser_method_valid"
        ),
    )
    op.create_index(
        op.f("ix_trusted_browser_user_account_id"),
        "trusted_browser",
        ["user_account_id"],
        unique=False,
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.drop_index(op.f("ix_trusted_browser_user_account_id"), table_name="trusted_browser")
    op.drop_table("trusted_browser")
    op.drop_constraint(METHOD_VALID, "pending_sign_in", type_="check")
    op.drop_column("pending_sign_in", "wrong_codes")
    op.drop_column("pending_sign_in", "email_codes_sent")
    op.drop_column("pending_sign_in", "email_code_sent_at")
    op.drop_column("pending_sign_in", "email_code_hash")
    op.drop_column("pending_sign_in", "method")
    op.drop_column("user_account", "two_step_email_at")
