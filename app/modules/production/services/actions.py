"""`POST /api/production/actions`: every change Production's screens make.

The old server's `handleAction`, ported (ADR 0076 decision 2). Each action
keeps its words, its refusals and the quirks the screens depend on - an order
edit rewrites every field, so a field left out goes back to its default; an
order may be named `807` or `HBA-PO-807`; a task is confirmed by its latest
confirm or reopen. What changed is who may act (Production's levels, not the
old app's accounts) and that every change is also an `audit_event`.

Returns `(status, body)`; the route sends it as JSON.
"""

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.permissions import Permission
from app.modules.production.models import (
    ProductionActivity,
    ProductionOrder,
    ProductionOrderStage,
    ProductionPhase,
    ProductionProduct,
    ProductionQcCheck,
    ProductionSample,
    ProductionStageUpdate,
    ProductionSupplier,
    ProductionSupplierCategory,
    ProductionTask,
)
from app.modules.production.services.js import (
    as_number,
    clean_text,
    days_after,
    js_number,
    js_round,
    number_words,
    phase_slug,
    pounds_to_piastres,
    to_date,
    utc_today,
    valid_date,
)
from app.modules.production.services.qc import QC_STEPS
from app.modules.production.services.state import FINISHED, ORDER_STATUSES, fixture_text
from app.shared.services.audit import record_audit

#: Which permission each action needs (ADR 0076 decision 5).
NEEDS: dict[str, str] = {
    **{
        action: Permission.PRODUCTION_EDIT
        for action in (
            "create_phase", "assign_phase", "create_order", "update_order", "create_task", "create_sample",
            "update_sample", "update_task", "delete_task", "confirm_task", "reopen_task", "sample_status",
        )
    },
    "qc_check": Permission.PRODUCTION_QC,
    "create_supplier": Permission.PRODUCTION_SUPPLIERS,
    "supplier_update": Permission.PRODUCTION_SUPPLIERS,
    "approve_payment": Permission.PRODUCTION_PAYMENTS,
    "shared_update": Permission.PRODUCTION_PAYMENTS,
}

MODULE_OF: dict[str, str] = {
    "create_phase": "Production Orders",
    "assign_phase": "Production Orders",
    "create_task": "Production Tasks",
    "create_sample": "Samples",
    "update_sample": "Samples",
    "qc_check": "Quality Control",
    "sample_status": "Samples",
    "create_order": "Production Orders",
    "update_order": "Production Orders",
    "create_supplier": "Suppliers",
    "supplier_update": "Supplier Portal",
    "approve_payment": "Payments",
    "update_task": "Production Tasks",
    "delete_task": "Production Tasks",
    "confirm_task": "Production Tasks",
    "reopen_task": "Production Tasks",
    "shared_update": "Shared Workspace",
}

PRIORITIES = ("Critical", "High", "Normal", "Low")
SAMPLE_PRIORITIES = ("Critical", "Urgent", "High", "Normal", "Low")
SAMPLE_STAGES = ("Done", "Approved", "In Progress", "Revision Requested", "On Hold", "Rejected")
SIZES = ("S", "M", "L", "XL", "XXL")

_MISSING = object()


