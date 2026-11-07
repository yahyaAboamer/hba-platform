"""Move Production's data from the ChatGPT export into HBA's database (ADR 0076).

A one-off, run once on staging from an export and once on production from
the final export at switch-over. **The export holds people's names: it stays
outside the repository**, and so do the two fixture files made from it.

    DATABASE_URL=… python scripts/production_import.py \\
        --export  <export>/data/workspace.json \\
        --lists   <private>/fixture-lists.json \\
        --texts   <private>/fixture-texts.json \\
        --live-state <private>/live-state.json \
        [--replace] [--check-only]

- Refuses to write over Production data already there unless `--replace`,
  which empties Production's tables first, in the same transaction.
- `--live-state` is the old site's own `/api/state` answer, read the same
  day. Rows made in the same second were listed in an order only its
  database knew; the import records each row's place so the lists read
  exactly as they did.
- `--check-only` writes nothing and compares the database with the export.
- Either way it ends with the reconciliation: every kind counted on both
  sides, and every order, task, sample, supplier and product compared field
  by field. It exits non-zero when anything differs.

What is deliberately not carried over: the old app's accounts, passwords and
sessions (HBA's sign-in replaces them), the IP address and browser on each
activity entry (ADR 0076 decision 9), its settings rows that only recorded
which one-time fixes had run, and the empty tables nothing writes.
"""

