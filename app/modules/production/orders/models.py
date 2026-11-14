"""The production order's tables (ADR 0084; build plan 2026-11-14).

One order is one style in one colour at one factory. Ten stages, a size table
running planned -> cut -> passed / to fix / rejected, the factory's
deliveries with Khazenly's count beside each, the delivery-date history, and
a settlement snapshot written when the owner settles.

**Money is integer piastres** (ADR 0002), in ``*_piastres`` columns, never
shown to anybody without ``production.owner``.

History is the platform's ``audit_event`` (``production.order_*``); there is
no history table here. Nothing in these tables is deleted: a file is hidden
with ``deleted_at``, an order is cancelled rather than removed.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

#: The fixed size list, in the order the screens show it. XS is optional.
SIZES: tuple[str, ...] = ("XS", "S", "M", "L", "XL", "XXL")

#: The ten stages, in order (ADR 0084, decision 4).
STAGES: tuple[str, ...] = (
    "plan",
    "sample",
    "materials",
    "fabric_check",
    "pattern_check",
    "cutting",
    "making",
    "final_inspection",
    "warehouse",
    "settle",
)

STAGE_LABELS: dict[str, str] = {
    "plan": "Plan",
    "sample": "Sample",
    "materials": "Materials",
    "fabric_check": "Fabric check",
    "pattern_check": "Pattern check",
    "cutting": "Cutting",
    "making": "Making",
    "final_inspection": "Final inspection",
    "warehouse": "Warehouse receipt",
    "settle": "Settle",
}

#: The typical days per stage, as seeded; ``prod_stage_days`` overrides them.
#: ``plan`` takes none: it is done the day the order is made.
DEFAULT_STAGE_DAYS: dict[str, int] = {
    "sample": 7,
    "materials": 7,
    "fabric_check": 2,
    "pattern_check": 3,
    "cutting": 2,
    "making": 17,
    "final_inspection": 1,
    "warehouse": 3,
    "settle": 7,
}

#: The five parts of a piece's cost.
COST_PARTS: tuple[str, ...] = ("fabric", "manufacturing", "printing", "accessories", "packaging")

FABRIC_BUYERS = ("hba", "factory")
PRINTING = ("factory", "outside", "none")
SAMPLE_STATUSES = ("none", "pending", "approved", "changes")
ORDER_STATUSES = ("open", "closed", "cancelled")
STAGE_STATUSES = ("todo", "done", "skipped")
REASON_KINDS = ("cut_short", "rejected", "to_fix")
DATE_SETTERS = ("owner", "factory")
DELIVERY_KINDS = ("finished", "fix")


def _in(values) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _user() -> Mapped[int | None]:
    return mapped_column(Integer, ForeignKey("user_account.id", ondelete="SET NULL"))


class ProdStageDays(Base):
    """The adjustable typical days per stage; the owner changes them."""

    __tablename__ = "prod_stage_days"
    __table_args__ = (
        CheckConstraint(f"stage IN ({_in(STAGES[1:])})", name="prod_stage_days_stage_valid"),
        CheckConstraint("days BETWEEN 0 AND 365", name="prod_stage_days_days_range"),
    )

    stage: Mapped[str] = mapped_column(String(20), primary_key=True)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = _created()
    updated_by: Mapped[int | None] = _user()


class ProdOrder(Base):
    __tablename__ = "prod_order"
    __table_args__ = (
        UniqueConstraint("code", name="prod_order_code_unique"),
        CheckConstraint(f"fabric_bought_by IN ({_in(FABRIC_BUYERS)})", name="prod_order_fabric_buyer_valid"),
        CheckConstraint(f"printing IN ({_in(PRINTING)})", name="prod_order_printing_valid"),
        # An outside print house is named; nobody else is.
        CheckConstraint(
            "(printing = 'outside') = (print_supplier_id IS NOT NULL)", name="prod_order_print_supplier_when_outside"
        ),
        CheckConstraint(f"sample_status IN ({_in(SAMPLE_STATUSES)})", name="prod_order_sample_status_valid"),
        CheckConstraint(f"status IN ({_in(ORDER_STATUSES)})", name="prod_order_status_valid"),
        CheckConstraint(
            " AND ".join(f"target_{part}_piastres >= 0" for part in COST_PARTS),
            name="prod_order_target_cost_not_negative",
        ),
        CheckConstraint(
            " AND ".join(f"(actual_{part}_piastres IS NULL OR actual_{part}_piastres >= 0)" for part in COST_PARTS),
            name="prod_order_actual_cost_not_negative",
        ),
        # The settlement snapshot is whole or absent, and a closed order has one.
        CheckConstraint(
            "(settled_at IS NULL) = (settled_payable_piastres IS NULL)", name="prod_order_settlement_whole"
        ),
        CheckConstraint("status <> 'closed' OR settled_at IS NOT NULL", name="prod_order_closed_is_settled"),
        Index("ix_prod_order_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: ``PO-YYMM-NN``, counted per Cairo month.
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    style_name: Mapped[str] = mapped_column(String(180), nullable=False)
    colour: Mapped[str] = mapped_column(String(80), nullable=False)
    #: A style may be produced before it is listed on Shopify.
    shopify_product_id: Mapped[str | None] = mapped_column(String(32))
    factory_id: Mapped[str] = mapped_column(String(80), ForeignKey("production_supplier.id"), nullable=False)
    fabric_bought_by: Mapped[str] = mapped_column(String(10), nullable=False)
    printing: Mapped[str] = mapped_column(String(10), nullable=False)
    print_supplier_id: Mapped[str | None] = mapped_column(String(80), ForeignKey("production_supplier.id"))
    repeat_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: The current promise; starts equal to ``target_date``.
    delivery_date: Mapped[date] = mapped_column(Date, nullable=False)

    target_fabric_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    target_manufacturing_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    target_printing_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    target_accessories_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    target_packaging_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    actual_fabric_piastres: Mapped[int | None] = mapped_column(BigInteger)
    actual_manufacturing_piastres: Mapped[int | None] = mapped_column(BigInteger)
    actual_printing_piastres: Mapped[int | None] = mapped_column(BigInteger)
    actual_accessories_piastres: Mapped[int | None] = mapped_column(BigInteger)
    actual_packaging_piastres: Mapped[int | None] = mapped_column(BigInteger)

    sample_status: Mapped[str] = mapped_column(String(10), nullable=False, default="none")
    sample_note: Mapped[str | None] = mapped_column(Text)
    sample_decided_by: Mapped[int | None] = _user()
    sample_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")

    #: What the factory was owed when the owner settled; may be negative when
    #: the factory bought the fabric and much was rejected.
    settled_payable_piastres: Mapped[int | None] = mapped_column(BigInteger)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_by: Mapped[int | None] = _user()

    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = _user()
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class ProdOrderSize(Base):
    __tablename__ = "prod_order_size"
    __table_args__ = (
        UniqueConstraint("order_id", "size", name="prod_order_size_once"),
        CheckConstraint(f"size IN ({_in(SIZES)})", name="prod_order_size_valid"),
        CheckConstraint(
            "planned >= 0 AND (cut IS NULL OR cut >= 0) AND (passed IS NULL OR passed >= 0) "
            "AND (to_fix IS NULL OR to_fix >= 0) AND (rejected IS NULL OR rejected >= 0)",
            name="prod_order_size_not_negative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("prod_order.id"), nullable=False)
    size: Mapped[str] = mapped_column(String(4), nullable=False)
    planned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cut: Mapped[int | None] = mapped_column(Integer)
    passed: Mapped[int | None] = mapped_column(Integer)
    to_fix: Mapped[int | None] = mapped_column(Integer)
    rejected: Mapped[int | None] = mapped_column(Integer)


class ProdOrderStage(Base):
    __tablename__ = "prod_order_stage"
    __table_args__ = (
        UniqueConstraint("order_id", "stage", name="prod_order_stage_once"),
        CheckConstraint(f"stage IN ({_in(STAGES)})", name="prod_order_stage_valid"),
        CheckConstraint("position BETWEEN 1 AND 10", name="prod_order_stage_position_range"),
        CheckConstraint(f"status IN ({_in(STAGE_STATUSES)})", name="prod_order_stage_status_valid"),
        CheckConstraint("(status = 'done') = (done_on IS NOT NULL)", name="prod_order_stage_done_has_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("prod_order.id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="todo")
    expected_date: Mapped[date | None] = mapped_column(Date)
    done_on: Mapped[date | None] = mapped_column(Date)
    done_by: Mapped[int | None] = _user()
    note: Mapped[str | None] = mapped_column(Text)


class ProdOrderReason(Base):
    """Why a count dropped: cut short of the plan, rejected, or sent to fix."""

    __tablename__ = "prod_order_reason"
    __table_args__ = (
        CheckConstraint(f"kind IN ({_in(REASON_KINDS)})", name="prod_order_reason_kind_valid"),
        CheckConstraint("quantity > 0", name="prod_order_reason_quantity_positive"),
        Index("ix_prod_order_reason_order", "order_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("prod_order.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[int | None] = _user()
    created_at: Mapped[datetime] = _created()


class ProdOrderDateChange(Base):
    """The delivery-date history, append-only. The first row is the target
    as planned, with no old date."""

    __tablename__ = "prod_order_date_change"
    __table_args__ = (
        CheckConstraint(f"set_by IN ({_in(DATE_SETTERS)})", name="prod_order_date_change_set_by_valid"),
        Index("ix_prod_order_date_change_order", "order_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("prod_order.id"), nullable=False)
    old_date: Mapped[date | None] = mapped_column(Date)
    new_date: Mapped[date] = mapped_column(Date, nullable=False)
    set_by: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[int | None] = _user()
    created_at: Mapped[datetime] = _created()


class ProdDelivery(Base):
    """One batch leaving the factory, with Khazenly's count when it comes."""

    __tablename__ = "prod_delivery"
    __table_args__ = (
        UniqueConstraint("order_id", "number", name="prod_delivery_number_once"),
        CheckConstraint("number >= 1", name="prod_delivery_number_positive"),
        CheckConstraint(f"kind IN ({_in(DELIVERY_KINDS)})", name="prod_delivery_kind_valid"),
        CheckConstraint("counted_on IS NULL OR counted_on >= shipped_on", name="prod_delivery_counted_after_shipped"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("prod_order.id"), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    shipped_on: Mapped[date] = mapped_column(Date, nullable=False)
    counted_on: Mapped[date | None] = mapped_column(Date)
    mismatch_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = _user()
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class ProdDeliverySize(Base):
    __tablename__ = "prod_delivery_size"
    __table_args__ = (
        UniqueConstraint("delivery_id", "size", name="prod_delivery_size_once"),
        CheckConstraint(f"size IN ({_in(SIZES)})", name="prod_delivery_size_valid"),
        CheckConstraint("shipped >= 0 AND (counted IS NULL OR counted >= 0)", name="prod_delivery_size_not_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[int] = mapped_column(Integer, ForeignKey("prod_delivery.id"), nullable=False)
    size: Mapped[str] = mapped_column(String(4), nullable=False)
    shipped: Mapped[int] = mapped_column(Integer, nullable=False)
    counted: Mapped[int | None] = mapped_column(Integer)


class ProdOrderFile(Base):
    """A photo or PDF on an order, kept in the platform's file bucket under
    ``production/orders/{order_id}/``."""

    __tablename__ = "prod_order_file"
    __table_args__ = (
        CheckConstraint(f"stage IS NULL OR stage IN ({_in(STAGES)})", name="prod_order_file_stage_valid"),
        CheckConstraint("size_bytes >= 0", name="prod_order_file_size_not_negative"),
        Index("ix_prod_order_file_order", "order_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("prod_order.id"), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[int | None] = _user()
    created_at: Mapped[datetime] = _created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
