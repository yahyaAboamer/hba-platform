"""A refund can be paid before the return is back, and carry a photo (ADR 0082).

Revision ID: b2d8f4a60029
Revises: a1c7e3f50028
Create Date: 2026-11-11

``ops_refund_paid_complete`` no longer requires a paid row to have been
received. Adds ``proof_key`` and ``proof_type``: the optional photo of the
payment, kept in the file bucket.

Downgrade restores the narrower check and drops the photo columns. It
refuses while any paid row is not yet received, or any row has a photo,
rather than fail half way or lose a photo's link silently.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2d8f4a60029"
down_revision: Union[str, Sequence[str], None] = "a1c7e3f50028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PAID_BEFORE = (
    "paid_on IS NULL OR (received_at IS NOT NULL AND amount IS NOT NULL "
    "AND method IS NOT NULL AND refund_to IS NOT NULL)"
)
PAID_AFTER = "paid_on IS NULL OR (amount IS NOT NULL AND method IS NOT NULL AND refund_to IS NOT NULL)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint("ops_refund_paid_complete", "ops_refund", type_="check")
    op.create_check_constraint("ops_refund_paid_complete", "ops_refund", PAID_AFTER)
    op.add_column(
        "ops_refund", sa.Column("paid_early", sa.Boolean(), nullable=False, server_default=sa.text("false"))
    )
    op.create_check_constraint("ops_refund_early_paid", "ops_refund", "NOT paid_early OR paid_on IS NOT NULL")
    op.add_column("ops_refund", sa.Column("proof_key", sa.String(200), nullable=True))
    op.add_column("ops_refund", sa.Column("proof_type", sa.String(20), nullable=True))
    op.create_check_constraint(
        "ops_refund_proof_whole", "ops_refund", "(proof_key IS NULL) = (proof_type IS NULL)"
    )
    op.create_check_constraint(
        "ops_refund_proof_paid", "ops_refund", "proof_key IS NULL OR paid_on IS NOT NULL"
    )


def downgrade() -> None:
    bind = op.get_bind()
    early = bind.execute(
        sa.text("SELECT count(*) FROM ops_refund WHERE paid_on IS NOT NULL AND received_at IS NULL")
    ).scalar_one()
    photos = bind.execute(sa.text("SELECT count(*) FROM ops_refund WHERE proof_key IS NOT NULL")).scalar_one()
    if early or photos:
        raise RuntimeError(
            f"Refusing to downgrade: {early} refund(s) paid before the return was back and "
            f"{photos} with a proof photo. Undo those first."
        )
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint("ops_refund_proof_paid", "ops_refund", type_="check")
    op.drop_constraint("ops_refund_proof_whole", "ops_refund", type_="check")
    op.drop_column("ops_refund", "proof_type")
    op.drop_column("ops_refund", "proof_key")
    op.drop_constraint("ops_refund_early_paid", "ops_refund", type_="check")
    op.drop_column("ops_refund", "paid_early")
    op.drop_constraint("ops_refund_paid_complete", "ops_refund", type_="check")
    op.create_check_constraint("ops_refund_paid_complete", "ops_refund", PAID_BEFORE)
