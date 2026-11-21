"""Production: the Library, each product's own details (ADR 0087).

Revision ID: a7c3e9d10040
Revises: f1c2d3e40039
Create Date: 2026-11-21

* ``prod_library_item``: one row per Shopify product (keyed by its id, a
  foreign key to ``product`` with no cascade), holding what HBA types: colour
  code, fabric, print / embroidery type and width (above 0, at most 999.9),
  notes, and the COGS in the five parts of a piece's cost, in piastres (none
  below 0).
* ``prod_library_file``: its design files, size charts and pattern files.

Two new tables; nothing existing is touched. Downgrade refuses while either
holds a row, rather than lose what the owner typed; empty, it drops them.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e9d10040"
down_revision: Union[str, Sequence[str], None] = "f1c2d3e40039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PARTS = ("fabric", "manufacturing", "printing", "accessories", "packaging")


def _user(name: str) -> sa.Column:
    return sa.Column(name, sa.Integer(), sa.ForeignKey("user_account.id", ondelete="SET NULL"))


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.create_table(
        "prod_library_item",
        sa.Column(
            "shopify_product_id", sa.String(32), sa.ForeignKey("product.shopify_product_id"), primary_key=True
        ),
        sa.Column("colour_code", sa.String(40)),
        sa.Column("fabric_type", sa.String(120)),
        sa.Column("decoration_type", sa.String(120)),
        sa.Column("decoration_width_cm", sa.Numeric(6, 1)),
        sa.Column("notes", sa.Text()),
        *(sa.Column(f"cogs_{part}_piastres", sa.BigInteger()) for part in _PARTS),
        _user("updated_by"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "decoration_width_cm IS NULL OR (decoration_width_cm > 0 AND decoration_width_cm <= 999.9)",
            name="prod_library_item_decoration_width_range",
        ),
        *(
            sa.CheckConstraint(
                f"cogs_{part}_piastres IS NULL OR cogs_{part}_piastres >= 0",
                name=f"prod_library_item_cogs_{part}_not_negative",
            )
            for part in _PARTS
        ),
    )

    op.create_table(
        "prod_library_file",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shopify_product_id", sa.String(32), sa.ForeignKey("product.shopify_product_id"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(300), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        _user("uploaded_by"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "kind IN ('design', 'size_chart', 'pattern')", name="prod_library_file_kind_valid"
        ),
        sa.CheckConstraint("size_bytes >= 0", name="prod_library_file_size_not_negative"),
    )
    op.create_index("ix_prod_library_file_product", "prod_library_file", ["shopify_product_id"])


#: What only this revision can hold, each with the words a refusal uses.
_HELD = (
    ("SELECT count(*) FROM prod_library_item", "Library record(s)"),
    ("SELECT count(*) FROM prod_library_file", "Library file(s)"),
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

    op.drop_index("ix_prod_library_file_product", table_name="prod_library_file")
    op.drop_table("prod_library_file")
    op.drop_table("prod_library_item")
