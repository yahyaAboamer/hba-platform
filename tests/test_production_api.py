"""Production behind HBA's sign-in, answering as its old server did (ADR 0076).

Every name and record here is invented; the real data never enters the
repository.
"""

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

from app.core.passwords import hash_password
from app.core.permissions import DEPARTMENT_LEVELS, access_words, level_in
from app.db import SessionLocal, engine
from app.main import app
from app.modules.production.models import (
    ProductionActivity,
    ProductionDocument,
    ProductionFixture,
    ProductionOrder,
    ProductionPhase,
    ProductionProduct,
    ProductionSample,
    ProductionSupplier,
    ProductionTask,
)
from app.modules.production.services import files
from app.modules.production.services.qc import QC_STEPS
from app.shared.models.audit import AuditEvent

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "quiet-harbour-lantern"
BOOTSTRAP = {"email": "owner@example.com", "display_name": "Owner", "password": PASSWORD}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


@pytest.fixture()
def owner(fresh_database):
    with TestClient(app) as client:
        response = client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield client


def _person(email: str, *roles: str, name: str = "Somebody") -> TestClient:
    with engine.begin() as connection:
        account_id = connection.execute(
            text(
                "INSERT INTO user_account (email, password_hash, status, display_name) "
                "VALUES (:e, :p, 'active', :n) RETURNING id"
            ),
            {"e": email, "p": hash_password(PASSWORD), "n": name},
        ).scalar_one()
        for role in roles:
            connection.execute(
                text("INSERT INTO role_assignment (user_account_id, role) VALUES (:u, :r)"),
                {"u": account_id, "r": role},
            )
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    return client


def _seed() -> None:
    """A small Production: two suppliers, two products, an order, a task, a sample."""
    at = datetime(2026, 9, 4, 17, 0, tzinfo=timezone.utc)
    with SessionLocal() as db:
        db.add(ProductionPhase(id="phase-one", name="Phase One", created_at=at))
        db.add(ProductionSupplier(id="sup-a", code="SUP-A", name="Mill A", active=True, created_at=at, updated_at=at))
        db.add(ProductionSupplier(id="sup-b", code="SUP-B", name="Mill B", active=True, created_at=at, updated_at=at))
        db.add(ProductionProduct(id="prd-a", style_code="STY-A", name="Plain Pants", collection="Autumn",
                                 status="Active", created_at=at, updated_at=at))
        db.add(ProductionProduct(id="prd-b", style_code="STY-B", name="Plain Top", created_at=at, updated_at=at))
        db.flush()
        db.add(ProductionOrder(
            id="po-1", code="HBA-PO-807", product_id="prd-a", collection="Autumn", color="Black",
            size_breakdown={"S": 4, "M": 6}, total_ordered_quantity=10, progress_percentage=50,
            current_stage_name="In Production", status="In Progress", priority="High",
            planned_start_date=date(2026, 9, 1), planned_completion_date=date(2026, 9, 20),
            forecast_completion_date=date(2026, 9, 25), delay_days=5, main_manufacturer_id="sup-a",
            phase_id="phase-one", created_at=at, updated_at=at,
        ))
        db.add(ProductionTask(id="PRD-1", name="Collect cuts", stage="Sample", owner="Planner",
                              action_date=date(2026, 9, 5), progress=0, priority="High", created_at=at, updated_at=at))
        db.add(ProductionSample(id="SMP-1", name="Zip top", stage="In Progress", progress=40, updates=2,
                                updated_at_source=date(2026, 9, 3), created_at=at, updated_at=at))
        db.add(ProductionFixture(key="texts", value={"defaultSampleOwner": "Planner"}))
        db.add(ProductionFixture(key="lists", value={"notifications": [{"id": "n0", "title": "Hello"}]}))
        db.commit()


def _act(client: TestClient, **body):
    return client.post("/api/production/actions", json=body)


# ── Who may come in ───────────────────────────────────────────────────────────


