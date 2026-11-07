"""Production's tables (ADR 0069, ADR 0076 decision 1).

Production came from an app ChatGPT built on SQLite, about forty tables of
which thirteen held rows. Only what its screens read or write is kept here;
the settings rows it used as tables (drop phases, which phase an order is in,
the tracker's model name) are columns and a table of their own.

**Identifiers are the old app's own text ids** (`po-oct-…`, `SMP-…`,
`PRD-…`), so an imported record keeps the id its screens, photos and activity
already point at. New records get the same kinds of id the old server made.

**Money is integer piastres** (ADR 0002; ADR 0076 decision 7). The screens
send and see pounds; `app.modules.production.services.money` converts.

Nothing here holds a password, a session or a person's contact details: who
someone is comes from the platform's own accounts.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProductionSupplierCategory(Base):
    __tablename__ = "production_supplier_category"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = _created()


class ProductionSupplier(Base):
    __tablename__ = "production_supplier"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("production_supplier_category.id"))
    contact_person: Mapped[str | None] = mapped_column(String(180))
    phone: Mapped[str | None] = mapped_column(String(180))
    whatsapp: Mapped[str | None] = mapped_column(String(180))
    city: Mapped[str | None] = mapped_column(String(180))
    payment_terms: Mapped[str | None] = mapped_column(String(180))
    normal_lead_time_days: Mapped[int | None] = mapped_column(Integer)
    maximum_capacity: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    services: Mapped[list | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    #: Where the old app listed this row among others made in the same second
    #: (its database broke such ties its own way). Set by the import from the
    #: live answer; new rows have none and never tie.
    legacy_position: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductionProduct(Base):
    __tablename__ = "production_product"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    style_code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    category: Mapped[str | None] = mapped_column(String(120))
    collection: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str | None] = mapped_column(String(40))
    gsm: Mapped[int | None] = mapped_column(Integer)
    target_production_cost_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductionPhase(Base):
    """A drop phase. The id is the slug of its name, as the old app made it."""

    __tablename__ = "production_phase"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = _created()


class ProductionOrder(Base):
    __tablename__ = "production_order"
    __table_args__ = (Index("production_order_created", "created_at"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("production_product.id"), nullable=False)
    collection: Mapped[str | None] = mapped_column(String(120))
    color: Mapped[str | None] = mapped_column(String(80))
    tracker_order_number: Mapped[int | None] = mapped_column(Integer)
    #: The model name from the owner's manufacturing tracker, when the order came from it.
    tracker_model: Mapped[str | None] = mapped_column(String(180))
    fabric: Mapped[str | None] = mapped_column(String(180))
    fabric_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    size_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    total_ordered_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_accepted_quantity: Mapped[int | None] = mapped_column(Integer)
    progress_percentage: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    current_stage_name: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str | None] = mapped_column(String(40))
    priority: Mapped[str | None] = mapped_column(String(20))
    target_unit_cost_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    target_total_cost_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    actual_total_cost_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    target_delivery_date: Mapped[date | None] = mapped_column(Date)
    planned_start_date: Mapped[date | None] = mapped_column(Date)
    planned_completion_date: Mapped[date | None] = mapped_column(Date)
    forecast_completion_date: Mapped[date | None] = mapped_column(Date)
    actual_completion_date: Mapped[date | None] = mapped_column(Date)
    delay_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    blocking_reason: Mapped[str | None] = mapped_column(Text)
    cpo_approval_status: Mapped[str | None] = mapped_column(String(40))
    main_manufacturer_id: Mapped[str | None] = mapped_column(ForeignKey("production_supplier.id"))
    phase_id: Mapped[str | None] = mapped_column(ForeignKey("production_phase.id"))
    #: Where the old app listed this row among others made in the same second
    #: (its database broke such ties its own way). Set by the import from the
    #: live answer; new rows have none and never tie.
    legacy_position: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductionTask(Base):
    __tablename__ = "production_task"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    supplier: Mapped[str | None] = mapped_column(String(180))
    supplier_type: Mapped[str | None] = mapped_column(String(80))
    stage: Mapped[str | None] = mapped_column(String(100))
    next_action: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(120))
    action_date: Mapped[date | None] = mapped_column(Date)
    deadline: Mapped[date | None] = mapped_column(Date)
    progress: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    priority: Mapped[str | None] = mapped_column(String(20))
    #: Set by the latest "confirm", cleared by the latest "reopen" - the old
    #: app read this from its activity log; ADR 0076 decision 2.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(String(120))
    #: Where the old app listed this row among others made in the same second
    #: (its database broke such ties its own way). Set by the import from the
    #: live answer; new rows have none and never tie.
    legacy_position: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductionSample(Base):
    __tablename__ = "production_sample"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    material: Mapped[str | None] = mapped_column(String(180))
    priority: Mapped[str | None] = mapped_column(String(20))
    progress: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    stage: Mapped[str | None] = mapped_column(String(40))
    latest_progress: Mapped[str | None] = mapped_column(Text)
    #: The day the sample's latest progress was written, as the screens show it.
    updated_at_source: Mapped[date | None] = mapped_column(Date)
    next_step: Mapped[str | None] = mapped_column(Text)
    deadline: Mapped[date | None] = mapped_column(Date)
    owner: Mapped[str | None] = mapped_column(String(120))
    supplier: Mapped[str | None] = mapped_column(String(180))
    approved_by: Mapped[str | None] = mapped_column(String(120))
    approval_date: Mapped[date | None] = mapped_column(Date)
    manufacturing_notes: Mapped[str | None] = mapped_column(Text)
    updates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: "Mark done" / "Reopen" on the Samples screen. None: no override, the
    #: stage decides. Editing the sample clears it, as the old app did.
    done_override: Mapped[bool | None] = mapped_column(Boolean)
    done_override_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductionQcCheck(Base):
    """One line of an order's five-step QC checklist."""

    __tablename__ = "production_qc_check"
    __table_args__ = (UniqueConstraint("order_id", "step", "item", name="production_qc_check_one"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("production_order.id"), nullable=False)
    step: Mapped[str] = mapped_column(String(40), nullable=False)
    item: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    checked_by: Mapped[str] = mapped_column(String(120), nullable=False)
    updated_at: Mapped[datetime] = _created()


class ProductionActivity(Base):
    """Production's own activity list, which its screens read (the latest 40).

    Every entry is also an `audit_event` in the Production department; this
    table is what the screens were built on, the audit trail is the
    platform's record. Imported history carries no IP address or browser
    (ADR 0076 decision 9).
    """

    __tablename__ = "production_activity"
    __table_args__ = (Index("production_activity_created", "created_at"),)

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    module: Mapped[str | None] = mapped_column(String(60))
    record_id: Mapped[str | None] = mapped_column(String(180))
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("user_account.id"))
    created_at: Mapped[datetime] = _created()


