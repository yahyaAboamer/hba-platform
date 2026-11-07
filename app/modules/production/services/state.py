"""`GET /api/production/state`: everything Production's screens draw from.

The same answer the old server's `loadSharedState` gave (ADR 0076 decision
2), field for field, built from the tables in `app.modules.production.models`
rather than from SQLite. The screens ask for it every five seconds and when
the window regains focus, and compare `revision` to say "A teammate's change
was synced".
"""

import json
import re
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.production.models import (
    ProductionActivity,
    ProductionDocument,
    ProductionFixture,
    ProductionOrder,
    ProductionPhase,
    ProductionProduct,
    ProductionQcCheck,
    ProductionSample,
    ProductionSupplier,
    ProductionSupplierCategory,
    ProductionTask,
)
from app.modules.production.services.js import (
    activity_time,
    as_number,
    clean_text,
    display_date,
    iso,
    out_number,
    piastres_to_pounds,
    sqlite_time,
)

ORDER_STATUSES = frozenset(
    {
        "Completed", "On Track", "At Risk", "Delayed", "Blocked", "Pending Approval",
        "Not Started", "Waiting", "In Progress", "Waiting for QC", "Rework", "Warehouse Received",
    }
)
FINISHED = ("Completed", "Warehouse Received")
_LEGACY_CODE = r"^HBA-PO-\d{3,4}(-[A-Z]+)?$"


def fixture_text(db: Session, key: str, fallback: str = "") -> str:
    """One of the fixed sentences (ADR 0076 decision 3), e.g. the default owner."""
    row = db.get(ProductionFixture, "texts")
    value = (row.value or {}).get(key) if row and isinstance(row.value, dict) else None
    return value if isinstance(value, str) and value else fallback


def _phases(db: Session) -> list[dict]:
    rows = db.scalars(select(ProductionPhase).order_by(ProductionPhase.created_at, ProductionPhase.id))
    return [{"id": row.id, "name": row.name} for row in rows]


def _stage(stage_id, name, short, status, supplier, planned, forecast, actual, quantity, accepted, progress, notes):
    """One of the three stages the old server made up for every order.
    `actual` is left out until the order is finished, as it was."""
    stage = {"id": stage_id, "name": name, "shortName": short, "status": status, "supplier": supplier,
             "planned": planned, "forecast": forecast}
    if actual is not None:
        stage["actual"] = actual
    stage.update({"quantity": out_number(quantity), "accepted": out_number(accepted), "rejected": 0,
                  "progress": out_number(progress), "notes": notes})
    return stage