def test_signed_out_is_refused(fresh_database):
    with TestClient(app) as client:
        assert client.get("/api/production/state").status_code == 401


def test_staff_without_production_are_refused_in_the_old_shape(owner):
    inbox = _person("cs@example.com", "customer_service")
    answer = inbox.get("/api/production/state")
    assert answer.status_code == 403
    assert answer.json() == {"error": "Your account does not have access to Production"}


@pytest.mark.parametrize(
    ("role", "shown", "label", "checks"),
    [
        ("production_viewer", "viewer", None, None),
        # ADR 0077: staff keep the staff screens and get the QC checklist.
        ("production_staff", "production", "Production staff", True),
        ("production_manager", "admin", "Production manager", None),
    ],
)
def test_each_level_is_shown_to_the_screens_as_an_old_role(owner, role, shown, label, checks):
    person = _person(f"{role}@example.com", role, name="Lina")
    user = person.get("/api/production/session").json()["user"]
    assert user["role"] == shown
    assert user["name"] == "Lina"
    assert user.get("roleLabel") == label
    assert user.get("canCheckQc") == checks


def test_the_owner_is_the_old_admin(owner):
    assert owner.get("/api/production/session").json()["user"]["role"] == "admin"


def test_signing_in_inside_production_is_refused(owner):
    answer = owner.post("/api/production/session", json={"action": "login", "username": "x", "password": "y"})
    assert answer.status_code == 400
    assert "HBA account" in answer.json()["error"]


def test_a_write_without_the_csrf_token_is_refused(owner):
    _seed()
    del owner.headers["X-CSRF-Token"]
    assert _act(owner, action="create_phase", payload={"name": "Two"}).status_code == 401


# ── The state, as the old server wrote it ─────────────────────────────────────


def test_the_state_has_the_old_keys_in_the_old_order(owner):
    _seed()
    state = owner.get("/api/production/state")
    assert state.status_code == 200
    assert state.headers["cache-control"] == "no-store"
    assert list(state.json()) == [
        "phases", "samples", "products", "sampleStatuses", "qcChecks", "orders", "suppliers", "activity",
        "tasks", "revision", "user",
    ]


def test_an_order_reads_as_it_did(owner):
    _seed()
    order = owner.get("/api/production/state").json()["orders"][0]
    assert order["code"] == "HBA-PO-807"
    assert order["legacyCode"] == "807"
    assert "trackerOrderNumber" not in order
    assert order["phaseName"] == "Phase One"
    assert order["supplier"] == "Mill A"
    assert order["startDate"] == "01 Sept 2026"
    assert order["forecastDeliveryISO"] == "2026-09-25"
    assert order["sizeBreakdown"] == {"S": 4, "M": 6}
    assert order["progress"] == 50
    assert [stage["shortName"] for stage in order["stages"]] == ["Logged", "Production", "QC / Delivery"]
    assert "actual" not in order["stages"][1]


def test_a_supplier_with_no_lead_time_reads_one_day_as_before(owner):
    _seed()
    supplier = next(s for s in owner.get("/api/production/state").json()["suppliers"] if s["code"] == "SUP-A")
    assert supplier["leadTime"] == "1 days"
    assert supplier["activeOrders"] == 1
    assert supplier["capacity"] == "Capacity not set"