import argparse
import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: E402,F401  (every table, for the foreign keys)
from app.db import SessionLocal  # noqa: E402
from app.modules.production.models import (  # noqa: E402
    ProductionActivity,
    ProductionDocument,
    ProductionFixture,
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
from app.modules.production.services.js import pounds_to_piastres  # noqa: E402

#: Children first, so emptying respects every foreign key.
TABLES = (
    ProductionStageUpdate, ProductionOrderStage, ProductionQcCheck, ProductionDocument, ProductionActivity,
    ProductionOrder, ProductionTask, ProductionSample, ProductionProduct, ProductionSupplier,
    ProductionSupplierCategory, ProductionPhase, ProductionFixture,
)


def moment(value: str | None) -> datetime | None:
    """The old database's times: "2026-10-08 12:56:17" (UTC) or ISO."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text.replace(" ", "T") if "T" not in text else text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def day(value: str | None) -> date | None:
    """A YYYY-MM-DD day. Blank, or the dash a few orders hold, is no date."""
    if not value or len(value) != 10:
        return None
    return date.fromisoformat(value)


def piastres(value) -> int:
    return pounds_to_piastres(float(value or 0))


def parse_json(value, fallback):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return fallback
    return parsed if parsed is not None else fallback


def task_confirmations(activity: list[dict]) -> dict[str, tuple[str, dict, str]]:
    """Each task's latest confirm or reopen, in the order rows were written."""
    latest: dict[str, tuple[str, dict, str]] = {}
    for row in activity:
        if row["action"] in ("confirm_task", "reopen_task"):
            latest[row["record_id"]] = (row["action"], parse_json(row.get("new_value_json"), {}), row["created_at"])
    return latest


def import_all(db: Session, tables: dict, lists: dict, texts: dict, live: dict) -> None:
    place = {
        section: {row[key]: index for index, row in enumerate(live.get(section, []))}
        for section, key in (("orders", "id"), ("suppliers", "code"), ("tasks", "id"))
    }
    settings = tables["system_settings"]
    phases = {}
    for row in settings:
        if row["category"] == "Drop Phases":
            value = parse_json(row["value_json"], {})
            if isinstance(value.get("id"), str) and isinstance(value.get("name"), str):
                phases[value["id"]] = ProductionPhase(id=value["id"], name=value["name"], created_at=moment(row["created_at"]))
    db.add_all(phases.values())
    assignment = {}
    tracker_model = {}
    for row in settings:
        value = parse_json(row["value_json"], {})
        if row["category"] == "Order Phases" and isinstance(value.get("phaseId"), str):
            assignment[row["key"].removeprefix("drop_order_phase:")] = value["phaseId"]
        if row["category"] == "Tracker source" and row["key"].startswith("tracker_source:") and value.get("model"):
            tracker_model[row["key"].removeprefix("tracker_source:")] = value["model"]

    db.add_all(
        ProductionSupplierCategory(id=row["id"], name=row["name"], created_at=moment(row["created_at"]))
        for row in tables["supplier_categories"]
    )
    db.flush()
    db.add_all(
        ProductionSupplier(
            id=row["id"], code=row["code"], name=row["name"], category_id=row["category_id"],
            contact_person=row["contact_person"], phone=row["phone"], whatsapp=row["whatsapp"], city=row["city"],
            payment_terms=row["payment_terms"], normal_lead_time_days=row["normal_lead_time_days"],
            maximum_capacity=row["maximum_capacity"], active=bool(row["active"]),
            legacy_position=place["suppliers"].get(row["code"]),
            services=parse_json(row.get("services_json"), None), notes=row["notes"],
            created_at=moment(row["created_at"]), updated_at=moment(row["updated_at"]) or moment(row["created_at"]),
            deleted_at=moment(row["deleted_at"]),
        )
        for row in tables["suppliers"]
    )
    db.add_all(
        ProductionProduct(
            id=row["id"], style_code=row["style_code"], name=row["name"], category=row["category"],
            collection=row["collection"], status=row["status"], gsm=row["gsm"],
            target_production_cost_piastres=piastres(row["target_production_cost"]),
            created_at=moment(row["created_at"]), updated_at=moment(row["updated_at"]) or moment(row["created_at"]),
            deleted_at=moment(row["deleted_at"]),
        )
        for row in tables["products"]
    )
    db.flush()
    for row in tables["production_orders"]:
        phase = assignment.get(row["id"]) or None
        db.add(
            ProductionOrder(
                id=row["id"], code=row["code"], product_id=row["product_id"], collection=row["collection"],
                color=row["color"], tracker_order_number=row["tracker_order_number"],
                tracker_model=tracker_model.get(row["id"]), fabric=row["fabric"],
                fabric_kg=Decimal(str(row["fabric_kg"])) if row["fabric_kg"] is not None else None,
                size_breakdown=parse_json(row["size_breakdown_json"] or "{}", {}),
                total_ordered_quantity=row["total_ordered_quantity"] or 0,
                actual_accepted_quantity=row["actual_accepted_quantity"],
                progress_percentage=row["progress_percentage"] or 0, current_stage_name=row["current_stage_name"],
                status=row["status"], priority=row["priority"],
                target_unit_cost_piastres=piastres(row["target_unit_cost"]),
                target_total_cost_piastres=piastres(row["target_total_cost"]),
                actual_total_cost_piastres=piastres(row["actual_total_cost"]),
                target_delivery_date=day(row["target_delivery_date"]), planned_start_date=day(row["planned_start_date"]),
                planned_completion_date=day(row["planned_completion_date"]),
                forecast_completion_date=day(row["forecast_completion_date"]),
                actual_completion_date=day(row["actual_completion_date"]), delay_days=row["delay_days"] or 0,
                notes=row["notes"], blocking_reason=row["blocking_reason"],
                cpo_approval_status=row["cpo_approval_status"], main_manufacturer_id=row["main_manufacturer_id"],
                phase_id=phase if phase in phases else None, legacy_position=place["orders"].get(row["id"]),
                created_at=moment(row["created_at"]), updated_at=moment(row["updated_at"]) or moment(row["created_at"]),
                deleted_at=moment(row["deleted_at"]),
            )
        )
    confirmations = task_confirmations(tables["activity_logs"])
    for row in tables["production_tasks"]:
        action, details, at = confirmations.get(row["id"], ("", {}, ""))
        confirmed = action == "confirm_task"
        db.add(
            ProductionTask(
                id=row["id"], name=row["name"], supplier=row["supplier"], supplier_type=row["supplier_type"],
                stage=row["stage"], next_action=row["next_action"], owner=row["owner"],
                action_date=day(row["action_date"]), deadline=day(row["deadline"]), progress=row["progress"] or 0,
                priority=row["priority"], confirmed_at=moment(at) if confirmed else None,
                confirmed_by=details.get("actor") if confirmed else None,
                legacy_position=place["tasks"].get(row["id"]),
                created_at=moment(row["created_at"]), updated_at=moment(row["updated_at"]) or moment(row["created_at"]),
                deleted_at=moment(row["deleted_at"]),
            )
        )
    statuses = {row["sample_id"]: row for row in tables["sample_status"]}
    for row in tables["samples_tracker"]:
        status = statuses.get(row["id"])
        db.add(
            ProductionSample(
                id=row["id"], name=row["name"], material=row["material"], priority=row["priority"],
                progress=row["progress"] or 0, stage=row["stage"], latest_progress=row["latest_progress"],
                updated_at_source=day(row["updated_at_source"]), next_step=row["next_step"],
                deadline=day(row["deadline"]), owner=row["owner"], supplier=row["supplier"],
                approved_by=row["approved_by"], approval_date=day(row["approval_date"]),
                manufacturing_notes=row["manufacturing_notes"], updates=row["updates"] or 0,
                done_override=bool(status["done"]) if status else None,
                done_override_by=status["updated_by"] if status else None,
                created_at=moment(row["created_at"]), updated_at=moment(row["updated_at"]) or moment(row["created_at"]),
                deleted_at=moment(row["deleted_at"]),
            )
        )
    db.flush()
    orders_by_code = {row["code"]: row["id"] for row in tables["production_orders"]}
    for row in tables["order_qc_checks"]:
        db.add(
            ProductionQcCheck(
                order_id=orders_by_code[row["order_code"]], step=row["step"], item=row["item"], result=row["result"],
                notes=row["notes"] or "", checked_by=row["checked_by"], updated_at=moment(row["updated_at"]),
            )
        )
    for row in tables["activity_logs"]:
        db.add(
            ProductionActivity(
                id=row["id"], action=row["action"], module=row["module"], record_id=row["record_id"],
                old_value=parse_json(row.get("old_value_json"), None),
                details=parse_json(row.get("new_value_json"), {}), created_at=moment(row["created_at"]),
            )
        )
    db.add_all(
        [
            ProductionFixture(key="lists", value=lists),
            ProductionFixture(key="texts", value=texts.get("texts", {})),
            ProductionFixture(key="textLists", value=texts.get("textLists", {})),
        ]
    )
    db.flush()


# ── Reconciliation ────────────────────────────────────────────────────────────


def _count(db: Session, model, *where) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


def reconcile(db: Session, tables: dict, lists: dict) -> list[str]:
    """Every difference between the export and the database, in words."""
    problems: list[str] = []
    settings = tables["system_settings"]
    pairs = [
        ("orders", len(tables["production_orders"]), _count(db, ProductionOrder)),
        ("products", len(tables["products"]), _count(db, ProductionProduct)),
        ("samples", len(tables["samples_tracker"]), _count(db, ProductionSample)),
        ("suppliers", len(tables["suppliers"]), _count(db, ProductionSupplier)),
        ("supplier categories", len(tables["supplier_categories"]), _count(db, ProductionSupplierCategory)),
        ("tasks (with deleted)", len(tables["production_tasks"]), _count(db, ProductionTask)),
        ("tasks deleted", sum(1 for r in tables["production_tasks"] if r["deleted_at"]),
         _count(db, ProductionTask, ProductionTask.deleted_at.is_not(None))),
        ("phases", sum(1 for r in settings if r["category"] == "Drop Phases"), _count(db, ProductionPhase)),
        # An order moved back to "Unassigned" kept a row with an empty phase.
        ("orders in a phase", sum(
            1 for r in settings
            if r["category"] == "Order Phases" and parse_json(r["value_json"], {}).get("phaseId")
        ),
         _count(db, ProductionOrder, ProductionOrder.phase_id.is_not(None))),
        ("activity", len(tables["activity_logs"]), _count(db, ProductionActivity)),
        ("QC checks", len(tables["order_qc_checks"]), _count(db, ProductionQcCheck)),
        ("QC inspections (never written)", len(tables["qc_inspections"]), 0),
        ("documents and photos", len(tables["documents"]), _count(db, ProductionDocument)),
        ("sample Done overrides", len(tables["sample_status"]),
         _count(db, ProductionSample, ProductionSample.done_override.is_not(None))),
        ("costs (never written)", len(tables["production_costs"]), 0),
        ("supplier invoices (never written)", len(tables["supplier_invoices"]), 0),
        ("supplier payments (never written)", len(tables["supplier_payments"]), 0),
        ("order stages", len(tables["production_order_stages"]), _count(db, ProductionOrderStage)),
        ("stage updates", len(tables["stage_updates"]), _count(db, ProductionStageUpdate)),
    ]
    print(f"{'kind':38} {'export':>7} {'HBA':>7}")
    for kind, exported, here in pairs:
        mark = "" if exported == here else "   <- differs"
        print(f"{kind:38} {exported:7} {here:7}{mark}")
        if exported != here:
            problems.append(f"{kind}: export {exported}, HBA {here}")
    money = sum(
        piastres(r[k]) for r in tables["production_orders"]
        for k in ("target_unit_cost", "target_total_cost", "actual_total_cost")
    )
    money_here = db.scalar(
        select(func.coalesce(func.sum(
            ProductionOrder.target_unit_cost_piastres + ProductionOrder.target_total_cost_piastres
            + ProductionOrder.actual_total_cost_piastres), 0))
    )
    print(f"{'order cost figures, piastres':38} {money:7} {money_here:7}")
    if money != money_here:
        problems.append("order cost figures differ")
    stored = db.get(ProductionFixture, "lists")
    if stored is None or stored.value != lists:
        problems.append("the fixed content differs from the file")

    def compare(name, rows, model, fields):
        here = {row.id: row for row in db.scalars(select(model))}
        for row in rows:
            mine = here.get(row["id"])
            if mine is None:
                problems.append(f"{name} {row['id']}: missing")
                continue
            for theirs, ours, convert in fields:
                expected = convert(row[theirs]) if convert else row[theirs]
                actual = getattr(mine, ours)
                if isinstance(actual, Decimal):
                    actual = float(actual)
                    expected = float(expected) if expected is not None else expected
                if expected != actual:
                    problems.append(f"{name} {row['id']}.{ours}: export {expected!r}, HBA {actual!r}")

    text = [("name", "name", None)]
    compare("order", tables["production_orders"], ProductionOrder, [
        ("code", "code", None), ("status", "status", None), ("total_ordered_quantity", "total_ordered_quantity", None),
        ("progress_percentage", "progress_percentage", None), ("main_manufacturer_id", "main_manufacturer_id", None),
        ("product_id", "product_id", None), ("color", "color", None), ("notes", "notes", None),
        ("planned_completion_date", "planned_completion_date", day),
        ("forecast_completion_date", "forecast_completion_date", day),
        ("size_breakdown_json", "size_breakdown", lambda v: parse_json(v or "{}", {})),
    ])
    compare("task", tables["production_tasks"], ProductionTask, [
        *text, ("stage", "stage", None), ("progress", "progress", None), ("owner", "owner", None),
        ("deadline", "deadline", day), ("deleted_at", "deleted_at", moment),
    ])
    compare("sample", tables["samples_tracker"], ProductionSample, [
        *text, ("stage", "stage", None), ("progress", "progress", None), ("supplier", "supplier", None),
        ("updates", "updates", None), ("deadline", "deadline", day),
    ])
    compare("supplier", tables["suppliers"], ProductionSupplier, [*text, ("code", "code", None), ("city", "city", None)])
    compare("product", tables["products"], ProductionProduct, [*text, ("style_code", "style_code", None)])
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--export", required=True, type=Path)
    parser.add_argument("--lists", required=True, type=Path)
    parser.add_argument("--texts", required=True, type=Path)
    parser.add_argument("--live-state", required=True, type=Path)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    tables = json.loads(args.export.read_text(encoding="utf-8"))["tables"]
    lists = json.loads(args.lists.read_text(encoding="utf-8"))
    texts = json.loads(args.texts.read_text(encoding="utf-8"))
    live = json.loads(args.live_state.read_text(encoding="utf-8"))
    if tables["documents"]:
        print("The export lists uploaded files; move them into the bucket first (not handled here).")
        return 2
    with SessionLocal() as db:
        if not args.check_only:
            if _count(db, ProductionOrder) or _count(db, ProductionActivity):
                if not args.replace:
                    print("Production already holds data. Pass --replace to empty it and import again.")
                    return 2
                if _count(db, ProductionDocument):
                    # Photos and documents uploaded here exist nowhere in the
                    # export; emptying would lose them and orphan their files.
                    print("Production holds uploaded files; --replace would lose them. Nothing was changed.")
                    return 2
                for model in TABLES:
                    db.execute(delete(model))
            import_all(db, tables, lists, texts, live)
        problems = reconcile(db, tables, lists)
        if problems:
            db.rollback()
            print(f"\n{len(problems)} difference(s); nothing was written:" if not args.check_only else "")
            for problem in problems[:50]:
                print(" -", problem)
            return 1
        if not args.check_only:
            db.commit()
            print("\nImported and reconciled: every count and every compared field matches.")
        else:
            print("\nReconciled: every count and every compared field matches.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
