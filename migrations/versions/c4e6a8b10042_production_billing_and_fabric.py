"""Production: bill photos and fabric storage (ADR 0089).

Revision ID: c4e6a8b10042
Revises: b3d5f7a90041
Create Date: 2026-11-22

* ``prod_purchase_photo``: photos or PDFs of a bill (a purchase's receipt),
  kept in the file bucket, removed with ``deleted_at``.
* ``prod_fabric``: a named roll type kept in storage. Its name is unique
  whatever its case (``uq_prod_fabric_name`` on ``lower(name)``).
* ``prod_fabric_move``: kilos in or out of a fabric's storage, signed, to
  three decimals. A fabric's stock is the sum of its moves, never a stored
  figure. ``purchase`` and ``return`` are positive, ``use`` and ``void``
  negative, ``count`` either; a ``return`` points at the ``use`` it undoes,
  once; a purchase fills storage once and is voided out of it once.

Three new tables; nothing existing is touched. Downgrade refuses while any
holds a row, rather than lose what was recorded; empty, it drops them.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4e6a8b10042"
down_revision: Union[str, Sequence[str], None] = "b3d5f7a90041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _user(name: str) -> sa.Column:
    return sa.Column(name, sa.Integer(), sa.ForeignKey("user_account.id", ondelete="SET NULL"))


def _created(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.create_table(
        "prod_purchase_photo",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_id", sa.Integer(), sa.ForeignKey("prod_purchase.id"), nullable=False),
        sa.Column("storage_key", sa.String(300), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        _user("uploaded_by"),
        _created(),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("size_bytes >= 0", name="prod_purchase_photo_size_not_negative"),
    )
    op.create_index("ix_prod_purchase_photo_purchase", "prod_purchase_photo", ["purchase_id"])

    op.create_table(
        "prod_fabric",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("fabric_type", sa.String(400)),
        sa.Column("colour", sa.String(80)),
        sa.Column("colour_code", sa.String(200)),
        sa.Column("supplier_id", sa.String(80), sa.ForeignKey("production_supplier.id")),
        sa.Column("note", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _user("created_by"),
        _created(),
        _created("updated_at"),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="prod_fabric_name_length"),
    )
    op.create_index("uq_prod_fabric_name", "prod_fabric", [sa.text("lower(name)")], unique=True)

    op.create_table(
        "prod_fabric_move",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fabric_id", sa.Integer(), sa.ForeignKey("prod_fabric.id"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("kg", sa.Numeric(12, 3), nullable=False),
        sa.Column("purchase_id", sa.Integer(), sa.ForeignKey("prod_purchase.id")),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("prod_order.id")),
        sa.Column("returns_id", sa.Integer(), sa.ForeignKey("prod_fabric_move.id")),
        sa.Column("note", sa.Text()),
        _user("created_by"),
        _created(),
        sa.CheckConstraint(
            "kind IN ('purchase', 'use', 'return', 'count', 'void')", name="prod_fabric_move_kind_valid"
        ),
        sa.CheckConstraint("kg <> 0", name="prod_fabric_move_kg_not_zero"),
        sa.CheckConstraint(
            "kind NOT IN ('purchase', 'void') OR purchase_id IS NOT NULL",
            name="prod_fabric_move_purchase_has_purchase",
        ),
        sa.CheckConstraint(
            "kind NOT IN ('use', 'return') OR order_id IS NOT NULL", name="prod_fabric_move_use_has_order"
        ),
        sa.CheckConstraint("(kind = 'return') = (returns_id IS NOT NULL)", name="prod_fabric_move_return_shape"),
        sa.CheckConstraint(
            "(kind IN ('purchase', 'return') AND kg > 0) OR (kind IN ('use', 'void') AND kg < 0) OR kind = 'count'",
            name="prod_fabric_move_sign",
        ),
    )
    op.create_index("ix_prod_fabric_move_fabric", "prod_fabric_move", ["fabric_id"])
    op.create_index("ix_prod_fabric_move_order", "prod_fabric_move", ["order_id"])
    op.create_index("ix_prod_fabric_move_purchase", "prod_fabric_move", ["purchase_id"])
    op.create_index(
        "uq_prod_fabric_move_returns", "prod_fabric_move", ["returns_id"], unique=True,
        postgresql_where=sa.text("returns_id IS NOT NULL"),
    )
    op.create_index(
        "uq_prod_fabric_move_purchase_kind", "prod_fabric_move", ["purchase_id", "kind"], unique=True,
        postgresql_where=sa.text("purchase_id IS NOT NULL"),
    )


#: What only this revision can hold, each with the words a refusal uses.
_HELD = (
    ("SELECT count(*) FROM prod_fabric_move", "fabric movement(s)"),
    ("SELECT count(*) FROM prod_fabric", "fabric(s)"),
    ("SELECT count(*) FROM prod_purchase_photo", "bill photo(s)"),
)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    for query, words in _HELD:
        found = bind.execute(sa.text(query)).scalar_one()
        if found:
            raise RuntimeError(
                f"Refusing to downgrade: {found} {words} exist and would be lost. "
                "Keep this revision, or move them out first."
            )
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.drop_index("uq_prod_fabric_move_purchase_kind", table_name="prod_fabric_move")
    op.drop_index("uq_prod_fabric_move_returns", table_name="prod_fabric_move")
    op.drop_index("ix_prod_fabric_move_purchase", table_name="prod_fabric_move")
    op.drop_index("ix_prod_fabric_move_order", table_name="prod_fabric_move")
    op.drop_index("ix_prod_fabric_move_fabric", table_name="prod_fabric_move")
    op.drop_table("prod_fabric_move")
    op.drop_index("uq_prod_fabric_name", table_name="prod_fabric")
    op.drop_table("prod_fabric")
    op.drop_index("ix_prod_purchase_photo_purchase", table_name="prod_purchase_photo")
    op.drop_table("prod_purchase_photo")