def test_products_are_listed_in_the_old_byte_order(owner):
    # SQLite sorted names byte by byte: capitals before small letters, and a
    # space or dash counts. Language-aware sorting would give the opposite here.
    _seed()
    at = datetime(2026, 9, 4, 17, 0, tzinfo=timezone.utc)
    with SessionLocal() as db:
        for key, name in (("x1", "basic tee"), ("x2", "Zip Hoodie"), ("x3", "Plain-Pants")):
            db.add(ProductionProduct(id=key, style_code=key.upper(), name=name, created_at=at, updated_at=at))
        db.commit()
    statements: list[str] = []

    def keep(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", keep)
    try:
        names = [product["name"] for product in owner.get("/api/production/state").json()["products"]]
    finally:
        event.remove(engine, "before_cursor_execute", keep)
    assert names == sorted(names, key=lambda name: name.encode("utf-8"))
    assert names.index("Zip Hoodie") < names.index("basic tee")
    # A database set up with byte order passes the lines above anyway (this
    # one did, staging did not), so the query itself must ask for it.
    products = [s for s in statements if "FROM production_product" in s and "ORDER BY" in s]
    assert products and all('COLLATE "C"' in s.split("ORDER BY", 1)[1] for s in products)


def test_the_revision_is_initial_until_something_is_logged(owner):
    _seed()
    assert owner.get("/api/production/state").json()["revision"] == "initial"
    _act(owner, action="create_phase", payload={"name": "Two"})
    assert owner.get("/api/production/state").json()["revision"] != "initial"


def test_the_fixed_content_comes_whole(owner):
    _seed()
    fixtures = owner.get("/api/production/fixtures").json()
    assert fixtures["lists"]["notifications"][0]["title"] == "Hello"
    assert fixtures["texts"]["defaultSampleOwner"] == "Planner"


# ── Actions ───────────────────────────────────────────────────────────────────


def test_every_change_is_logged_for_the_screens_and_audited_for_the_platform(owner):
    _seed()
    answer = _act(owner, action="create_task", payload={"name": "Book the van", "deadline": "2026-09-30"})
    assert answer.status_code == 201
    body = answer.json()
    assert body["ok"] is True and body["summary"] == "Book the van created"
    with SessionLocal() as db:
        activity = db.scalar(select(ProductionActivity).where(ProductionActivity.record_id == body["recordId"]))
        assert activity.details["actor"] == "Owner"
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "production.create_task"))
        assert event.department == "production"
        assert event.subject == f"production:{body['recordId']}"


def test_a_new_order_gets_the_days_code(owner):
    _seed()
    answer = _act(owner, action="create_order", product="Plain Pants", quantity=30, manufacturer="Mill B",
                  phaseId="phase-one", targetDelivery="2026-12-01")
    assert answer.status_code == 201, answer.text
    assert re.fullmatch(r"HBA-PO-\d{6}-001", answer.json()["recordId"])
    assert answer.json()["summary"] == "Plain Pants · 30 units"
    again = _act(owner, action="create_order", product="Plain Pants", quantity=5)
    assert again.json()["recordId"].endswith("-002")


def test_an_unknown_product_is_refused_as_before(owner):
    _seed()
    answer = _act(owner, action="create_order", product="Nothing")
    assert answer.status_code == 409
    assert answer.json() == {"error": "Selected product was not found"}


def test_an_order_edit_rewrites_every_field_and_finds_the_old_code(owner):
    _seed()
    answer = _act(owner, action="update_order", recordId="807",
                  payload={"quantity": "10", "status": "Delayed", "size_S": "5", "size_M": "5", "size_L": "0",
                           "size_XL": "0", "size_XXL": "0", "targetCost": "12.5"})
    assert answer.status_code == 201, answer.text
    assert answer.json()["summary"] == "HBA-PO-807 updated · 10 units · Delayed"
    with SessionLocal() as db:
        order = db.get(ProductionOrder, "po-1")
        # Left out, so back to its default - the old server did exactly this.
        assert float(order.progress_percentage) == 0
        assert order.main_manufacturer_id is None
        assert order.collection == "HBA Production"
        # Money in integer piastres (ADR 0002).
        assert order.target_unit_cost_piastres == 1250
        assert order.target_total_cost_piastres == 12500
    assert owner.get("/api/production/state").json()["orders"][0]["targetCost"] == 12.5


def test_sizes_must_total_the_quantity(owner):
    _seed()
    answer = _act(owner, action="update_order", recordId="HBA-PO-807",
                  payload={"quantity": "10", "size_S": "3", "size_M": "3"})
    assert answer.status_code == 400
    assert answer.json()["error"] == "Size quantities must be whole numbers and total the order quantity"