class ProductionDocument(Base):
    """A file someone uploaded: an order or sample photo, or a document."""

    __tablename__ = "production_document"
    __table_args__ = (Index("production_document_record", "module", "record_id"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(80), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    module: Mapped[str] = mapped_column(String(80), nullable=False)
    record_id: Mapped[str] = mapped_column(String(180), nullable=False)
    confidential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("user_account.id"))
    created_at: Mapped[datetime] = _created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductionOrderStage(Base):
    """A stage of an order, made when the supplier portal first reports on it."""

    __tablename__ = "production_order_stage"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("production_order.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey("production_supplier.id"))
    planned_start: Mapped[date | None] = mapped_column(Date)
    planned_finish: Mapped[date | None] = mapped_column(Date)
    forecast_finish: Mapped[date | None] = mapped_column(Date)
    planned_lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    input_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rework_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_percentage: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class ProductionStageUpdate(Base):
    """A supplier's report on a stage, waiting for review. Never overwrites the stage."""

    __tablename__ = "production_stage_update"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    stage_id: Mapped[str] = mapped_column(ForeignKey("production_order_stage.id"), nullable=False)
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey("production_supplier.id"))
    proposed_status: Mapped[str] = mapped_column(String(40), nullable=False)
    quantity_completed: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    rejected_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    expected_completion_date: Mapped[str | None] = mapped_column(String(10))
    delay_expected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delay_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="Pending")
    submitted_by_id: Mapped[int | None] = mapped_column(ForeignKey("user_account.id"))
    created_at: Mapped[datetime] = _created()


class ProductionFixture(Base):
    """The fixed content Production's screens show (ADR 0076 decision 3).

    Lists and sentences that used to be written into the screens' code, some
    naming people. Imported once from the export; read whole by
    `/api/production/fixtures` before the first screen draws.
    """

    __tablename__ = "production_fixture"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | str] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = _created()