def _orders(db: Session, phase_names: dict[str, str]) -> list[dict]:
    rows = db.execute(
        select(ProductionOrder, ProductionProduct, ProductionSupplier.name)
        .join(ProductionProduct, ProductionProduct.id == ProductionOrder.product_id)
        .outerjoin(ProductionSupplier, ProductionSupplier.id == ProductionOrder.main_manufacturer_id)
        .where(ProductionOrder.deleted_at.is_(None))
        .order_by(
            ProductionOrder.created_at.desc(), ProductionOrder.legacy_position.nulls_last(), ProductionOrder.id
        )
        .limit(100)
    ).all()
    orders = []
    for order, product, supplier_name in rows:
        quantity = max(0, as_number(order.total_ordered_quantity, 0))
        accepted = as_number(order.actual_accepted_quantity)
        status_value = clean_text(order.status, "Pending Approval", 40)
        status = status_value if status_value in ORDER_STATUSES else "Pending Approval"
        sizes = {}
        if isinstance(order.size_breakdown, dict):
            for key, value in order.size_breakdown.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    sizes[str(key)[:12]] = out_number(value)
        stage_status = "Completed" if status in FINISHED else status
        supplier = clean_text(supplier_name or "Unassigned", "Unassigned")
        forecast = order.forecast_completion_date or order.target_delivery_date
        completed = stage_status == "Completed"
        actual = display_date(order.actual_completion_date or order.planned_completion_date) if completed else None
        progress = out_number(order.progress_percentage)
        code = clean_text(order.code)
        entry: dict = {"id": clean_text(order.id), "code": code}
        if re.match(_LEGACY_CODE, order.code or ""):
            entry["legacyCode"] = order.code[7:]
        if order.tracker_order_number is not None:
            entry["trackerOrderNumber"] = order.tracker_order_number
        entry.update(
            {
                "fabric": clean_text(order.fabric),
                "fabricKg": out_number(order.fabric_kg) if order.fabric_kg is not None else None,
                "phaseId": order.phase_id or "",
                "phaseName": phase_names.get(order.phase_id or "", "Unassigned"),
                "product": clean_text(product.name, "Untitled product"),
            }
        )
        if order.tracker_model:
            entry["trackerModel"] = clean_text(order.tracker_model)
        stage_id = clean_text(order.id)
        notes = clean_text(order.notes, "", 1000)
        planned = display_date(order.planned_completion_date)
        expected = display_date(forecast)
        stages = [
            _stage(f"{stage_id}-logged", "Order logged", "Logged", "Completed", "HBA Internal", "Recorded",
                   "Recorded", "Recorded", quantity, quantity, 100,
                   "Imported from the HBA manufacturing tracker."),
            _stage(f"{stage_id}-make", "Manufacturing", "Production", stage_status, supplier, planned, expected,
                   actual, quantity, accepted, progress,
                   clean_text(order.notes, "Manufacturing tracker status.", 1000)),
            _stage(f"{stage_id}-qc", "Final QC and delivery", "QC / Delivery",
                   "Completed" if completed else "Not Started", "HBA QC", planned, expected, actual,
                   quantity, quantity if completed else 0, 100 if completed else 0,
                   "Confirm delivered and accepted quantity during final QC."),
        ]
        entry.update(
            {
                "style": clean_text(product.style_code, "—"),
                "collection": clean_text(order.collection, clean_text(product.collection, "HBA Production")),
                "color": clean_text(order.color, "—", 80),
                "quantity": out_number(quantity),
                "accepted": out_number(accepted),
                "rejected": 0,
                "progress": progress,
                "currentStage": clean_text(order.current_stage_name, "Production request & approval"),
                "status": status,
                "manager": "HBA shared team",
                "supplier": supplier,
                "startDate": display_date(order.planned_start_date),
                "startDateISO": iso(order.planned_start_date),
                "plannedDelivery": display_date(order.planned_completion_date),
                "plannedDeliveryISO": iso(order.planned_completion_date),
                "forecastDelivery": display_date(forecast),
                "forecastDeliveryISO": iso(forecast),
                "delayDays": order.delay_days or 0,
                "priority": clean_text(order.priority, "Normal"),
                "targetCost": piastres_to_pounds(order.target_unit_cost_piastres or 0),
                "actualCost": piastres_to_pounds(order.actual_total_cost_piastres or 0),
                "notes": notes,
                "sizeBreakdown": sizes,
                "stages": stages,
            }
        )
        orders.append(entry)
    return orders