def test_a_phase_that_does_not_exist_is_refused(owner):
    _seed()
    answer = _act(owner, action="assign_phase", recordId="807", payload={"phaseId": "nope"})
    assert answer.json() == {"error": "Choose an existing drop phase"}


def test_a_phase_is_made_from_its_name(owner):
    _seed()
    answer = _act(owner, action="create_phase", payload={"name": "Phase Two!"})
    assert answer.json()["recordId"] == "phase-two"


def test_confirming_and_reopening_a_task(owner):
    _seed()
    assert _act(owner, action="confirm_task", recordId="PRD-1").json()["summary"] == "Collect cuts moved to Confirmed"
    task = owner.get("/api/production/state").json()["tasks"][0]
    assert task["confirmed"] is True and task["confirmedBy"] == "Owner" and task["stage"] == "Done"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", task["confirmedAt"])
    _act(owner, action="reopen_task", recordId="PRD-1")
    task = owner.get("/api/production/state").json()["tasks"][0]
    assert task["confirmed"] is False and task["stage"] == "Preparation"


def test_marking_a_sample_done_and_editing_clears_it(owner):
    _seed()
    _act(owner, action="sample_status", recordId="SMP-1", payload={"done": True})
    assert owner.get("/api/production/state").json()["sampleStatuses"] == {"SMP-1": True}
    _act(owner, action="update_sample", recordId="SMP-1", payload={"name": "Zip top", "stage": "On Hold"})
    state = owner.get("/api/production/state").json()
    assert state["sampleStatuses"] == {}
    assert state["samples"][0]["updates"] == 3


def test_staff_record_qc_a_viewer_does_not_and_a_failure_needs_a_note(owner):
    """ADR 0077: the people who produce are the people who check."""
    _seed()
    viewer = _person("viewer@example.com", "production_viewer")
    qc = _person("staff@example.com", "production_staff")
    check = {"step": "cutting", "item": 1, "result": "Fail", "notes": ""}
    assert _act(viewer, action="qc_check", recordId="807", payload=check).status_code == 403
    refused = _act(qc, action="qc_check", recordId="807", payload=check)
    assert refused.json()["error"] == "Add a note explaining the failure or why this check does not apply"
    saved = _act(qc, action="qc_check", recordId="807", payload={**check, "notes": "Short"})
    assert saved.json()["summary"] == "Cutting & measurements: Size quantities and cut panels counted — Fail"
    assert owner.get("/api/production/state").json()["qcChecks"][0]["orderCode"] == "HBA-PO-807"


def test_a_viewer_changes_nothing(owner):
    _seed()
    viewer = _person("viewer@example.com", "production_viewer")
    assert _act(viewer, action="create_phase", payload={"name": "X"}).status_code == 403


def test_only_the_manager_handles_suppliers(owner):
    _seed()
    staff = _person("staff@example.com", "production_staff")
    manager = _person("manager@example.com", "production_manager")
    supplier = {"action": "create_supplier", "name": "Trim Works", "category": "Packaging"}
    assert staff.post("/api/production/actions", json=supplier).status_code == 403
    made = manager.post("/api/production/actions", json=supplier)
    assert made.status_code == 201 and made.json()["recordId"] == "SUP-003"


def test_approving_a_payment_is_the_owners_alone(owner):
    _seed()
    manager = _person("manager@example.com", "production_manager")
    assert _act(manager, action="approve_payment", recordId="INV-1").status_code == 403
    assert _act(owner, action="approve_payment", recordId="INV-1").json()["summary"] == "INV-1 approved for payment"


def test_an_unknown_action(owner):
    _seed()
    staff = _person("staff@example.com", "production_staff")
    assert _act(staff, action="nothing").status_code == 403
    assert _act(owner, action="nothing").json() == {"error": "Unknown action"}