class Refused(Exception):
    """An action refused with the old server's words."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _priority(value: object, sample: bool = False) -> str:
    allowed = SAMPLE_PRIORITIES if sample else PRIORITIES
    return str(value) if str(value) in allowed and isinstance(value, str) else "Normal"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_order_code(db: Session, code: str) -> str:
    """`resolveOrderCode`: "807" finds "HBA-PO-807" and the other way round."""
    if re.fullmatch(r"\d{3,4}(-[A-Z]+)?", code):
        alternate = f"HBA-PO-{code}"
    elif re.fullmatch(r"HBA-PO-\d{3,4}(-[A-Z]+)?", code):
        alternate = code[7:]
    else:
        alternate = code
    rows = db.scalars(
        select(ProductionOrder.code).where(
            ProductionOrder.code.in_((code, alternate)), ProductionOrder.deleted_at.is_(None)
        )
    ).all()
    if code in rows:
        return code
    return rows[0] if rows else code


def _order_by_code(db: Session, code: str) -> ProductionOrder | None:
    return db.scalar(
        select(ProductionOrder).where(ProductionOrder.code == code, ProductionOrder.deleted_at.is_(None))
    )


def _valid_phase(db: Session, phase_id: str) -> bool:
    return not phase_id or db.get(ProductionPhase, phase_id) is not None


def _check_date(value: str, message: str) -> None:
    if value and not valid_date(value):
        raise Refused(400, message)


def perform(db: Session, body: Any, *, actor_name: str, actor_id: int, actor_email: str,
            held: frozenset[str]) -> tuple[int, dict]:
    """Do one action. Staged, not committed: the route commits it whole."""
    if not isinstance(body, dict):
        return 400, {"error": "Invalid JSON payload"}
    action = body.get("action")
    action = action if isinstance(action, str) else ""
    needed = NEEDS.get(action)
    if needed is not None and needed not in held:
        return 403, {"error": "Your account does not have permission for this action"}
    if needed is None:
        # The old server refused an unknown action as a permission problem
        # for everyone but the owner, who was told it was unknown.
        if Permission.PRODUCTION_PAYMENTS not in held:
            return 403, {"error": "Your account does not have permission for this action"}
        return 400, {"error": "Unknown action"}
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    try:
        record_id, summary = _ACTIONS[action](db, body, payload, actor_name)
    except Refused as refused:
        return refused.status, {"error": refused.message}

    details: dict[str, Any] = {}
    for key in ("quantity", "product"):
        if key in body:
            details[key] = body[key]
    if "payload" in body:
        details["payload"] = body["payload"]
    details["actor"] = actor_name
    details["summary"] = summary
    db.add(
        ProductionActivity(
            id=str(uuid.uuid4()),
            action=action,
            module=MODULE_OF[action],
            record_id=record_id,
            details=details,
            actor_id=actor_id,
            created_at=_now(),
        )
    )
    record_audit(
        db,
        action=f"production.{action}",
        subject=f"production:{record_id}",
        actor_id=actor_id,
        actor_email=actor_email,
        after={"summary": summary, **({"payload": body["payload"]} if "payload" in body else {})},
    )
    return 201, {"ok": True, "action": action, "recordId": record_id, "summary": summary}


def _phase_value(db: Session, body: dict, payload: dict, action: str) -> object:
    """The phase an order action names, checked; `_MISSING` when none."""
    source = body if action == "create_order" else payload
    value = source.get("phaseId", _MISSING)
    if value is not _MISSING and (not isinstance(value, str) or not _valid_phase(db, value)):
        raise Refused(400, "Choose an existing drop phase")
    return value


def _order_record_id(db: Session, body: dict) -> str:
    return resolve_order_code(db, clean_text(body.get("recordId"), "", 120))


# ── Phases ────────────────────────────────────────────────────────────────────


def _create_phase(db, body, payload, actor):
    name = clean_text(payload.get("name"), "", 80)
    if not name:
        raise Refused(400, "Phase name is required")
    slug = phase_slug(name)
    if not slug:
        raise Refused(400, "Enter a phase name containing letters or numbers")
    if db.get(ProductionPhase, slug) is None:
        db.add(ProductionPhase(id=slug, name=name, created_at=_now()))
        db.flush()
    return slug, f"Drop phase {name} created"


def _assign_phase(db, body, payload, actor):
    code = _order_record_id(db, body)
    phase = _phase_value(db, body, payload, "assign_phase")
    order = _order_by_code(db, code)
    if order is None:
        raise Refused(404, "Order not found")
    order.phase_id = clean_text(phase if phase is not _MISSING else None) or None
    return code, "Order drop phase updated"


# ── Orders ────────────────────────────────────────────────────────────────────


def _unique_code(db: Session, date_code: str) -> str:
    count = db.scalar(
        select(func.count()).select_from(ProductionOrder).where(ProductionOrder.code.like(f"HBA-PO-{date_code}-%"))
    ) or 0
    sequence = max(1, count + 1)
    # The old server counted and hoped; two people creating at once could get
    # the same code. Step past any code already taken instead.
    while db.scalar(select(ProductionOrder.id).where(ProductionOrder.code == f"HBA-PO-{date_code}-{sequence:03d}")):
        sequence += 1
    return f"HBA-PO-{date_code}-{sequence:03d}"


def _create_order(db, body, payload, actor):
    phase = _phase_value(db, body, payload, "create_order")
    quantity = max(1, min(100000, js_round(as_number(body.get("quantity"), 100, absent="quantity" not in body))))
    requested = clean_text(body.get("product"), "Basic Pants")
    product = db.scalar(
        select(ProductionProduct)
        .where(ProductionProduct.name == requested, ProductionProduct.deleted_at.is_(None))
        .limit(1)
    )
    if product is None:
        raise Refused(409, "Selected product was not found")
    manufacturer_name = clean_text(body.get("manufacturer"), "Cotton Candy")
    manufacturer = db.scalar(
        select(ProductionSupplier.id)
        .where(ProductionSupplier.name == manufacturer_name, ProductionSupplier.deleted_at.is_(None))
        .limit(1)
    )
    target_delivery = clean_text(body.get("targetDelivery"), days_after(30).isoformat(), 10)
    _check_date(target_delivery, "Enter valid production dates or leave them blank")
    code = _unique_code(db, utc_today().strftime("%y%m%d"))
    unit = product.target_production_cost_piastres or 0
    order = ProductionOrder(
        id=str(uuid.uuid4()),
        code=code,
        collection=clean_text(body.get("collection"), clean_text(product.collection, "HBA Production")),
        color=clean_text(body.get("color"), "—", 80),
        size_breakdown={},
        product_id=product.id,
        total_ordered_quantity=quantity,
        target_delivery_date=to_date(target_delivery),
        planned_start_date=utc_today(),
        planned_completion_date=to_date(target_delivery),
        forecast_completion_date=to_date(target_delivery),
        main_manufacturer_id=manufacturer,
        priority="Normal",
        target_unit_cost_piastres=unit,
        target_total_cost_piastres=unit * quantity,
        current_stage_name="Production request & approval",
        status="Pending Approval",
        progress_percentage=0,
        cpo_approval_status="Pending",
        notes=f"Created by {actor} in the public shared workspace",
        phase_id=(phase or None) if isinstance(phase, str) else None,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(order)
    db.flush()
    return code, f"{requested} · {quantity} units"


def _update_order(db, body, payload, actor):
    phase = _phase_value(db, body, payload, "update_order")
    code = _order_record_id(db, body)
    if not code:
        raise Refused(400, "Production order code is required")
    existing = _order_by_code(db, code)
    if existing is None:
        raise Refused(404, "Production order was not found")
    update = payload
    requested_status = clean_text(update.get("status"), "In Progress", 40)
    status = requested_status if requested_status in ORDER_STATUSES else "In Progress"
    requested_priority = clean_text(update.get("priority"), "Normal", 20)
    priority = requested_priority if requested_priority in PRIORITIES else "Normal"
    quantity = max(0, min(100000, js_round(as_number(update.get("quantity"), existing.total_ordered_quantity,
                                                     absent="quantity" not in update))))
    progress = max(0, min(100, as_number(update.get("progress"), 0, absent="progress" not in update)))

    def given_date(key: str, current: str) -> str:
        value = update.get(key)
        return value.strip() if isinstance(value, str) else current

    planned_start = given_date("startDate", existing.planned_start_date.isoformat() if existing.planned_start_date else "")
    planned_completion = given_date(
        "plannedDelivery", existing.planned_completion_date.isoformat() if existing.planned_completion_date else ""
    )
    forecast_completion = given_date(
        "forecastDelivery",
        existing.forecast_completion_date.isoformat() if existing.forecast_completion_date else planned_completion,
    )
    if any(value and not valid_date(value) for value in (planned_start, planned_completion, forecast_completion)):
        raise Refused(400, "Enter valid production dates or leave them blank")
    fabric = clean_text(update["fabric"]) if isinstance(update.get("fabric"), str) else clean_text(existing.fabric)
    if "fabricKg" not in update:
        fabric_kg = existing.fabric_kg
    elif update["fabricKg"] in ("", None):
        fabric_kg = None
    else:
        fabric_kg = js_number(update["fabricKg"])
        if not (fabric_kg == fabric_kg and fabric_kg not in (float("inf"), float("-inf"))) or fabric_kg < 0:
            raise Refused(400, "Fabric KG must be a non-negative number")
    sizes = existing.size_breakdown if isinstance(existing.size_breakdown, dict) else {}
    if any(f"size_{size}" in update for size in SIZES):
        values = [js_number(update.get(f"size_{size}", 0)) for size in SIZES]
        if any(not float(v).is_integer() or v < 0 for v in values) or sum(values) != quantity:
            raise Refused(400, "Size quantities must be whole numbers and total the order quantity")
        sizes = {size: int(value) for size, value in zip(SIZES, values)}
    planned_day, forecast_day = to_date(planned_completion), to_date(forecast_completion)
    delay = max(0, (forecast_day - planned_day).days) if planned_day and forecast_day else 0
    manufacturer_name = clean_text(update.get("supplier"), "", 180)
    manufacturer = None
    if manufacturer_name:
        manufacturer = db.scalar(
            select(ProductionSupplier.id)
            .where(ProductionSupplier.name == manufacturer_name, ProductionSupplier.deleted_at.is_(None))
            .limit(1)
        )
    unit = pounds_to_piastres(max(0, as_number(update.get("targetCost"), 0, absent="targetCost" not in update)))
    existing.collection = clean_text(update.get("collection"), "HBA Production", 120)
    existing.color = clean_text(update.get("color"), "—", 80)
    existing.total_ordered_quantity = quantity
    existing.priority = priority
    existing.status = status
    existing.progress_percentage = progress
    existing.current_stage_name = clean_text(update.get("currentStage"), "Production", 120)
    existing.planned_start_date = to_date(planned_start)
    existing.planned_completion_date = planned_day
    existing.forecast_completion_date = forecast_day
    existing.target_delivery_date = forecast_day
    existing.delay_days = delay
    existing.target_unit_cost_piastres = unit
    existing.target_total_cost_piastres = unit * quantity
    existing.main_manufacturer_id = manufacturer
    existing.notes = clean_text(update.get("notes"), "", 1000)
    existing.fabric = fabric
    existing.fabric_kg = fabric_kg
    existing.size_breakdown = sizes
    existing.updated_at = _now()
    if isinstance(phase, str):
        existing.phase_id = phase or None
    return code, f"{code} updated · {quantity} units · {status}"


# ── Suppliers ─────────────────────────────────────────────────────────────────


def _create_supplier(db, body, payload, actor):
    name = clean_text(body.get("name"), "New supplier")
    category_name = clean_text(body.get("category"), "Other")
    first_word = category_name.split(" ")[0]
    category = db.scalar(
        select(ProductionSupplierCategory.id)
        .where(func.lower(ProductionSupplierCategory.name).like(f"%{first_word.lower()}%"))
        .order_by(ProductionSupplierCategory.id)
        .limit(1)
    )
    count = db.scalar(select(func.count()).select_from(ProductionSupplier)) or 0
    sequence = count + 1
    while db.scalar(select(ProductionSupplier.id).where(ProductionSupplier.code == f"SUP-{sequence:03d}")):
        sequence += 1
    code = f"SUP-{sequence:03d}"
    phone = clean_text(body.get("phone"), "—")
    db.add(
        ProductionSupplier(
            id=str(uuid.uuid4()),
            code=code,
            name=name,
            category_id=category,
            contact_person=clean_text(body.get("contact"), "Not assigned"),
            phone=phone,
            whatsapp=phone,
            city=clean_text(body.get("city"), "Cairo"),
            payment_terms=clean_text(body.get("paymentTerms"), "Net 15"),
            services=[clean_text(body.get("notes"), category_name, 500)],
            active=True,
            notes=f"Created by {actor} in the public shared workspace",
            created_at=_now(),
            updated_at=_now(),
        )
    )
    db.flush()
    return code, f"{name} · {category_name}"


def _supplier_update(db, body, payload, actor):
    code = resolve_order_code(db, clean_text(body.get("recordId"), "", 120)) or "801"
    code = clean_text(code, "801")
    update = payload
    stage = db.scalar(
        select(ProductionOrderStage)
        .join(ProductionOrder, ProductionOrder.id == ProductionOrderStage.order_id)
        .where(ProductionOrder.code == code, ProductionOrderStage.status.not_in(FINISHED))
        .order_by(ProductionOrderStage.sequence)
        .limit(1)
    )
    if stage is None:
        order = _order_by_code(db, code)
        if order is None:
            raise Refused(404, "Production order was not found")
        planned_finish = order.planned_completion_date or days_after(7)
        stage = ProductionOrderStage(
            id=str(uuid.uuid4()),
            order_id=order.id,
            sequence=1,
            name=clean_text(order.current_stage_name, "Manufacturing"),
            supplier_id=order.main_manufacturer_id,
            planned_start=order.planned_start_date or utc_today(),
            planned_finish=planned_finish,
            forecast_finish=planned_finish,
            planned_lead_time_days=1,
            input_quantity=max(0, order.total_ordered_quantity or 0),
            progress_percentage=order.progress_percentage or 0,
            status=clean_text(order.status, "In Progress", 40),
            notes="Created from the shared supplier portal",
        )
        db.add(stage)
        db.flush()
    completed = as_number(update.get("completed"), 0, absent="completed" not in update)
    status = clean_text(update.get("status"), "In Progress")
    db.add(
        ProductionStageUpdate(
            id=str(uuid.uuid4()),
            stage_id=stage.id,
            supplier_id=stage.supplier_id,
            proposed_status=status,
            quantity_completed=max(0, completed),
            rejected_quantity=max(0, as_number(update.get("rejected"), 0, absent="rejected" not in update)),
            expected_completion_date=clean_text(update.get("forecast"), days_after(7).isoformat(), 10),
            delay_expected=bool(update.get("delayExpected")),
            delay_reason=clean_text(update.get("delayReason"), ""),
            notes=clean_text(update.get("notes"), "Shared supplier update", 1000),
            review_status="Pending",
        )
    )
    return code, f"{number_words(completed)} completed · {status}"


def _approve_payment(db, body, payload, actor):
    # No supplier invoice is ever created in Production yet (ADR 0076
    # decision 7); the old server's update matched none, and nothing is
    # stored here either. The approval is still recorded, as it was.
    invoice = clean_text(body.get("recordId"), "")
    if not invoice:
        raise Refused(400, "Invoice number is required")
    return invoice, f"{invoice} approved for payment"


def _shared_update(db, body, payload, actor):
    return clean_text(body.get("recordId"), "general", 120), "Saved to the shared team workspace"


# ── Tasks ─────────────────────────────────────────────────────────────────────


def _create_task(db, body, payload, actor):
    name = clean_text(payload.get("name"))
    if not name:
        raise Refused(400, "Task name is required")
    deadline = clean_text(payload.get("deadline"), "", 10)
    action_date = clean_text(payload.get("actionDate"), utc_today().isoformat(), 10)
    if (deadline and not valid_date(deadline)) or not valid_date(action_date):
        raise Refused(400, "Enter a valid date")
    record_id = f"PRD-{uuid.uuid4()}"
    db.add(
        ProductionTask(
            id=record_id,
            name=name,
            supplier=clean_text(payload.get("supplier"), "Unassigned"),
            supplier_type=clean_text(payload.get("supplierType"), "Sampling"),
            stage=clean_text(payload.get("stage"), "Preparation"),
            next_action=clean_text(payload.get("nextAction"), "Follow up", 1000),
            owner=clean_text(payload.get("owner"), actor),
            action_date=to_date(action_date),
            deadline=to_date(deadline),
            progress=0,
            priority=_priority(payload.get("priority")),
            created_at=_now(),
            updated_at=_now(),
        )
    )
    return record_id, f"{name} created"


def _live_task(db: Session, task_id: str) -> ProductionTask | None:
    return db.scalar(select(ProductionTask).where(ProductionTask.id == task_id, ProductionTask.deleted_at.is_(None)))


def _update_task(db, body, payload, actor):
    task_id = clean_text(body.get("recordId"), "", 120)
    if not task_id:
        raise Refused(400, "Task ID is required")
    task = _live_task(db, task_id)
    if task is None:
        raise Refused(404, "Task was not found")
    update = payload
    action_date = clean_text(update.get("actionDate"), utc_today().isoformat(), 10)
    deadline = clean_text(update.get("deadline"), "", 10)
    # The old server stored whatever came; a date column cannot, so a date
    # that is not one is refused as `create_task` refuses it.
    if not valid_date(action_date) or (deadline and not valid_date(deadline)):
        raise Refused(400, "Enter a valid date")
    requested = clean_text(update.get("priority"), "Normal", 20)
    task.name = clean_text(update.get("name"), clean_text(task.name, "Untitled task"), 180)
    task.supplier = clean_text(update.get("supplier"), "Unassigned", 180)
    task.supplier_type = clean_text(update.get("supplierType"), "Other", 80)
    task.stage = clean_text(update.get("stage"), "Preparation", 100)
    task.next_action = clean_text(update.get("nextAction"), "Follow up", 1000)
    task.owner = clean_text(update.get("owner"), fixture_text(db, "defaultSampleOwner", actor), 120)
    task.action_date = to_date(action_date)
    task.deadline = to_date(deadline)
    task.progress = max(0, min(100, as_number(update.get("progress"), 0, absent="progress" not in update)))
    task.priority = requested if requested in PRIORITIES else "Normal"
    task.updated_at = _now()
    return task_id, f"{clean_text(update.get('name'), clean_text(task.name, 'Task'), 180)} updated"


def _confirm_or_reopen(db, body, payload, actor, *, confirm: bool):
    task_id = clean_text(body.get("recordId"), "", 120)
    if not task_id:
        raise Refused(400, "Task ID is required")
    task = _live_task(db, task_id)
    if task is None:
        raise Refused(404, "Task was not found")
    if confirm:
        task.stage, task.progress = "Done", 100
        task.confirmed_at, task.confirmed_by = _now(), actor
    else:
        if task.stage == "Done":
            task.stage, task.progress = "Preparation", 0
        task.confirmed_at, task.confirmed_by = None, None
    task.updated_at = _now()
    where = "moved to Confirmed" if confirm else "moved to Active tasks"
    return task_id, f"{clean_text(task.name, 'Task')} {where}"


def _delete_task(db, body, payload, actor):
    task_id = clean_text(body.get("recordId"), "", 120)
    if not task_id:
        raise Refused(400, "Task ID is required")
    task = _live_task(db, task_id)
    if task is None:
        raise Refused(404, "Task was not found or was already deleted")
    task.deleted_at = task.updated_at = _now()
    return task_id, f"{clean_text(task.name, 'Task')} deleted"


# ── Samples ───────────────────────────────────────────────────────────────────


def _live_sample(db: Session, sample_id: str) -> ProductionSample | None:
    return db.scalar(
        select(ProductionSample).where(ProductionSample.id == sample_id, ProductionSample.deleted_at.is_(None))
    )


def _save_sample(db, body, payload, actor, *, create: bool):
    name = clean_text(payload.get("name"))
    if not name:
        raise Refused(400, "Sample name is required")
    deadline = clean_text(payload.get("deadline"), "", 10)
    _check_date(deadline, "Enter a valid deadline")
    stage = clean_text(payload.get("stage"), "In Progress")
    if stage not in SAMPLE_STAGES:
        raise Refused(400, "Invalid sample stage")
    progress = 100 if stage in ("Done", "Approved") else max(
        0, min(100, as_number(payload.get("progress"), 0, absent="progress" not in payload))
    )
    values = dict(
        name=name,
        material=clean_text(payload.get("material")),
        priority=_priority(payload.get("priority"), sample=True),
        progress=progress,
        stage=stage,
        latest_progress=clean_text(payload.get("latestProgress"), "Sample requested", 1000),
        updated_at_source=utc_today(),
        next_step=clean_text(payload.get("nextStep"), "Make and review the sample", 1000),
        deadline=to_date(deadline),
        owner=clean_text(payload.get("owner"), actor),
        supplier=clean_text(payload.get("supplier"), "Unassigned"),
        manufacturing_notes=clean_text(payload.get("manufacturingNotes"), "Production not started", 1000),
    )
    if create:
        record_id = f"SMP-{uuid.uuid4()}"
        db.add(ProductionSample(id=record_id, updates=1, created_at=_now(), updated_at=_now(), **values))
    else:
        record_id = clean_text(body.get("recordId"), "general", 120)
        sample = _live_sample(db, record_id)
        if sample is None:
            raise Refused(404, "Sample not found")
        for key, value in values.items():
            setattr(sample, key, value)
        sample.updates = (sample.updates or 0) + 1
        sample.updated_at = _now()
        sample.done_override = None
        sample.done_override_by = None
    return record_id, f"{name} {'created' if create else 'updated'}"


def _sample_status(db, body, payload, actor):
    record_id = clean_text(body.get("recordId"), "general", 120)
    sample = _live_sample(db, record_id)
    if sample is None:
        raise Refused(404, "Sample not found")
    done = payload.get("done")
    if not isinstance(done, bool):
        raise Refused(400, "Done must be true or false")
    sample.done_override, sample.done_override_by = done, actor
    return record_id, "Sample marked Done" if done else "Sample reopened"


# ── Quality control ───────────────────────────────────────────────────────────


def _qc_check(db, body, payload, actor):
    code = _order_record_id(db, body)
    step = next((step for step in QC_STEPS if step["id"] == payload.get("step")), None)
    item_number = js_number(payload.get("item")) if "item" in payload else float("nan")
    result = payload.get("result")
    if (
        step is None
        or not float(item_number).is_integer()
        or not 0 <= item_number < len(step["checks"])
        or result not in ("Pending", "Pass", "Fail", "N/A")
    ):
        raise Refused(400, "Invalid checklist item")
    item = int(item_number)
    order = _order_by_code(db, code)
    if order is None:
        raise Refused(404, "Order not found")
    notes = clean_text(payload.get("notes"), "", 1000)
    if result in ("Fail", "N/A") and not notes:
        raise Refused(400, "Add a note explaining the failure or why this check does not apply")
    check = db.scalar(
        select(ProductionQcCheck).where(
            ProductionQcCheck.order_id == order.id, ProductionQcCheck.step == step["id"], ProductionQcCheck.item == item
        )
    )
    if check is None:
        check = ProductionQcCheck(order_id=order.id, step=step["id"], item=item)
        db.add(check)
    check.result, check.notes, check.checked_by, check.updated_at = result, notes, actor, _now()
    return code, f"{step['name']}: {step['checks'][item]} — {result}"


_ACTIONS = {
    "create_phase": _create_phase,
    "assign_phase": _assign_phase,
    "create_order": _create_order,
    "update_order": _update_order,
    "create_supplier": _create_supplier,
    "supplier_update": _supplier_update,
    "approve_payment": _approve_payment,
    "shared_update": _shared_update,
    "create_task": _create_task,
    "update_task": _update_task,
    "confirm_task": lambda db, body, payload, actor: _confirm_or_reopen(db, body, payload, actor, confirm=True),
    "reopen_task": lambda db, body, payload, actor: _confirm_or_reopen(db, body, payload, actor, confirm=False),
    "delete_task": _delete_task,
    "create_sample": lambda db, body, payload, actor: _save_sample(db, body, payload, actor, create=True),
    "update_sample": lambda db, body, payload, actor: _save_sample(db, body, payload, actor, create=False),
    "sample_status": _sample_status,
    "qc_check": _qc_check,
}

assert set(_ACTIONS) == set(NEEDS) == set(MODULE_OF)  # noqa: S101 - one list each, kept in step