def _suppliers(db: Session) -> list[dict]:
    active_orders = dict(
        db.execute(
            select(ProductionOrder.main_manufacturer_id, func.count())
            .where(
                ProductionOrder.deleted_at.is_(None),
                ProductionOrder.main_manufacturer_id.is_not(None),
                ProductionOrder.status.not_in(FINISHED) | ProductionOrder.status.is_(None),
            )
            .group_by(ProductionOrder.main_manufacturer_id)
        ).all()
    )
    rows = db.execute(
        select(ProductionSupplier, ProductionSupplierCategory.name)
        .outerjoin(ProductionSupplierCategory, ProductionSupplierCategory.id == ProductionSupplier.category_id)
        .where(ProductionSupplier.deleted_at.is_(None))
        .order_by(
            ProductionSupplier.created_at.desc(), ProductionSupplier.legacy_position.nulls_last(),
            ProductionSupplier.id,
        )
        .limit(100)
    ).all()
    suppliers = []
    for supplier, category in rows:
        capacity = supplier.maximum_capacity or 0
        # Ratings were never recorded; the old server read none and showed 0.
        suppliers.append(
            {
                "code": clean_text(supplier.code),
                "name": clean_text(supplier.name, "Unnamed supplier"),
                "category": clean_text(category or "Other", "Other"),
                "contact": clean_text(supplier.contact_person, "Not assigned"),
                "city": clean_text(supplier.city, "Cairo"),
                "phone": clean_text(supplier.phone, "—"),
                "activeOrders": active_orders.get(supplier.id, 0),
                "onTime": 0,
                "defectRate": 0,
                "rating": 0,
                "capacity": f"{capacity:,} units / month" if capacity else "Capacity not set",
                # `Math.max(1, asNumber(null, 14))` is 1: a blank lead time read "1 days".
                "leadTime": f"{max(1, supplier.normal_lead_time_days or 0)} days",
                "paymentTerms": clean_text(supplier.payment_terms, "Net 15"),
                "status": "Active" if supplier.active else "Inactive",
            }
        )
    return suppliers


def _activity(db: Session) -> tuple[list[dict], str]:
    rows = db.scalars(
        select(ProductionActivity)
        .order_by(ProductionActivity.created_at.desc(), ProductionActivity.id.desc())
        .limit(40)
    ).all()
    entries = []
    for row in rows:
        details = row.details if isinstance(row.details, dict) else {}
        entries.append(
            {
                "user": clean_text(details.get("actor"), "Public editor", 80),
                "action": clean_text(row.action, "Updated record").replace("_", " "),
                "module": clean_text(row.module, "Shared workspace"),
                "record": clean_text(row.record_id, clean_text(details.get("product"), "General")),
                "old": "—",
                "next": clean_text(details.get("summary"), clean_text(details.get("product"), "Saved to team")),
                "time": activity_time(row.created_at),
            }
        )
    revision = rows[0].created_at.isoformat() if rows else "initial"
    return entries, revision


def _tasks(db: Session, default_owner: str) -> list[dict]:
    rows = db.scalars(
        select(ProductionTask)
        .where(ProductionTask.deleted_at.is_(None))
        .order_by(
            ProductionTask.action_date.desc().nulls_last(),
            ProductionTask.created_at.desc(),
            ProductionTask.legacy_position.nulls_last(),
            ProductionTask.id,
        )
        .limit(100)
    ).all()
    return [
        {
            "id": clean_text(row.id),
            "name": clean_text(row.name, "Untitled task"),
            "supplier": clean_text(row.supplier, "Unassigned"),
            "supplierType": clean_text(row.supplier_type, "Other"),
            "confirmed": row.confirmed_at is not None,
            "confirmedAt": sqlite_time(row.confirmed_at),
            "confirmedBy": clean_text(row.confirmed_by) if row.confirmed_at else "",
            "stage": clean_text(row.stage, "Preparation"),
            "nextAction": clean_text(row.next_action, "Follow up", 1000),
            "owner": clean_text(row.owner, default_owner),
            "actionDate": display_date(row.action_date),
            "deadline": display_date(row.deadline),
            "progress": out_number(max(0, min(100, as_number(row.progress)))),
            "priority": clean_text(row.priority, "Normal"),
        }
        for row in rows
    ]