def test_the_supplier_portal_files_a_proposal_for_review(owner):
    _seed()
    answer = _act(owner, action="supplier_update", recordId="807",
                  payload={"status": "In Progress", "completed": 4, "forecast": "2026-10-01"})
    assert answer.json()["summary"] == "4 completed · In Progress"


# ── Photos ────────────────────────────────────────────────────────────────────


class _Bucket:
    def __init__(self):
        self.files = {}

    def put(self, key, content, content_type):
        self.files[key] = content

    def get(self, key):
        return self.files[key]


@pytest.fixture()
def bucket(monkeypatch):
    store = _Bucket()
    monkeypatch.setattr(files, "file_bucket", lambda: store)
    monkeypatch.setattr("app.modules.production.api.file_bucket", lambda: store)
    return store


def test_an_order_photo_is_kept_and_served_to_production_only(owner, bucket):
    _seed()
    saved = owner.post("/api/production/order-photos", data={"order": "807"},
                       files={"file": ("front.png", PNG, "image/png")})
    assert saved.status_code == 201, saved.text
    photo = saved.json()["photo"]
    assert photo["url"] == f"/api/production/order-photos/{photo['id']}"
    assert all(key.startswith("production/order-photos/po-1/") for key in bucket.files)
    assert owner.get("/api/production/order-photos", params={"order": "HBA-PO-807"}).json()["photos"][0]["id"] == photo["id"]
    assert owner.get(photo["url"]).content == PNG
    outsider = _person("cs@example.com", "customer_service")
    assert outsider.get(photo["url"]).status_code == 403


def test_a_photo_must_be_an_image_and_a_viewer_cannot_upload(owner, bucket):
    _seed()
    refused = owner.post("/api/production/sample-photos", data={"sample": "SMP-1"},
                         files={"file": ("x.png", b"not an image at all", "image/png")})
    assert refused.json() == {"error": "Use a JPG, PNG, WebP or GIF photo"}
    viewer = _person("viewer@example.com", "production_viewer")
    assert viewer.post("/api/production/sample-photos", data={"sample": "SMP-1"},
                       files={"file": ("x.png", PNG, "image/png")}).status_code == 403


def test_a_sample_photo_shows_on_the_sample(owner, bucket):
    _seed()
    owner.post("/api/production/sample-photos", data={"sample": "SMP-1"}, files={"file": ("a.png", PNG, "image/png")})
    sample = owner.get("/api/production/state").json()["samples"][0]
    assert sample["photoCount"] == 1
    assert sample["photoUrl"].startswith("/api/production/sample-photos/")


def test_documents_are_listed_after_upload(owner, bucket):
    _seed()
    saved = owner.post("/api/production/documents", data={"module": "Documents", "recordId": "general"},
                       files={"file": ("tech pack.pdf", b"%PDF-1.4", "application/pdf")})
    assert saved.status_code == 201
    listed = owner.get("/api/production/documents").json()["documents"]
    assert listed[0]["name"] == "tech pack.pdf"
    with SessionLocal() as db:
        assert db.scalar(select(ProductionDocument.storage_key)).startswith("production/documents/documents/general/")


# ── Levels and the screens' own lists ─────────────────────────────────────────


def test_production_offers_viewer_staff_and_manager_and_no_qc_level():
    """ADR 0077: QC is part of staff, not a level of its own."""
    assert set(DEPARTMENT_LEVELS["production"]) == {"viewer", "staff", "manager"}
    assert all("qc" not in levels for levels in DEPARTMENT_LEVELS.values())
    assert level_in("production", {"production_staff"}) == "staff"
    assert access_words({"production_manager", "customer_service"}) == "Production manager · Inbox staff"


def test_the_qc_checklist_is_the_one_the_screens_carry():
    source = (ROOT / "production-ui/src/lib/qc-checklist.ts").read_text(encoding="utf-8")
    for step in QC_STEPS:
        assert f'id: "{step["id"]}", name: "{step["name"]}"' in source
        for check in step["checks"]:
            assert f'"{check}"' in source


