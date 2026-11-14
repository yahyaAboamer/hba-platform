"""Production suppliers: sections, purchases and the supplier's account (ADR 0084, batch 4).

Revision ID: b8d5f1a30035
Revises: a7c4e9f20034
Create Date: 2026-11-14

Creates ``prod_section`` (seeded with the owner's five), ``prod_supplier_section``,
``prod_purchase``, ``prod_supplier_entry`` (the supplier's account, **append-only**:
a trigger refuses UPDATE, DELETE and TRUNCATE, as on the payment ledger) and
``prod_supplier_receipt``. Today's suppliers are placed in sections by their
old category's name; nothing is lost and nothing old is altered.

Downgrade refuses while any purchase or account line exists, rather than lose
money records; with none, it drops the trigger and the new tables.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8d5f1a30035"
down_revision: Union[str, Sequence[str], None] = "a7c4e9f20034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UNITS = "'kg', 'm', 'piece'"
PARTS = "'fabric', 'printing', 'accessories', 'packaging', 'other'"
KINDS = "'opening', 'purchase', 'work', 'payment', 'adjustment'"
METHODS = "'bank_transfer', 'cash', 'instapay', 'wallet', 'cheque'"
PAY_KINDS = "'weekly', 'deposit', 'final'"

#: The owner's sections, in order (build plan, 14 November 2026).
SECTIONS = ("Manufacturers", "Fabric", "Printing houses", "Accessories", "Packaging")


def section_for(category_name: str) -> str | None:
    """Which section an old supplier category belongs in: by its name,
    case-insensitively, the first rule that matches; otherwise the category's
    own name (cut to a section's 60 characters)."""
    name = " ".join((category_name or "").split())
    lowered = name.lower()
    if "manufactur" in lowered:
        return "Manufacturers"
    if "fabric" in lowered:
        return "Fabric"
    if "print" in lowered:
        return "Printing houses"
    if "accessor" in lowered or "trim" in lowered:
        return "Accessories"
    if "packag" in lowered:
        return "Packaging"
    return name[:60].strip() or None


def _user(name: str) -> sa.Column:
    return sa.Column(name, sa.Integer(), sa.ForeignKey("user_account.id", ondelete="SET NULL"))


def _now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    sections = op.create_table(
        "prod_section",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        _user("created_by"),
        _now("created_at"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("name", name="prod_section_name_unique"),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 60", name="prod_section_name_length"),
    )
    op.bulk_insert(sections, [{"name": name, "position": index} for index, name in enumerate(SECTIONS, start=1)])

    op.create_table(
        "prod_supplier_section",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_id", sa.String(80), sa.ForeignKey("production_supplier.id"), nullable=False),
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("prod_section.id"), nullable=False),
        sa.UniqueConstraint("supplier_id", "section_id", name="prod_supplier_section_once"),
    )

    op.create_table(
        "prod_purchase",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_id", sa.String(80), sa.ForeignKey("production_supplier.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("prod_order.id")),
        sa.Column("item", sa.String(200), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit", sa.String(5), nullable=False),
        sa.Column("unit_price_piastres", sa.BigInteger(), nullable=False),
        sa.Column("total_piastres", sa.BigInteger(), nullable=False),
        sa.Column("cost_part", sa.String(12), nullable=False),
        sa.Column("expected_on", sa.Date()),
        sa.Column("received_on", sa.Date()),
        sa.Column("note", sa.Text()),
        sa.Column("voided_at", sa.DateTime(timezone=True)),
        _user("voided_by"),
        sa.Column("void_reason", sa.Text()),
        _user("created_by"),
        _now("created_at"),
        sa.CheckConstraint("char_length(item) BETWEEN 1 AND 200", name="prod_purchase_item_length"),
        sa.CheckConstraint("quantity > 0", name="prod_purchase_quantity_positive"),
        sa.CheckConstraint(f"unit IN ({UNITS})", name="prod_purchase_unit_valid"),
        sa.CheckConstraint("unit_price_piastres > 0", name="prod_purchase_unit_price_positive"),
        sa.CheckConstraint("total_piastres > 0", name="prod_purchase_total_positive"),
        sa.CheckConstraint(f"cost_part IN ({PARTS})", name="prod_purchase_part_valid"),
        sa.CheckConstraint("(voided_at IS NULL) = (void_reason IS NULL)", name="prod_purchase_void_whole"),
    )
    op.create_index("ix_prod_purchase_supplier", "prod_purchase", ["supplier_id"])
    op.create_index("ix_prod_purchase_order", "prod_purchase", ["order_id"])

    op.create_table(
        "prod_supplier_entry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_id", sa.String(80), sa.ForeignKey("production_supplier.id"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("amount_piastres", sa.BigInteger(), nullable=False),
        sa.Column("happened_on", sa.Date(), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("prod_order.id")),
        sa.Column("purchase_id", sa.Integer(), sa.ForeignKey("prod_purchase.id")),
        sa.Column("method", sa.String(14)),
        sa.Column("payment_kind", sa.String(10)),
        sa.Column("note", sa.Text()),
        sa.Column("reverses_id", sa.Integer(), sa.ForeignKey("prod_supplier_entry.id")),
        _user("created_by"),
        _now("created_at"),
        sa.CheckConstraint(f"kind IN ({KINDS})", name="prod_supplier_entry_kind_valid"),
        sa.CheckConstraint("amount_piastres <> 0", name="prod_supplier_entry_amount_not_zero"),
        sa.CheckConstraint(f"method IS NULL OR method IN ({METHODS})", name="prod_supplier_entry_method_valid"),
        sa.CheckConstraint(
            f"payment_kind IS NULL OR payment_kind IN ({PAY_KINDS})", name="prod_supplier_entry_payment_kind_valid"
        ),
        sa.CheckConstraint(
            "(kind = 'payment') = (method IS NOT NULL AND payment_kind IS NOT NULL)",
            name="prod_supplier_entry_payment_shape",
        ),
        sa.CheckConstraint("kind <> 'work' OR order_id IS NOT NULL", name="prod_supplier_entry_work_has_order"),
        sa.CheckConstraint(
            "kind <> 'purchase' OR purchase_id IS NOT NULL", name="prod_supplier_entry_purchase_has_purchase"
        ),
        sa.CheckConstraint(
            "kind <> 'adjustment' OR note IS NOT NULL", name="prod_supplier_entry_adjustment_has_note"
        ),
        sa.UniqueConstraint("reverses_id", name="prod_supplier_entry_reversed_once"),
    )
    op.create_index("ix_prod_supplier_entry_supplier", "prod_supplier_entry", ["supplier_id", "happened_on", "id"])
    op.create_index("ix_prod_supplier_entry_purchase", "prod_supplier_entry", ["purchase_id"])

    op.create_table(
        "prod_supplier_receipt",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("prod_supplier_entry.id"), nullable=False),
        sa.Column("storage_key", sa.String(300), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        _user("uploaded_by"),
        _now("created_at"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("size_bytes >= 0", name="prod_supplier_receipt_size_not_negative"),
    )
    op.create_index(
        "uq_prod_supplier_receipt_live", "prod_supplier_receipt", ["entry_id"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # Today's suppliers, placed by their old category's name. Nothing is lost:
    # a category that is none of the five gets a section of its own name.
    bind = op.get_bind()
    section_ids = {
        name.lower(): section_id
        for section_id, name in bind.execute(sa.text("SELECT id, name FROM prod_section")).all()
    }
    position = len(SECTIONS)
    links = []
    rows = bind.execute(
        sa.text(
            "SELECT s.id, c.name FROM production_supplier s "
            "JOIN production_supplier_category c ON c.id = s.category_id ORDER BY s.id"
        )
    ).all()
    for supplier_id, category_name in rows:
        name = section_for(category_name)
        if name is None:
            continue
        if name.lower() not in section_ids:
            position += 1
            section_ids[name.lower()] = bind.execute(
                sa.text("INSERT INTO prod_section (name, position) VALUES (:n, :p) RETURNING id"),
                {"n": name, "p": position},
            ).scalar_one()
        links.append({"s": supplier_id, "c": section_ids[name.lower()]})
    if links:
        bind.execute(
            sa.text("INSERT INTO prod_supplier_section (supplier_id, section_id) VALUES (:s, :c)"), links
        )

    # Append-only, as the payment ledger is: two triggers, because a row-level
    # one does not fire on TRUNCATE. ``reject_mutation()`` is the platform's.
    op.execute(
        """
        CREATE TRIGGER prod_supplier_entry_no_update_or_delete
        BEFORE UPDATE OR DELETE ON prod_supplier_entry
        FOR EACH ROW EXECUTE FUNCTION reject_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER prod_supplier_entry_no_truncate
        BEFORE TRUNCATE ON prod_supplier_entry
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    purchases = bind.execute(sa.text("SELECT count(*) FROM prod_purchase")).scalar_one()
    lines = bind.execute(sa.text("SELECT count(*) FROM prod_supplier_entry")).scalar_one()
    if purchases or lines:
        raise RuntimeError(
            f"Refusing to downgrade: {purchases} purchase(s) and {lines} supplier account line(s) exist "
            "and would be lost. Keep this revision, or move them out first."
        )
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("DROP TRIGGER IF EXISTS prod_supplier_entry_no_truncate ON prod_supplier_entry;")
    op.execute("DROP TRIGGER IF EXISTS prod_supplier_entry_no_update_or_delete ON prod_supplier_entry;")
    op.drop_index("uq_prod_supplier_receipt_live", table_name="prod_supplier_receipt")
    op.drop_table("prod_supplier_receipt")
    op.drop_index("ix_prod_supplier_entry_purchase", table_name="prod_supplier_entry")
    op.drop_index("ix_prod_supplier_entry_supplier", table_name="prod_supplier_entry")
    op.drop_table("prod_supplier_entry")
    op.drop_index("ix_prod_purchase_order", table_name="prod_purchase")
    op.drop_index("ix_prod_purchase_supplier", table_name="prod_purchase")
    op.drop_table("prod_purchase")
    op.drop_table("prod_supplier_section")
    op.drop_table("prod_section")