def _samples(db: Session) -> tuple[list[dict], dict[str, bool]]:
    photos: dict[str, list[ProductionDocument]] = defaultdict(list)
    for photo in db.scalars(
        select(ProductionDocument)
        .where(
            ProductionDocument.module == "Samples",
            ProductionDocument.document_type == "Sample photo",
            ProductionDocument.storage_key.startswith("production/sample-photos/"),
            ProductionDocument.confidential.is_(False),
            ProductionDocument.deleted_at.is_(None),
        )
        .order_by(ProductionDocument.created_at.desc(), ProductionDocument.id.desc())
    ):
        photos[photo.record_id].append(photo)
    rows = db.scalars(
        select(ProductionSample)
        .where(ProductionSample.deleted_at.is_(None))
        .order_by(ProductionSample.created_at.desc(), ProductionSample.id)
    ).all()
    samples, statuses = [], {}
    for row in rows:
        mine = photos.get(row.id, [])
        entry: dict = {
            "id": clean_text(row.id),
            "name": clean_text(row.name),
            "material": clean_text(row.material),
            "photoCount": len(mine),
        }
        if mine:
            entry["photoUrl"] = f"/api/production/sample-photos/{mine[0].id}"
        entry.update(
            {
                "priority": clean_text(row.priority, "Normal"),
                "progress": out_number(row.progress),
                "updates": row.updates or 0,
                "stage": clean_text(row.stage, "In Progress"),
                "latestProgress": clean_text(row.latest_progress, "", 1000),
                "updatedAt": display_date(row.updated_at_source),
                "nextStep": clean_text(row.next_step, "", 1000),
                "deadline": display_date(row.deadline),
                "owner": clean_text(row.owner),
                "supplier": clean_text(row.supplier, "Unassigned"),
                "approvedBy": clean_text(row.approved_by),
                "approvalDate": display_date(row.approval_date),
                "manufacturingNotes": clean_text(row.manufacturing_notes, "", 1000),
            }
        )
        samples.append(entry)
        if row.done_override is not None:
            statuses[row.id] = bool(row.done_override)
    return samples, statuses


def _products(db: Session) -> list[dict]:
    rows = db.scalars(
        select(ProductionProduct).where(ProductionProduct.deleted_at.is_(None)).order_by(ProductionProduct.name)
    )
    # Product variants were never recorded; the old server counted none.
    return [
        {
            "name": row.name,
            "style": row.style_code,
            "category": row.category,
            "collection": row.collection,
            "status": row.status,
            "gsm": row.gsm or 0,
            "targetCost": piastres_to_pounds(row.target_production_cost_piastres or 0),
            "variants": 0,
        }
        for row in rows
    ]


def _qc_checks(db: Session) -> list[dict]:
    rows = db.execute(
        select(ProductionQcCheck, ProductionOrder.code)
        .join(ProductionOrder, ProductionOrder.id == ProductionQcCheck.order_id)
        .order_by(ProductionQcCheck.id)
    ).all()
    return [
        {
            "orderCode": code,
            "step": check.step,
            "item": check.item,
            "result": check.result,
            "notes": check.notes,
            "checkedBy": check.checked_by,
            "updatedAt": sqlite_time(check.updated_at),
        }
        for check, code in rows
    ]


def shared_state(db: Session, user: dict) -> dict:
    """The whole answer, in the order the old server wrote its keys."""
    phases = _phases(db)
    phase_names = {phase["id"]: phase["name"] for phase in phases}
    samples, statuses = _samples(db)
    activity, revision = _activity(db)
    default_owner = fixture_text(db, "defaultSampleOwner", "")
    return {
        "phases": phases,
        "samples": samples,
        "products": _products(db),
        "sampleStatuses": statuses,
        "qcChecks": _qc_checks(db),
        "orders": _orders(db, phase_names),
        "suppliers": _suppliers(db),
        "activity": activity,
        "tasks": _tasks(db, default_owner),
        "revision": revision,
        "user": user,
    }


def fixtures(db: Session) -> dict:
    """The fixed content, whole: `{lists, texts, textLists}`."""
    found = {row.key: row.value for row in db.scalars(select(ProductionFixture))}
    lists = found.get("lists")
    texts = found.get("texts")
    text_lists = found.get("textLists")
    return {
        "lists": lists if isinstance(lists, dict) else {},
        "texts": texts if isinstance(texts, dict) else {},
        "textLists": text_lists if isinstance(text_lists, dict) else {},
    }


def dumps(payload: dict) -> str:
    """JSON as the old server sent it: no spaces, Unicode as is."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