def test_the_screens_carry_no_fixed_content():
    """The fixed lists come from the database (ADR 0076 decision 3): in the
    code each is an empty array, so no name can be committed with them."""
    source = (ROOT / "production-ui/src/lib/demo-data.ts").read_text(encoding="utf-8")
    declared = [
        (name, value)
        for name, value in re.findall(r"^export const (\w+)[^=]*= (.*);$", source, flags=re.MULTILINE)
        if name != "fixtureListNames"
    ]
    assert len(declared) >= 18
    assert all(value == "[]" for _, value in declared), [name for name, value in declared if value != "[]"]


def test_an_import_that_does_not_reconcile_writes_nothing(fresh_database, tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("production_import", ROOT / "scripts/production_import.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    empty = {name: [] for name in (
        "system_settings", "supplier_categories", "suppliers", "products", "production_orders",
        "production_tasks", "activity_logs", "samples_tracker", "sample_status", "order_qc_checks",
        "qc_inspections", "documents", "production_costs", "supplier_invoices", "supplier_payments",
        "production_order_stages", "stage_updates",
    )}
    tables = {**empty,
              "products": [{"id": "p", "style_code": "S", "name": "N", "category": None, "collection": None,
                            "status": None, "gsm": None, "target_production_cost": 0,
                            "created_at": "2026-09-04 17:00:00", "updated_at": None, "deleted_at": None}],
              "activity_logs": [{"id": "a", "action": "logged_tasks", "module": "M", "record_id": "r",
                                 "old_value_json": None, "new_value_json": json.dumps({"actor": "X"}),
                                 "created_at": "2026-09-05 17:00:00", "ip_address": "1.2.3.4", "user_agent": "UA"}]}
    for name, content in {"export.json": {"tables": tables}, "lists.json": {}, "texts.json": {},
                          "live.json": {}}.items():
        (tmp_path / name).write_text(json.dumps(content), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["x", "--export", str(tmp_path / "export.json"), "--lists",
                                     str(tmp_path / "lists.json"), "--texts", str(tmp_path / "texts.json"),
                                     "--live-state", str(tmp_path / "live.json")])
    assert module.main() == 0
    with SessionLocal() as db:
        activity = db.get(ProductionActivity, "a")
        assert activity.details == {"actor": "X"}
        assert db.scalar(select(ProductionProduct.name)) == "N"
    # A second run without --replace refuses rather than doubling anything.
    assert module.main() == 2


