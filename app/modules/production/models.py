"""Production's supplier tables (ADR 0069, ADR 0076; ADR 0085).

Production came from an app ChatGPT built on SQLite. Its orders, samples,
tasks, styles, phases, activity, QC checks, documents, stage proposals and
fixed lists were removed on 16 November 2026 (ADR 0085: Production starts from
zero). What stays are the suppliers and their categories: the new Production
orders, purchases, ratings and factory logins all point at them.

**Identifiers are the old app's own text ids**; a supplier keeps the id its
records already point at. New suppliers get the same kind of id.

Nothing here holds a password, a session or a person's contact details beyond
what the supplier list itself shows: who someone is comes from the platform's
own accounts.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
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
