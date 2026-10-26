"""two-step sign-in: the secret, the recovery codes, the half-way sign-in

ADR 0067, decision 5; Phase 1 batch 3. Three new tables and nothing else:

- `two_step_secret`: a person's authenticator secret, Fernet-encrypted, one per
  account, with the last 30-second step a code was accepted for (a code works
  once). No `enabled_at` means it is still being set up.
- `recovery_code`: the ten one-time codes for a lost phone, stored only as
  salted slow hashes.
- `pending_sign_in`: the right password with the code still owed. Its token is
  stored only as a hash, lives five minutes and works once.

**Additive.** No existing table or row is touched, so nobody's sign-in changes
by deploying this: two-step sign-in is off for everybody until they turn it on,
and nobody is made to until `TWO_STEP_ENFORCED` is set.

**Downgrade** drops the three tables. Everybody who had turned two-step
sign-in on signs in with the password alone again, and has to set it up afresh
if the upgrade is reapplied - the secrets are not kept anywhere else.

Revision ID: d5a2c8e40020
Revises: c3e7a1f90019
Create Date: 2026-10-26 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d5a2c8e40020"
down_revision: Union[str, Sequence[str], None] = "c3e7a1f90019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "two_step_secret",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_account_id", sa.Integer(), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_step", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_account_id"], ["user_account.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_account_id", name="two_step_secret_one_per_account"),
    )

    op.create_table(
        "recovery_code",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_account_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=200), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_account_id"], ["user_account.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_recovery_code_user_account_id"),
        "recovery_code",
        ["user_account_id"],
        unique=False,
    )

    op.create_table(
        "pending_sign_in",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_account_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_account_id"], ["user_account.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_pending_sign_in_user_account_id"),
        "pending_sign_in",
        ["user_account_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_pending_sign_in_user_account_id"), table_name="pending_sign_in")
    op.drop_table("pending_sign_in")
    op.drop_index(op.f("ix_recovery_code_user_account_id"), table_name="recovery_code")
    op.drop_table("recovery_code")
    op.drop_table("two_step_secret")