def _import_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("production_import", ROOT / "scripts/production_import.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_import(module, tmp_path, monkeypatch, tables, live):
    for name, content in {"export.json": {"tables": tables}, "lists.json": {}, "texts.json": {},
                          "live.json": live}.items():
        (tmp_path / name).write_text(json.dumps(content), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["x", "--export", str(tmp_path / "export.json"), "--lists",
                                     str(tmp_path / "lists.json"), "--texts", str(tmp_path / "texts.json"),
                                     "--live-state", str(tmp_path / "live.json")])
    return module.main()


def _one_task_export(*, confirmed: bool) -> dict:
    tables = {name: [] for name in (
        "system_settings", "supplier_categories", "suppliers", "products", "production_orders",
        "production_tasks", "activity_logs", "samples_tracker", "sample_status", "order_qc_checks",
        "qc_inspections", "documents", "production_costs", "supplier_invoices", "supplier_payments",
        "production_order_stages", "stage_updates",
    )}
    tables["production_tasks"] = [{
        "id": "t1", "name": "Cut fabric", "supplier": "Supplier A", "supplier_type": "Cutting", "stage": "Preparation",
        "next_action": "", "owner": "Person A", "action_date": "2026-10-01", "deadline": "2026-10-09", "progress": 20,
        "priority": "Normal", "created_at": "2026-10-01 09:00:00", "updated_at": None, "deleted_at": None,
    }]
    tables["activity_logs"] = [{"id": "a1", "action": "update_task", "module": "Production Tasks", "record_id": "t1",
                                "old_value_json": None, "new_value_json": json.dumps({"actor": "Person A"}),
                                "created_at": "2026-10-28 01:00:00"}]
    if confirmed:
        tables["production_tasks"][0].update(stage="Done", progress=100)
        tables["activity_logs"].append({
            "id": "a2", "action": "confirm_task", "module": "Production Tasks", "record_id": "t1",
            "old_value_json": None, "new_value_json": json.dumps({"actor": "Person A"}),
            "created_at": "2026-10-28 02:00:00"})
    return tables


def _live_task(**fields) -> dict:
    task = {"id": "t1", "name": "Cut fabric", "confirmed": False, "confirmedAt": "", "confirmedBy": "",
            "stage": "Preparation", "progress": 20}
    task.update(fields)
    return task


def test_a_confirmation_made_after_the_export_is_taken_from_the_live_site(fresh_database, tmp_path, monkeypatch):
    live = {
        "tasks": [_live_task(confirmed=True, confirmedAt="2026-11-06 15:00:48", confirmedBy="Person B",
                             stage="Done", progress=100)],
        "activity": [{"user": "Person B", "action": "confirm task", "module": "Production Tasks", "record": "t1",
                      "old": "—", "next": "Cut fabric moved to Confirmed", "time": "06 Nov, 17:00"}],
    }
    assert _run_import(_import_module(), tmp_path, monkeypatch, _one_task_export(confirmed=False), live) == 0
    with SessionLocal() as db:
        task = db.get(ProductionTask, "t1")
        assert (task.stage, task.progress, task.confirmed_by) == ("Done", 100, "Person B")
        assert task.confirmed_at == datetime(2026, 11, 6, 15, 0, 48, tzinfo=timezone.utc)
        line = db.scalar(select(ProductionActivity).where(ProductionActivity.action == "confirm_task"))
        assert line.details == {"actor": "Person B", "summary": "Cut fabric moved to Confirmed"}
        assert line.created_at == task.confirmed_at


def test_a_later_change_the_import_cannot_date_refuses_it(fresh_database, tmp_path, monkeypatch):
    # Confirmed in the export, no longer confirmed on the site: reopened when, nobody can say.
    live = {"tasks": [_live_task()], "activity": []}
    assert _run_import(_import_module(), tmp_path, monkeypatch, _one_task_export(confirmed=True), live) == 2
    with SessionLocal() as db:
        assert db.get(ProductionTask, "t1") is None


def test_a_confidential_document_is_not_listed_to_a_viewer(owner, bucket):
    _seed()
    owner.post("/api/production/documents", data={"module": "Documents", "recordId": "general", "confidential": "true"},
               files={"file": ("secret.pdf", b"%PDF-1.4", "application/pdf")})
    viewer = _person("viewer@example.com", "production_viewer")
    assert viewer.get("/api/production/documents").json()["documents"] == []
    assert len(owner.get("/api/production/documents").json()["documents"]) == 1


def test_an_upload_of_no_stated_size_is_refused(owner, bucket):
    _seed()
    answer = owner.post(
        "/api/production/order-photos",
        content=b"--x\r\n\r\n--x--\r\n",
        headers={"content-type": "multipart/form-data; boundary=x", "transfer-encoding": "chunked"},
    )
    assert answer.status_code == 413


def test_a_document_cannot_pass_as_a_photo(owner, bucket):
    _seed()
    qc = _person("staff@example.com", "production_staff")
    saved = qc.post(
        "/api/production/documents",
        data={"module": "Samples", "recordId": "SMP-1", "documentType": "Sample photo"},
        files={"file": ("x.png", b"<html>not a photo</html>", "image/png")},
    )
    assert saved.status_code == 201
    assert saved.json()["document"]["documentType"] == "Other"
    assert owner.get("/api/production/sample-photos", params={"sample": "SMP-1"}).json()["photos"] == []
    assert owner.get("/api/production/state").json()["samples"][0]["photoCount"] == 0
