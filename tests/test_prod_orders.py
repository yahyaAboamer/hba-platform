"""Production orders under /api/prod (ADR 0084, batch 1).

Every name and figure here is invented (the money example is the approved
mockup's sample data); the real data never enters the repository.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

from app.core.businesstime import business_date, utcnow
from app.core.passwords import hash_password
from app.db import SessionLocal, engine
from app.main import app
from app.modules.production.models import ProductionSupplier, ProductionSupplierCategory
from app.modules.production.orders import api as orders_api
from app.modules.production.orders.models import (
    ProdDelivery,
    ProdDeliverySize,
    ProdOrder,
    ProdOrderSize,
)
from app.modules.production.orders.services import files as order_files
from app.modules.production.orders.services import orders as service
from app.shared.models.audit import AuditEvent
from app.shared.models.catalogue import Product
from app.shared.models.identity import UserAccount

PASSWORD = "quiet-harbour-lantern"
BOOTSTRAP = {"email": "owner@example.com", "display_name": "Owner", "password": PASSWORD}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40

TODAY = business_date(utcnow())
TARGET = TODAY + timedelta(days=60)

PLANNED = {"S": 150, "M": 300, "L": 300, "XL": 180, "XXL": 70}
CUT = {"S": 148, "M": 292, "L": 290, "XL": 176, "XXL": 66}
INSPECTED = {
    "S": {"passed": 140, "to_fix": 5, "rejected": 3},
    "M": {"passed": 280, "to_fix": 8, "rejected": 4},
    "L": {"passed": 276, "to_fix": 9, "rejected": 5},
    "XL": {"passed": 168, "to_fix": 5, "rejected": 3},
    "XXL": {"passed": 62, "to_fix": 3, "rejected": 1},
}
INSPECTION_REASONS = [
    {"kind": "rejected", "reason": "Stitching", "quantity": 9},
    {"kind": "rejected", "reason": "Print misplaced", "quantity": 5},
    {"kind": "rejected", "reason": "Stain", "quantity": 2},
    {"kind": "to_fix", "reason": "Loose stitching", "quantity": 21},
    {"kind": "to_fix", "reason": "Label", "quantity": 9},
]
FIRST = {"S": 70, "M": 140, "L": 138, "XL": 92, "XXL": 40}
SECOND = {"S": 70, "M": 140, "L": 138, "XL": 76, "XXL": 22}
FIX = {"S": 5, "M": 8, "L": 9, "XL": 5, "XXL": 3}


# ── People ────────────────────────────────────────────────────────────────────


@pytest.fixture()
def owner(fresh_database):
    with TestClient(app) as client:
        response = client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf"]
        _seed()
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


@pytest.fixture()
def staff(owner):
    return _person("qc@example.com", "production_staff", name="QC Manager")


@pytest.fixture()
def viewer(owner):
    return _person("look@example.com", "production_viewer", name="Viewer")


def _seed() -> None:
    with SessionLocal() as db:
        db.add(ProductionSupplierCategory(id="cat-make", name="Manufacturers"))
        db.add(ProductionSupplierCategory(id="cat-print", name="Printing houses"))
        db.flush()
        db.add(ProductionSupplier(id="fac", code="FAC", name="Main factory", category_id="cat-make", active=True))
        db.add(ProductionSupplier(id="prt", code="PRT", name="Print house A", category_id="cat-print", active=True))
        db.add(ProductionSupplier(id="old", code="OLD", name="Closed mill", active=False))
        db.add(Product(shopify_product_id="111", title="Oversized hoodie", status="active"))
        db.add(Product(shopify_product_id="222", title="Retired tee", status="archived"))
        db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _body(**over) -> dict:
    body = {
        "style_name": "Oversized hoodie",
        "colour": "Black",
        "shopify_product_id": "111",
        "factory_id": "fac",
        "fabric_bought_by": "hba",
        "printing": "factory",
        "target_date": TARGET.isoformat(),
        "planned": PLANNED,
        "target_fabric_piastres": 16500,
        "target_manufacturing_piastres": 8500,
        "target_printing_piastres": 3000,
        "target_accessories_piastres": 1200,
        "target_packaging_piastres": 800,
    }
    body.update(over)
    return body


def _new(client: TestClient, **over) -> dict:
    response = client.post("/api/prod/orders", json=_body(**over))
    assert response.status_code == 201, response.text
    return response.json()["order"]


def _ok(response) -> dict:
    assert response.status_code in (200, 201), response.text
    return response.json()["order"]


def _stage(order: dict, key: str) -> dict:
    return next(stage for stage in order["stages"] if stage["key"] == key)


def _day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def _to_cutting(client: TestClient, oid: int, *, repeat: bool = False) -> None:
    if not repeat:
        _ok(client.post(f"/api/prod/orders/{oid}/sample", json={"decision": "approved"}))
    _ok(client.post(f"/api/prod/orders/{oid}/stages/materials/complete", json={}))
    _ok(client.post(f"/api/prod/orders/{oid}/stages/fabric_check/complete", json={"result": "passed"}))
    _ok(client.post(f"/api/prod/orders/{oid}/stages/pattern_check/complete", json={}))


def _cut(client: TestClient, oid: int, promised: str | None = None) -> dict:
    return _ok(
        client.put(
            f"/api/prod/orders/{oid}/cut",
            json={
                "sizes": CUT,
                "promised_date": promised or TARGET.isoformat(),
                "reasons": [
                    {"reason": "Fabric defects", "quantity": 18},
                    {"reason": "Not enough fabric", "quantity": 10},
                ],
            },
        )
    )


def _inspected(client: TestClient, oid: int) -> dict:
    _ok(client.post(f"/api/prod/orders/{oid}/stages/making/complete", json={}))
    return _ok(
        client.put(
            f"/api/prod/orders/{oid}/inspection",
            json={"sizes": INSPECTED, "reasons": INSPECTION_REASONS, "complete": True},
        )
    )


def _deliver(client: TestClient, oid: int, kind: str, shipped: dict, **extra):
    return client.post(
        f"/api/prod/orders/{oid}/deliveries",
        json={"kind": kind, "shipped_on": _day(-2), "shipped": shipped, **extra},
    )


def _all_the_way(client: TestClient) -> dict:
    """An order through inspection and both finished deliveries, counted;
    the 30 fix pieces still at the factory."""
    order = _new(client)
    _to_cutting(client, order["id"])
    _cut(client, order["id"])
    _inspected(client, order["id"])
    _ok(_deliver(client, order["id"], "finished", FIRST, counted_on=_day(-1), counted=FIRST))
    second = {**SECOND, "M": 139}
    _ok(
        _deliver(
            client, order["id"], "finished", SECOND, counted_on=_day(-1), counted=second,
            mismatch_reason="One piece not found at Khazenly",
        )
    )
    return client.get(f"/api/prod/orders/{order['id']}").json()["order"]


#: A key naming any of these is money: an amount (`*_piastres`), a cost, a
#: rate, a value, a deduction, what is payable, or the settlement. ("settle"
#: alone is not on the list: it is also the name of a stage, and the typical
#: days of that stage are no money.)
MONEY_WORDS = ("piastres", "cost", "rate", "settlement", "payable", "price", "value", "deduction", "held_")


def _no_money(payload, where: str = "") -> None:
    """Recursively: no key that names money, at any depth."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = key.lower()
            assert not any(word in lowered for word in MONEY_WORDS), f"money key {where}.{key}"
            _no_money(value, f"{where}.{key}")
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            _no_money(item, f"{where}[{index}]")


# ── Who may come in ───────────────────────────────────────────────────────────


def test_signed_out_and_other_departments_are_refused(owner):
    with TestClient(app) as stranger:
        assert stranger.get("/api/prod/orders").status_code == 401
    inbox = _person("cs@example.com", "customer_service")
    assert inbox.get("/api/prod/orders").status_code == 403
    assert inbox.get("/api/prod/choices").status_code == 403


# ── Create, and the dates filled in backwards ─────────────────────────────────


def test_create_fills_the_expected_dates_backwards_from_the_target(owner):
    order = _new(owner)
    expected = {
        "plan": -42, "sample": -35, "materials": -28, "fabric_check": -26, "pattern_check": -23,
        "cutting": -21, "making": -4, "final_inspection": -3, "warehouse": 0, "settle": 7,
    }
    for key, offset in expected.items():
        assert _stage(order, key)["expected_date"] == (TARGET + timedelta(days=offset)).isoformat(), key
    assert _stage(order, "plan")["status"] == "done"
    assert _stage(order, "plan")["done_on"] == TODAY.isoformat()
    assert _stage(order, "plan")["done_by"] == "Owner"
    assert _stage(order, "sample")["status"] == "todo"
    assert order["sample"]["status"] == "pending"
    assert order["code"] == f"PO-{TODAY:%y%m}-01"
    assert order["status"] == "open"
    assert order["delivery_date"] == TARGET.isoformat()
    assert order["planned_total"] == 1000
    assert order["current_stage"] == "sample"
    assert order["stage"] == {"key": "sample", "label": "Sample", "position": 2}
    assert order["steps"] == ["done"] + ["todo"] * 9
    assert order["date_history"] == [
        {
            "id": order["date_history"][0]["id"], "old_date": None, "new_date": TARGET.isoformat(),
            "set_by": "owner", "reason": "Target when planned",
            "created_at": order["date_history"][0]["created_at"], "created_by": "Owner",
        }
    ]
    assert [s["size"] for s in order["sizes"]] == ["S", "M", "L", "XL", "XXL"]
    assert order["factory"] == {"id": "fac", "name": "Main factory"}
    assert order["next_action"]["what"] == "Approve the sample"
    assert order["next_action"]["who"] == "owner"
    assert order["flags"]["waiting_for_owner"] is True
    assert _new(owner, colour="Off-white")["code"] == f"PO-{TODAY:%y%m}-02"


def test_a_repeat_run_skips_the_sample_and_its_days(owner):
    order = _new(owner, repeat_run=True)
    sample = _stage(order, "sample")
    assert sample["status"] == "skipped"
    assert sample["expected_date"] is None
    assert order["sample"]["status"] == "none"
    # The plan comes straight before materials: the sample's 7 days are gone.
    assert _stage(order, "plan")["expected_date"] == (TARGET - timedelta(days=35)).isoformat()
    assert _stage(order, "materials")["expected_date"] == (TARGET - timedelta(days=28)).isoformat()
    assert order["current_stage"] == "materials"
    assert order["flags"]["waiting_for_owner"] is False


def test_edited_stage_days_change_the_next_orders_dates(owner, staff, viewer):
    assert viewer.get("/api/prod/settings/stage-days").status_code == 200
    assert staff.put("/api/prod/settings/stage-days", json={"days": {"making": 10}}).status_code == 403
    assert owner.put("/api/prod/settings/stage-days", json={"days": {"making": 366}}).status_code == 422
    assert owner.put("/api/prod/settings/stage-days", json={"days": {"making": -1}}).status_code == 422
    assert owner.put("/api/prod/settings/stage-days", json={"days": {"plan": 2}}).status_code == 422
    saved = owner.put("/api/prod/settings/stage-days", json={"days": {"making": 10}})
    assert saved.status_code == 200, saved.text
    making = next(s for s in saved.json()["stages"] if s["stage"] == "making")
    assert making["days"] == 10 and making["updated_by"] == "Owner"
    assert [s["stage"] for s in saved.json()["stages"]][0] == "sample"

    order = _new(owner)
    assert _stage(order, "making")["expected_date"] == (TARGET - timedelta(days=4)).isoformat()
    assert _stage(order, "cutting")["expected_date"] == (TARGET - timedelta(days=14)).isoformat()
    assert owner.get("/api/prod/choices").json()["stage_days"]["making"] == 10


def test_expected_dates_can_be_set_at_create_and_edited_later(owner, staff, viewer):
    order = _new(owner, expected_dates={"cutting": _day(20)})
    assert _stage(order, "cutting")["expected_date"] == _day(20)
    url = f"/api/prod/orders/{order['id']}/stages/making"
    assert viewer.patch(url, json={"expected_date": _day(40)}).status_code == 403
    changed = _ok(staff.patch(url, json={"expected_date": _day(40), "note": "Factory busy"}))
    assert _stage(changed, "making")["expected_date"] == _day(40)
    assert _stage(changed, "making")["note"] == "Factory busy"
    assert owner.patch(f"/api/prod/orders/{order['id']}/stages/nope", json={}).status_code == 404
    repeat = _new(owner, repeat_run=True)
    refused = owner.patch(f"/api/prod/orders/{repeat['id']}/stages/sample", json={"expected_date": _day(1)})
    assert refused.status_code == 422


@pytest.mark.parametrize(
    ("over", "words"),
    [
        ({"planned": {"S": 0}}, "at least one piece"),
        ({"printing": "outside"}, "print house"),
        ({"factory_id": "old"}, "not an active supplier"),
        ({"factory_id": "nobody"}, "the factory"),
        ({"target_date": _day(-1)}, "past"),
        ({"shopify_product_id": "999"}, "product list"),
        ({"style_name": "  "}, "style"),
        ({"expected_dates": {"sample": _day(3)}, "repeat_run": True}, "skipped"),
    ],
)
def test_create_refusals(owner, over, words):
    response = owner.post("/api/prod/orders", json=_body(**over))
    assert response.status_code == 422, response.text
    assert words in response.json()["detail"]


def test_an_outside_print_house_is_named(owner):
    order = _new(owner, printing="outside", print_supplier_id="prt")
    assert order["print_supplier"] == {"id": "prt", "name": "Print house A"}
    moved = _ok(owner.patch(f"/api/prod/orders/{order['id']}", json={"printing": "none"}))
    assert moved["print_supplier"] is None and moved["printing"] == "none"


# ── Stages in order ───────────────────────────────────────────────────────────


def test_stages_complete_in_order(owner, staff):
    order = _new(owner)
    oid = order["id"]
    early = staff.post(f"/api/prod/orders/{oid}/stages/pattern_check/complete", json={})
    assert early.status_code == 422 and "Sample" in early.json()["detail"]
    for key in ("sample", "cutting", "final_inspection", "warehouse", "settle", "plan"):
        refused = staff.post(f"/api/prod/orders/{oid}/stages/{key}/complete", json={})
        assert refused.status_code == 422, key
    assert staff.post(f"/api/prod/orders/{oid}/stages/nope/complete", json={}).status_code == 404
    assert staff.post(f"/api/prod/orders/{oid}/sample", json={"decision": "approved"}).status_code == 403
    _ok(owner.post(f"/api/prod/orders/{oid}/sample", json={"decision": "approved", "note": "Good fit"}))
    future = staff.post(f"/api/prod/orders/{oid}/stages/materials/complete", json={"done_on": _day(1)})
    assert future.status_code == 422
    done = _ok(staff.post(f"/api/prod/orders/{oid}/stages/materials/complete", json={"done_on": _day(-1), "note": "Arrived"}))
    materials = _stage(done, "materials")
    assert materials["status"] == "done" and materials["done_on"] == _day(-1)
    assert materials["done_by"] == "QC Manager" and materials["note"] == "Arrived"
    again = staff.post(f"/api/prod/orders/{oid}/stages/materials/complete", json={})
    assert again.status_code == 409
    assert done["current_stage"] == "fabric_check"
    assert done["next_action"] == {
        "stage": "fabric_check", "what": "Check the fabric", "who": "qc",
        "by": _stage(done, "fabric_check")["expected_date"], "since": _day(0),
    }


def test_the_sample_approval_and_asking_for_changes(owner):
    oid = _new(owner)["id"]
    bare = owner.post(f"/api/prod/orders/{oid}/sample", json={"decision": "changes"})
    assert bare.status_code == 422
    changes = _ok(owner.post(f"/api/prod/orders/{oid}/sample", json={"decision": "changes", "note": "Longer sleeves"}))
    assert changes["sample"]["status"] == "changes"
    assert changes["sample"]["note"] == "Longer sleeves"
    assert changes["sample"]["decided_by"] == "Owner"
    assert _stage(changes, "sample")["status"] == "todo"
    assert changes["next_action"]["who"] == "factory"
    assert changes["flags"]["waiting_for_owner"] is False
    approved = _ok(owner.post(f"/api/prod/orders/{oid}/sample", json={"decision": "approved"}))
    assert approved["sample"]["status"] == "approved"
    assert _stage(approved, "sample")["status"] == "done"
    assert approved["current_stage"] == "materials"
    again = owner.post(f"/api/prod/orders/{oid}/sample", json={"decision": "approved"})
    assert again.status_code == 409


def test_the_fabric_check_only_completes_when_passed(owner, staff):
    oid = _new(owner, repeat_run=True)["id"]
    _ok(staff.post(f"/api/prod/orders/{oid}/stages/materials/complete", json={}))
    url = f"/api/prod/orders/{oid}/stages/fabric_check/complete"
    assert staff.post(url, json={}).status_code == 422
    assert staff.post(url, json={"result": "failed"}).status_code == 422
    failed = _ok(staff.post(url, json={"result": "failed", "note": "Wrong shade, 2 rolls back"}))
    assert _stage(failed, "fabric_check")["status"] == "todo"
    assert _stage(failed, "fabric_check")["note"] == "Wrong shade, 2 rolls back"
    passed = _ok(staff.post(url, json={"result": "passed", "note": "Replacement rolls fine"}))
    assert _stage(passed, "fabric_check")["status"] == "done"


# ── Cutting ───────────────────────────────────────────────────────────────────


def test_cutting_needs_reasons_for_the_shortfall_and_records_the_promise(owner, staff):
    oid = _new(owner)["id"]
    url = f"/api/prod/orders/{oid}/cut"
    early = staff.put(url, json={"sizes": CUT, "promised_date": TARGET.isoformat()})
    assert early.status_code == 422
    _to_cutting(owner, oid)
    short = staff.put(url, json={"sizes": CUT, "promised_date": TARGET.isoformat()})
    assert short.status_code == 422 and "28" in short.json()["detail"]
    wrong = staff.put(
        url, json={"sizes": CUT, "promised_date": TARGET.isoformat(), "reasons": [{"reason": "Defects", "quantity": 20}]}
    )
    assert wrong.status_code == 422
    promised = (TARGET + timedelta(days=3)).isoformat()
    order = _cut(staff, oid, promised)
    assert _stage(order, "cutting")["status"] == "done"
    assert order["totals"]["cut"] == 972 and order["cut_total"] == 972
    assert [(r["reason"], r["quantity"]) for r in order["reasons"]["cut_short"]] == [
        ("Fabric defects", 18), ("Not enough fabric", 10),
    ]
    assert order["delivery_date"] == promised
    last = order["date_history"][-1]
    assert (last["old_date"], last["new_date"], last["set_by"], last["reason"]) == (
        TARGET.isoformat(), promised, "factory", "Promised at cutting",
    )
    assert order["lateness_days"] == 3 and order["flags"]["late"] is True
    assert staff.put(url, json={"sizes": CUT, "promised_date": promised, "reasons": []}).status_code == 409


def test_cutting_more_than_planned_needs_no_reason_and_may_change_the_split(owner):
    oid = _new(owner, planned={"M": 10})["id"]
    _to_cutting(owner, oid)
    order = _ok(owner.put(f"/api/prod/orders/{oid}/cut", json={"sizes": {"M": 8, "L": 4}, "promised_date": TARGET.isoformat()}))
    by_size = {s["size"]: s for s in order["sizes"]}
    assert by_size["L"]["planned"] == 0 and by_size["L"]["cut"] == 4
    assert len(order["date_history"]) == 1  # the promise matched the date


def test_the_plan_can_change_until_cutting_only(owner):
    oid = _new(owner)["id"]
    edited = _ok(owner.patch(f"/api/prod/orders/{oid}", json={"planned": {"S": 100, "M": 100}}))
    assert edited["planned_total"] == 200
    assert owner.patch(f"/api/prod/orders/{oid}", json={"planned": {"S": 0}}).status_code == 422
    _to_cutting(owner, oid)
    _ok(owner.put(f"/api/prod/orders/{oid}/cut", json={"sizes": {"S": 100, "M": 100}, "promised_date": TARGET.isoformat()}))
    assert owner.patch(f"/api/prod/orders/{oid}", json={"planned": {"S": 50}}).status_code == 409


# ── Final inspection ──────────────────────────────────────────────────────────


def test_inspection_counts_are_saved_in_batches_and_must_add_up_to_complete(owner, staff):
    oid = _new(owner)["id"]
    url = f"/api/prod/orders/{oid}/inspection"
    assert staff.put(url, json={"sizes": {"M": {"passed": 1, "to_fix": 0, "rejected": 0}}}).status_code == 422  # before cutting
    _to_cutting(owner, oid)
    _cut(owner, oid)

    partial = _ok(staff.put(url, json={"sizes": {"M": {"passed": 200, "to_fix": 2, "rejected": 0}}}))
    m = next(s for s in partial["sizes"] if s["size"] == "M")
    assert (m["passed"], m["to_fix"], m["rejected"]) == (200, 2, 0)
    assert _stage(partial, "final_inspection")["status"] == "todo"

    over = staff.put(url, json={"sizes": {"S": {"passed": 149, "to_fix": 0, "rejected": 0}}})
    assert over.status_code == 422 and "148" in over.json()["detail"]

    # Making is not done yet, so the inspection cannot be completed.
    early = staff.put(url, json={"sizes": INSPECTED, "reasons": INSPECTION_REASONS, "complete": True})
    assert early.status_code == 422 and "Making" in early.json()["detail"]
    _ok(staff.post(f"/api/prod/orders/{oid}/stages/making/complete", json={}))

    short = {**INSPECTED, "S": {"passed": 139, "to_fix": 5, "rejected": 3}}
    refused = staff.put(url, json={"sizes": short, "reasons": INSPECTION_REASONS, "complete": True})
    assert refused.status_code == 422 and "Size S" in refused.json()["detail"]

    bad_reasons = [r for r in INSPECTION_REASONS if r["reason"] != "Stain"]
    refused = staff.put(url, json={"sizes": INSPECTED, "reasons": bad_reasons, "complete": True})
    assert refused.status_code == 422 and "16 rejected" in refused.json()["detail"]

    too_many = INSPECTION_REASONS + [{"kind": "to_fix", "reason": "Extra", "quantity": 1}]
    assert staff.put(url, json={"sizes": INSPECTED, "reasons": too_many}).status_code == 422

    done = _ok(staff.put(url, json={"sizes": INSPECTED, "reasons": INSPECTION_REASONS, "complete": True}))
    assert _stage(done, "final_inspection")["status"] == "done"
    assert (done["totals"]["passed"], done["totals"]["to_fix"], done["totals"]["rejected"]) == (926, 30, 16)
    assert done["current_stage"] == "warehouse"
    assert done["fix_not_returned"] == 30
    assert done["flags"]["fix_pieces_due"] is True
    assert staff.put(url, json={"sizes": INSPECTED}).status_code == 409


# ── Deliveries and the warehouse receipt ─────────────────────────────────────


def test_deliveries_take_two_counts_on_different_days_and_the_warehouse_completes(owner, staff):
    order = _new(owner)
    oid = order["id"]
    assert _deliver(staff, oid, "finished", {"M": 1}).status_code == 422  # before cutting
    _to_cutting(owner, oid)
    _cut(owner, oid)
    # Nothing has passed inspection yet, so nothing finished can ship.
    assert _deliver(staff, oid, "finished", {"M": 1}).status_code == 422
    _inspected(owner, oid)

    too_many = _deliver(staff, oid, "finished", {**FIRST, "S": 70 + 450})
    assert too_many.status_code == 422 and "926" in too_many.json()["detail"]
    assert _deliver(staff, oid, "finished", {"S": 0}).status_code == 422
    assert _deliver(staff, oid, "fix", {"S": 31}).status_code == 422

    created = _deliver(staff, oid, "finished", FIRST)
    assert created.status_code == 201, created.text
    first_id = created.json()["delivery_id"]
    order = created.json()["order"]
    first = order["deliveries"][0]
    assert first["number"] == 1 and first["waiting_for_count"] is True and first["counted_total"] is None
    assert order["next_action"]["what"] == "Enter Khazenly's count"
    assert order["received_total"] is None and order["shipped_total"] == 480

    # The count comes another day; it needs its date and cannot predate shipping.
    url = f"/api/prod/deliveries/{first_id}"
    assert staff.patch(url, json={"counted": FIRST}).status_code == 422
    assert staff.patch(url, json={"counted": FIRST, "counted_on": _day(-3)}).status_code == 422
    order = _ok(staff.patch(url, json={"counted": FIRST, "counted_on": _day(-1)}))
    assert order["deliveries"][0]["counted_total"] == 480 and order["deliveries"][0]["mismatch"] is False
    assert order["received_total"] == 480

    second = _ok(_deliver(staff, oid, "finished", SECOND, counted_on=_day(-1), counted={**SECOND, "M": 139}))
    d2 = second["deliveries"][1]
    assert d2["mismatch"] is True and d2["needs_reason"] is True
    assert second["flags"]["count_mismatch"] is True
    assert second["next_action"]["what"] == "Give a reason for the count that does not match"
    assert _stage(second, "warehouse")["status"] == "todo"
    explained = _ok(staff.patch(f"/api/prod/deliveries/{d2['id']}", json={"mismatch_reason": "One piece lost"}))
    assert explained["deliveries"][1]["needs_reason"] is False
    assert explained["flags"]["count_mismatch"] is False
    m = next(s for s in explained["sizes"] if s["size"] == "M")
    assert (m["shipped"], m["counted"]) == (280, 279)
    assert explained["received_total"] == 925
    # Finished pieces are all accounted for; the fix pieces are still due.
    assert _stage(explained, "warehouse")["status"] == "todo"
    assert explained["next_action"]["what"] == "Receive 30 fix pieces"
    assert explained["next_action"]["who"] == "factory"

    fix = _ok(_deliver(staff, oid, "fix", FIX))
    assert _stage(fix, "warehouse")["status"] == "todo"  # not counted yet
    fix_id = fix["deliveries"][2]["id"]
    done = _ok(staff.patch(f"/api/prod/deliveries/{fix_id}", json={"counted": FIX, "counted_on": _day(0)}))
    warehouse = _stage(done, "warehouse")
    assert warehouse["status"] == "done" and warehouse["done_on"] == _day(0)
    assert done["finished_on"] == _day(0)
    assert done["current_stage"] == "settle"
    assert done["flags"]["waiting_for_owner"] is True and done["flags"]["fix_pieces_due"] is False
    # Locked once received.
    assert staff.patch(url, json={"mismatch_reason": "x"}).status_code == 409
    assert _deliver(staff, oid, "fix", {"S": 1}).status_code == 409


def test_corrected_shipped_numbers_are_checked_again(owner, staff):
    order = _all_the_way(owner)
    first = order["deliveries"][0]
    url = f"/api/prod/deliveries/{first['id']}"
    over = staff.patch(url, json={"shipped": {**FIRST, "S": 71}})
    assert over.status_code == 422
    corrected = _ok(staff.patch(url, json={"shipped": {**FIRST, "S": 69}}))
    d1 = corrected["deliveries"][0]
    assert d1["shipped_total"] == 479 and d1["mismatch"] is True and d1["needs_reason"] is True
    assert staff.patch("/api/prod/deliveries/99999", json={"mismatch_reason": "x"}).status_code == 404


def test_writing_off_fix_pieces_moves_them_to_rejected(owner, staff):
    order = _all_the_way(owner)
    oid = order["id"]
    url = f"/api/prod/orders/{oid}/write-off"
    assert staff.post(url, json={"sizes": {"S": 1}, "reason": "Lost"}).status_code == 403
    assert owner.post(url, json={"sizes": {"S": 1}}).status_code == 422
    assert owner.post(url, json={"sizes": {"S": 6}, "reason": "Lost"}).status_code == 422
    # Bring part of the fix pieces back, counted, then write off the rest.
    _ok(_deliver(owner, oid, "fix", {"S": 5, "M": 8, "L": 9}, counted_on=_day(0), counted={"S": 5, "M": 8, "L": 9}))
    assert owner.post(url, json={"sizes": {"S": 1}, "reason": "Lost"}).status_code == 422  # S came back
    done = _ok(owner.post(url, json={"sizes": {"XL": 5, "XXL": 3}, "reason": "Factory lost them"}))
    xl = next(s for s in done["sizes"] if s["size"] == "XL")
    assert (xl["to_fix"], xl["rejected"]) == (0, 8)
    assert done["totals"]["rejected"] == 24 and done["totals"]["to_fix"] == 22
    assert ("Written off: Factory lost them", 8) in [(r["reason"], r["quantity"]) for r in done["reasons"]["rejected"]]
    # The reasons for fixing shrink with the pieces (largest first), so they
    # still add up to what is left to fix.
    assert [(r["reason"], r["quantity"]) for r in done["reasons"]["to_fix"]] == [("Loose stitching", 13), ("Label", 9)]
    assert sum(r["quantity"] for r in done["reasons"]["to_fix"]) == done["totals"]["to_fix"] == 22
    # That was all that was missing: the warehouse receipt completed by itself.
    assert _stage(done, "warehouse")["status"] == "done"
    assert owner.post(url, json={"sizes": {"S": 1}, "reason": "x"}).status_code == 409


# ── Delivery date and lateness ────────────────────────────────────────────────


def test_the_delivery_date_history_and_lateness_while_open(owner, staff, viewer):
    oid = _new(owner)["id"]
    url = f"/api/prod/orders/{oid}/delivery-date"
    later = (TARGET + timedelta(days=6)).isoformat()
    assert viewer.post(url, json={"new_date": later, "set_by": "factory", "reason": "Print queue"}).status_code == 403
    assert staff.post(url, json={"new_date": later, "set_by": "factory"}).status_code == 422
    assert staff.post(url, json={"new_date": later, "set_by": "nobody", "reason": "x"}).status_code == 422
    order = _ok(staff.post(url, json={"new_date": later, "set_by": "factory", "reason": "Waiting in the print queue"}))
    assert order["delivery_date"] == later
    assert [(h["old_date"], h["new_date"], h["set_by"]) for h in order["date_history"]] == [
        (None, TARGET.isoformat(), "owner"), (TARGET.isoformat(), later, "factory"),
    ]
    assert order["lateness_days"] == 6 and order["flags"]["late"] is True
    assert order["date_history"][1]["created_by"] == "QC Manager"
    same = staff.post(url, json={"new_date": later, "set_by": "owner", "reason": "x"})
    assert same.status_code == 422
    # A target already behind today: late by today, not by the promise.
    order = _ok(owner.patch(f"/api/prod/orders/{oid}", json={"target_date": _day(-5)}))
    assert order["lateness_days"] == (TARGET + timedelta(days=6) - (TODAY - timedelta(days=5))).days


def test_lateness_once_finished_is_the_day_the_warehouse_was_done(owner):
    order = _all_the_way(owner)
    oid = order["id"]
    done = _ok(_deliver(owner, oid, "fix", FIX, counted_on=_day(-1), counted=FIX))
    assert _stage(done, "warehouse")["done_on"] == _day(-1)
    assert done["lateness_days"] == 0  # done well before the target
    late = _ok(owner.patch(f"/api/prod/orders/{oid}", json={"target_date": _day(-3)}))
    # Finished on day -1 against a target of day -3: 2 days, whatever today is.
    assert late["lateness_days"] == 2 and late["finished_on"] == _day(-1)


# ── Money ─────────────────────────────────────────────────────────────────────


def _money_facts(printing: str, buyer: str, **actual) -> service.Facts:
    order = ProdOrder(
        printing=printing, fabric_bought_by=buyer,
        target_fabric_piastres=10000, target_manufacturing_piastres=5000, target_printing_piastres=2000,
        target_accessories_piastres=500, target_packaging_piastres=300,
    )
    for part, value in actual.items():
        setattr(order, f"actual_{part}_piastres", value)
    sizes = {"M": ProdOrderSize(size="M", planned=100, cut=100, passed=90, to_fix=6, rejected=4)}
    fix = service.Delivery(
        ProdDelivery(kind="fix", number=1), {"M": ProdDeliverySize(size="M", shipped=2, counted=2)}
    )
    return service.Facts(order, sizes, {}, [fix], [])


@pytest.mark.parametrize(
    ("printing", "buyer", "rate", "rejected_rate", "payable"),
    [
        # Rate = manufacturing (+ printing when the factory prints).
        # 100 cut x rate - 4 rejected x (rate | whole piece 17,800) - 4 still to fix x rate.
        ("factory", "hba", 7000, 7000, 700000 - 28000 - 28000),
        ("outside", "hba", 5000, 5000, 500000 - 20000 - 20000),
        ("none", "hba", 5000, 5000, 500000 - 20000 - 20000),
        ("factory", "factory", 7000, 17800, 700000 - 71200 - 28000),
        ("outside", "factory", 5000, 17800, 500000 - 71200 - 20000),
        ("none", "factory", 5000, 17800, 500000 - 71200 - 20000),
    ],
)
def test_every_money_formula(printing, buyer, rate, rejected_rate, payable):
    figures = service.settlement(_money_facts(printing, buyer))
    assert figures["making_rate_piastres"] == rate
    assert figures["rate_includes_printing"] is (printing == "factory")
    assert figures["work_value_piastres"] == 100 * rate
    assert figures["rejected_rate_piastres"] == rejected_rate
    assert figures["rejected_basis"] == ("making" if buyer == "hba" else "piece")
    assert figures["rejected_deduction_piastres"] == 4 * rejected_rate
    assert figures["held_pieces"] == 4
    assert figures["held_piastres"] == 4 * rate
    assert figures["payable_piastres"] == payable
    assert figures["settled"] is False


def test_an_actual_cost_replaces_its_target_part_by_part():
    facts = _money_facts("factory", "factory", manufacturing=5500, fabric=11000)
    figures = service.settlement(facts)
    assert figures["making_rate_piastres"] == 5500 + 2000
    assert figures["rejected_rate_piastres"] == 11000 + 5500 + 2000 + 500 + 300
    cost = service.cost(facts.order)
    assert cost["target_total_piastres"] == 17800
    assert cost["actual_total_piastres"] == 19300
    assert service.cost(_money_facts("none", "hba").order)["actual_total_piastres"] is None


def test_the_owner_sees_the_mockups_figures_and_settles(owner, staff):
    order = _all_the_way(owner)
    oid = order["id"]
    assert order["cost"]["target_total_piastres"] == 30000
    order = _ok(
        owner.patch(f"/api/prod/orders/{oid}", json={"actual_fabric_piastres": 17200, "actual_accessories_piastres": 1400})
    )
    assert order["cost"]["actual_total_piastres"] == 30900
    money = order["settlement"]
    assert money["making_rate_piastres"] == 11500
    assert money["work_value_piastres"] == 972 * 11500 == 11_178_000
    assert money["rejected_deduction_piastres"] == 16 * 11500 == 184_000
    assert money["held_piastres"] == 30 * 11500 == 345_000
    assert money["payable_piastres"] == 10_649_000

    assert owner.post(f"/api/prod/orders/{oid}/settle").status_code == 422  # warehouse not done
    _ok(_deliver(owner, oid, "fix", FIX, counted_on=_day(0), counted=FIX))
    assert staff.post(f"/api/prod/orders/{oid}/settle").status_code == 403
    settled = _ok(owner.post(f"/api/prod/orders/{oid}/settle"))
    assert settled["status"] == "closed"
    assert _stage(settled, "settle")["status"] == "done"
    assert settled["settlement"]["settled"] is True
    assert settled["settlement"]["payable_piastres"] == 11_178_000 - 184_000
    assert settled["next_action"] is None and settled["stage"] is None
    # Closed: nothing changes, and the snapshot stays.
    assert owner.patch(f"/api/prod/orders/{oid}", json={"actual_manufacturing_piastres": 1}).status_code == 409
    assert owner.post(f"/api/prod/orders/{oid}/settle").status_code == 409
    assert owner.get("/api/prod/orders").json()["orders"] == []
    closed = owner.get("/api/prod/orders", params={"status": "closed"}).json()["orders"]
    assert [row["id"] for row in closed] == [oid]
    with SessionLocal() as db:
        assert db.get(ProdOrder, oid).settled_payable_piastres == 10_994_000


def test_money_is_not_shown_before_cutting(owner):
    order = _new(owner)
    assert order["settlement"] is None
    assert order["cost"]["piece_cost_piastres"] == 30000


# ── Cancel and reopen ─────────────────────────────────────────────────────────


def test_cancel_needs_a_reason_and_locks_the_order(owner, staff):
    oid = _new(owner)["id"]
    url = f"/api/prod/orders/{oid}/cancel"
    assert staff.post(url, json={"reason": "No"}).status_code == 403
    assert owner.post(url, json={}).status_code == 422
    cancelled = _ok(owner.post(url, json={"reason": "Style dropped"}))
    assert cancelled["status"] == "cancelled" and cancelled["next_action"] is None
    # A cancelled order is at no stage, in the order and in the list.
    assert cancelled["stage"] is None and cancelled["current_stage"] is None
    assert cancelled["lateness_days"] == 0
    assert staff.post(f"/api/prod/orders/{oid}/delivery-date", json={"new_date": _day(9), "set_by": "owner", "reason": "x"}).status_code == 409
    assert owner.post(url, json={"reason": "Again"}).status_code == 409
    closed = owner.get("/api/prod/orders", params={"status": "closed"}).json()["orders"]
    assert closed[0]["status"] == "cancelled" and closed[0]["stage"] is None


def test_the_owner_reopens_only_the_latest_done_stage(owner, staff):
    oid = _new(owner)["id"]
    _to_cutting(owner, oid)
    _cut(owner, oid)
    assert staff.post(f"/api/prod/orders/{oid}/stages/cutting/reopen", json={"reason": "Recount"}).status_code == 403
    assert owner.post(f"/api/prod/orders/{oid}/stages/cutting/reopen", json={}).status_code == 422
    assert owner.post(f"/api/prod/orders/{oid}/stages/materials/reopen", json={"reason": "x"}).status_code == 422
    assert owner.post(f"/api/prod/orders/{oid}/stages/plan/reopen", json={"reason": "x"}).status_code == 422
    reopened = _ok(owner.post(f"/api/prod/orders/{oid}/stages/cutting/reopen", json={"reason": "Recount the M"}))
    assert _stage(reopened, "cutting")["status"] == "todo" and _stage(reopened, "cutting")["done_on"] is None
    assert reopened["current_stage"] == "cutting"
    # Cut again, now that it is open.
    again = _ok(owner.put(f"/api/prod/orders/{oid}/cut", json={"sizes": PLANNED, "promised_date": TARGET.isoformat()}))
    assert again["totals"]["cut"] == 1000 and again["reasons"]["cut_short"] == []


def test_reopening_the_sample_asks_for_it_again(owner):
    oid = _new(owner)["id"]
    _ok(owner.post(f"/api/prod/orders/{oid}/sample", json={"decision": "approved"}))
    reopened = _ok(owner.post(f"/api/prod/orders/{oid}/stages/sample/reopen", json={"reason": "Wrong colour"}))
    assert reopened["sample"]["status"] == "pending"
    assert reopened["flags"]["waiting_for_owner"] is True


# ── Files ─────────────────────────────────────────────────────────────────────


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
    monkeypatch.setattr(order_files, "file_bucket", lambda: store)
    monkeypatch.setattr("app.modules.production.orders.api.file_bucket", lambda: store)
    return store


def test_an_order_that_is_not_open_keeps_its_files(owner, staff, viewer, bucket):
    oid = _new(owner)["id"]
    url = f"/api/prod/orders/{oid}/files"
    photo = staff.post(url, files={"file": ("front.png", PNG, "image/png")}).json()["file"]
    _ok(owner.post(f"/api/prod/orders/{oid}/cancel", json={"reason": "Style dropped"}))

    assert staff.post(url, files={"file": ("late.png", PNG, "image/png")}).status_code == 409
    assert owner.post(url, files={"file": ("late.png", PNG, "image/png")}).status_code == 409
    assert staff.delete(photo["url"]).status_code == 409
    assert owner.delete(photo["url"]).status_code == 409
    # Still there, and still readable.
    assert [f["name"] for f in viewer.get(url).json()["files"]] == ["front.png"]
    assert viewer.get(photo["url"]).status_code == 200
    assert len(bucket.files) == 1


def test_files_are_kept_served_to_production_and_removed(owner, staff, viewer, bucket):
    oid = _new(owner)["id"]
    url = f"/api/prod/orders/{oid}/files"
    assert viewer.post(url, files={"file": ("front.png", PNG, "image/png")}).status_code == 403
    assert staff.post(url, files={"file": ("x.txt", b"hello", "text/plain")}).status_code == 422
    assert staff.post(url, files={"file": ("x.png", PNG, "image/png")}, data={"stage": "nope"}).status_code == 422
    assert staff.post("/api/prod/orders/9999/files", files={"file": ("x.png", PNG, "image/png")}).status_code == 404
    saved = staff.post(url, files={"file": ("front.png", PNG, "image/png")}, data={"stage": "sample"})
    assert saved.status_code == 201, saved.text
    photo = saved.json()["file"]
    assert photo["stage"] == "sample" and photo["mime_type"] == "image/png" and photo["uploaded_by"] == "QC Manager"
    assert all(key.startswith(f"production/orders/{oid}/") for key in bucket.files)
    pdf = staff.post(url, files={"file": ("spec.pdf", b"%PDF-1.7 ...", "application/pdf")})
    assert pdf.status_code == 201 and pdf.json()["file"]["mime_type"] == "application/pdf"

    listed = viewer.get(url).json()["files"]
    assert [f["name"] for f in listed] == ["spec.pdf", "front.png"]
    served = viewer.get(photo["url"])
    assert served.status_code == 200 and served.content == PNG
    assert served.headers["x-content-type-options"] == "nosniff"
    # The app marks every /api response no-store (app/main.py), a file included.
    assert served.headers["cache-control"] == "no-store"
    assert _person("cs@example.com", "customer_service").get(photo["url"]).status_code == 403
    assert owner.get(f"/api/prod/orders/{oid}").json()["order"]["files_count"] == 2

    assert viewer.delete(photo["url"]).status_code == 403
    assert staff.delete(photo["url"]).status_code == 200
    assert viewer.get(photo["url"]).status_code == 404
    assert staff.delete(photo["url"]).status_code == 404
    assert [f["name"] for f in viewer.get(url).json()["files"]] == ["spec.pdf"]


# ── History ───────────────────────────────────────────────────────────────────


def test_the_history_is_newest_first_in_words_and_carries_no_money(owner, staff, viewer):
    order = _all_the_way(owner)
    oid = order["id"]
    _ok(owner.patch(f"/api/prod/orders/{oid}", json={"actual_fabric_piastres": 17200}))
    events = viewer.get(f"/api/prod/orders/{oid}/history").json()["events"]
    assert events[0]["summary"] == f"Changed {order['code']}'s cost per piece"
    assert events[-1]["summary"].startswith(f"Created {order['code']}: Oversized hoodie · Black, 1,000 pieces")
    assert events[0]["who"] == "Owner"
    assert all(e["action"].startswith("production.order_") for e in events)
    assert any(e["action"] == "production.order_cut_recorded" for e in events)
    _no_money(events)
    assert viewer.get("/api/prod/orders/9999/history").status_code == 404
    with SessionLocal() as db:
        rows = db.scalars(select(AuditEvent).where(AuditEvent.subject == f"production:order:{oid}")).all()
        assert rows and all(row.department == "production" for row in rows)
        for row in rows:
            _no_money(row.after_json)
            assert "EGP" not in (row.after_json or {}).get("summary", "")


# ── Choices ───────────────────────────────────────────────────────────────────


def test_choices_lists_active_suppliers_and_products(owner, viewer):
    choices = viewer.get("/api/prod/choices").json()
    assert choices["suppliers"] == [
        {"id": "fac", "name": "Main factory", "category": "Manufacturers"},
        {"id": "prt", "name": "Print house A", "category": "Printing houses"},
    ]
    assert choices["products"] == [{"id": "111", "title": "Oversized hoodie"}]
    assert choices["sizes"] == ["XS", "S", "M", "L", "XL", "XXL"]
    assert choices["stage_days"]["making"] == 17


# ── The permission table ──────────────────────────────────────────────────────


def test_a_viewer_reads_everything_writes_nothing_and_sees_no_money(owner, viewer, bucket):
    order = _all_the_way(owner)
    oid = order["id"]
    delivery = order["deliveries"][0]["id"]
    assert "cost" in order and "settlement" in order  # the owner's view

    for path in (
        "/api/prod/orders", f"/api/prod/orders/{oid}", f"/api/prod/orders/{oid}/history",
        f"/api/prod/orders/{oid}/files", "/api/prod/settings/stage-days", "/api/prod/choices",
    ):
        response = viewer.get(path)
        assert response.status_code == 200, path
        _no_money(response.json(), path)
    seen = viewer.get(f"/api/prod/orders/{oid}").json()["order"]
    assert "cost" not in seen and "settlement" not in seen

    writes = [
        ("post", "/api/prod/orders", _body()),
        ("patch", f"/api/prod/orders/{oid}", {"colour": "Red"}),
        ("patch", f"/api/prod/orders/{oid}/stages/settle", {"note": "x"}),
        ("post", f"/api/prod/orders/{oid}/stages/making/complete", {}),
        ("post", f"/api/prod/orders/{oid}/stages/making/reopen", {"reason": "x"}),
        ("put", f"/api/prod/orders/{oid}/cut", {"sizes": CUT, "promised_date": TARGET.isoformat()}),
        ("put", f"/api/prod/orders/{oid}/inspection", {"sizes": {}}),
        ("post", f"/api/prod/orders/{oid}/write-off", {"sizes": {"S": 1}, "reason": "x"}),
        ("post", f"/api/prod/orders/{oid}/sample", {"decision": "approved"}),
        ("post", f"/api/prod/orders/{oid}/delivery-date", {"new_date": _day(90), "set_by": "owner", "reason": "x"}),
        ("post", f"/api/prod/orders/{oid}/deliveries", {"kind": "fix", "shipped_on": _day(0), "shipped": {"S": 1}}),
        ("patch", f"/api/prod/deliveries/{delivery}", {"mismatch_reason": "x"}),
        ("post", f"/api/prod/orders/{oid}/settle", None),
        ("post", f"/api/prod/orders/{oid}/cancel", {"reason": "x"}),
        ("put", "/api/prod/settings/stage-days", {"days": {"making": 9}}),
        ("delete", "/api/prod/files/1", None),
    ]
    for verb, path, body in writes:
        response = getattr(viewer, verb)(path, **({"json": body} if body is not None else {}))
        assert response.status_code == 403, (verb, path, response.status_code)


def test_staff_record_the_qc_work_never_the_owners_and_never_see_money(owner, staff, bucket):
    responses = []

    def keep(response):
        assert response.status_code in (200, 201), response.text
        responses.append(response.json())
        return response.json()

    assert staff.post("/api/prod/orders", json=_body()).status_code == 403
    oid = _new(owner)["id"]
    assert staff.post(f"/api/prod/orders/{oid}/sample", json={"decision": "approved"}).status_code == 403
    _ok(owner.post(f"/api/prod/orders/{oid}/sample", json={"decision": "approved"}))

    keep(staff.patch(f"/api/prod/orders/{oid}/stages/making", json={"expected_date": _day(30)}))
    keep(staff.post(f"/api/prod/orders/{oid}/stages/materials/complete", json={}))
    keep(staff.post(f"/api/prod/orders/{oid}/stages/fabric_check/complete", json={"result": "passed"}))
    keep(staff.post(f"/api/prod/orders/{oid}/stages/pattern_check/complete", json={}))
    keep(staff.put(f"/api/prod/orders/{oid}/cut", json={
        "sizes": CUT, "promised_date": TARGET.isoformat(),
        "reasons": [{"reason": "Fabric defects", "quantity": 28}],
    }))
    keep(staff.post(f"/api/prod/orders/{oid}/stages/making/complete", json={}))
    keep(staff.put(f"/api/prod/orders/{oid}/inspection", json={"sizes": INSPECTED, "reasons": INSPECTION_REASONS}))
    keep(staff.put(f"/api/prod/orders/{oid}/inspection", json={"complete": True}))
    keep(staff.post(f"/api/prod/orders/{oid}/delivery-date", json={"new_date": _day(70), "set_by": "factory", "reason": "Late zips"}))
    created = keep(staff.post(f"/api/prod/orders/{oid}/deliveries", json={"kind": "finished", "shipped_on": _day(-1), "shipped": FIRST}))
    keep(staff.patch(f"/api/prod/deliveries/{created['delivery_id']}", json={"counted": FIRST, "counted_on": _day(0)}))
    keep(staff.post(f"/api/prod/orders/{oid}/files", files={"file": ("a.png", PNG, "image/png")}))
    for path in ("/api/prod/orders", f"/api/prod/orders/{oid}", f"/api/prod/orders/{oid}/history",
                 f"/api/prod/orders/{oid}/files", "/api/prod/settings/stage-days", "/api/prod/choices"):
        keep(staff.get(path))

    for verb, path, body in [
        ("patch", f"/api/prod/orders/{oid}", {"actual_fabric_piastres": 1}),
        ("post", f"/api/prod/orders/{oid}/write-off", {"sizes": {"S": 1}, "reason": "x"}),
        ("post", f"/api/prod/orders/{oid}/settle", None),
        ("post", f"/api/prod/orders/{oid}/cancel", {"reason": "x"}),
        ("post", f"/api/prod/orders/{oid}/stages/making/reopen", {"reason": "x"}),
        ("put", "/api/prod/settings/stage-days", {"days": {"making": 9}}),
    ]:
        response = getattr(staff, verb)(path, **({"json": body} if body is not None else {}))
        assert response.status_code == 403, (verb, path)

    assert len(responses) >= 17
    for payload in responses:
        _no_money(payload)
    seen = staff.get(f"/api/prod/orders/{oid}").json()["order"]
    assert "cost" not in seen and "settlement" not in seen
    assert owner.get(f"/api/prod/orders/{oid}").json()["order"]["settlement"] is not None


def test_the_list_rows_carry_what_the_list_shows(owner):
    _all_the_way(owner)
    _new(owner, colour="Off-white", repeat_run=True)
    rows = owner.get("/api/prod/orders").json()["orders"]
    assert [row["colour"] for row in rows] == ["Black", "Off-white"]
    row = rows[0]
    assert row["stage"] == {"key": "warehouse", "label": "Warehouse receipt", "position": 9}
    assert row["planned_total"] == 1000 and row["received_total"] == 925 and row["cut_total"] == 972
    assert row["next_action"]["what"] == "Receive 30 fix pieces"
    assert row["flags"] == {"late": False, "waiting_for_owner": False, "count_mismatch": False, "fix_pieces_due": True}
    _no_money(rows)
    assert rows[1]["steps"][1] == "skipped" and rows[1]["received_total"] is None


@pytest.mark.parametrize("role", ["production_viewer", "production_staff", "production_manager"])
def test_nobody_without_the_owner_permission_gets_a_money_key_anywhere(owner, role, bucket):
    """Every read, for every Production role short of the owner's, with money
    on the orders: an open one, a settled one and a cancelled one. Not a key
    ending `_piastres`, nor a cost, rate, value, deduction, payable or
    settlement, at any depth - and not the word in the raw body either."""
    settled = _all_the_way(owner)
    _ok(owner.patch(f"/api/prod/orders/{settled['id']}", json={"actual_fabric_piastres": 17200}))
    _ok(_deliver(owner, settled["id"], "fix", FIX, counted_on=_day(0), counted=FIX))
    _ok(owner.post(f"/api/prod/orders/{settled['id']}/settle"))
    open_one = _all_the_way(owner)
    gone = _new(owner, colour="Off-white")
    _ok(owner.post(f"/api/prod/orders/{gone['id']}/cancel", json={"reason": "Style dropped"}))
    assert "settlement" in owner.get(f"/api/prod/orders/{settled['id']}").json()["order"]

    person = _person(f"{role}@example.com", role)
    paths = [
        "/api/prod/orders", "/api/prod/orders?status=closed", "/api/prod/choices", "/api/prod/settings/stage-days",
    ]
    for order in (settled, open_one, gone):
        paths += [f"/api/prod/orders/{order['id']}", f"/api/prod/orders/{order['id']}/history",
                  f"/api/prod/orders/{order['id']}/files"]
    for path in paths:
        response = person.get(path)
        assert response.status_code == 200, (role, path)
        _no_money(response.json(), path)
        assert "piastres" not in response.text, (role, path)
    seen = person.get(f"/api/prod/orders/{settled['id']}").json()["order"]
    assert "cost" not in seen and "settlement" not in seen
    assert seen["status"] == "closed" and seen["stage"] is None


def test_the_inspection_cannot_fall_below_what_has_already_shipped(owner, staff):
    oid = _new(owner)["id"]
    _to_cutting(owner, oid)
    _cut(owner, oid)
    url = f"/api/prod/orders/{oid}/inspection"
    _ok(staff.put(url, json={"sizes": {"M": {"passed": 200, "to_fix": 0, "rejected": 0}}}))
    _ok(_deliver(staff, oid, "finished", {"M": 150}))
    refused = staff.put(url, json={"sizes": {"M": {"passed": 100, "to_fix": 0, "rejected": 0}}})
    assert refused.status_code == 422 and "already left the factory" in refused.json()["detail"]
    kept = owner.get(f"/api/prod/orders/{oid}").json()["order"]
    assert next(s for s in kept["sizes"] if s["size"] == "M")["passed"] == 200  # the refusal rolled back


def test_the_to_fix_reasons_must_add_up_to_complete_the_inspection(owner, staff):
    oid = _new(owner)["id"]
    _to_cutting(owner, oid)
    _cut(owner, oid)
    _ok(staff.post(f"/api/prod/orders/{oid}/stages/making/complete", json={}))
    short = [r for r in INSPECTION_REASONS if r["reason"] != "Label"]
    refused = staff.put(
        f"/api/prod/orders/{oid}/inspection", json={"sizes": INSPECTED, "reasons": short, "complete": True}
    )
    assert refused.status_code == 422 and "30 to fix" in refused.json()["detail"]


def test_a_size_with_nothing_planned_gets_no_row(owner):
    order = _new(owner, planned={"S": 0, "M": 10})
    assert [s["size"] for s in order["sizes"]] == ["M"]


# ── Review fixes: write-off reasons, locks, suppliers, warehouse, files ──────


def _summaries(client: TestClient, oid: int) -> list[str]:
    return [e["summary"] for e in client.get(f"/api/prod/orders/{oid}/history").json()["events"]]


def _record_sql():
    """Every statement the engine runs from now on, until the returned stop()."""
    seen: list[str] = []

    def listen(connection, cursor, statement, parameters, context, executemany):
        seen.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", listen)
    return seen, lambda: event.remove(engine, "before_cursor_execute", listen)


def test_writing_off_everything_left_removes_the_fix_reasons_that_reach_zero(owner):
    order = _all_the_way(owner)
    oid = order["id"]
    assert [r["quantity"] for r in order["reasons"]["to_fix"]] == [21, 9]
    done = _ok(owner.post(f"/api/prod/orders/{oid}/write-off", json={"sizes": FIX, "reason": "Never came back"}))
    assert done["reasons"]["to_fix"] == []
    assert done["totals"]["to_fix"] == 0 and done["totals"]["rejected"] == 46
    assert sum(r["quantity"] for r in done["reasons"]["rejected"]) == 46
    assert _stage(done, "warehouse")["status"] == "done"


def test_an_inspection_reopened_after_a_write_off_completes_again_without_retyping(owner):
    order = _all_the_way(owner)
    oid = order["id"]
    _ok(_deliver(owner, oid, "fix", {"S": 5, "M": 8, "L": 9}, counted_on=_day(0), counted={"S": 5, "M": 8, "L": 9}))
    done = _ok(owner.post(f"/api/prod/orders/{oid}/write-off", json={"sizes": {"XL": 5, "XXL": 3}, "reason": "Lost"}))
    assert _stage(done, "warehouse")["status"] == "done"
    _ok(owner.post(f"/api/prod/orders/{oid}/stages/warehouse/reopen", json={"reason": "Recheck"}))
    reopened = _ok(owner.post(f"/api/prod/orders/{oid}/stages/final_inspection/reopen", json={"reason": "Recount"}))
    assert _stage(reopened, "final_inspection")["status"] == "todo"
    # No sizes and no reasons sent: what is stored already adds up.
    again = _ok(owner.put(f"/api/prod/orders/{oid}/inspection", json={"complete": True}))
    assert _stage(again, "final_inspection")["status"] == "done"
    assert (again["totals"]["to_fix"], again["totals"]["rejected"]) == (22, 24)


def test_a_fix_delivery_counted_over_what_it_shipped_does_not_complete_the_warehouse(owner, staff):
    order = _all_the_way(owner)
    oid = order["id"]
    # 28 of the 30 fix pieces shipped, and Khazenly's count typed as 30 with a reason.
    shipped = {**FIX, "XL": 3}
    held = _ok(
        _deliver(staff, oid, "fix", shipped, counted_on=_day(-1), counted=FIX, mismatch_reason="Counted at the dock")
    )
    assert _stage(held, "warehouse")["status"] == "todo"
    assert held["next_action"]["what"] == "Receive 2 fix pieces" and held["next_action"]["who"] == "factory"
    assert held["flags"]["fix_pieces_due"] is True
    # The last two ship and are counted: now it completes.
    last = _ok(_deliver(staff, oid, "fix", {"XL": 2}, counted_on=_day(-1), counted={"XL": 2}))
    assert _stage(last, "warehouse")["status"] == "done"


def test_a_size_added_to_a_counted_delivery_waits_for_its_count(owner, staff):
    order = _all_the_way(owner)
    oid = order["id"]
    fix = _ok(_deliver(staff, oid, "fix", {"S": 5}, counted_on=_day(-1), counted={"S": 5}))
    fix_id = fix["deliveries"][2]["id"]
    assert fix["deliveries"][2]["waiting_for_count"] is False
    edited = _ok(staff.patch(f"/api/prod/deliveries/{fix_id}", json={"shipped": {"S": 5, "M": 8}}))
    assert edited["deliveries"][2]["waiting_for_count"] is True
    assert edited["next_action"]["what"] == "Enter Khazenly's count" and edited["next_action"]["who"] == "qc"


def test_a_reopened_warehouse_stays_open_until_a_delivery_is_saved(owner, staff):
    order = _all_the_way(owner)
    oid = order["id"]
    done = _ok(_deliver(owner, oid, "fix", FIX, counted_on=_day(-1), counted=FIX))
    assert _stage(done, "warehouse")["status"] == "done"
    reopened = _ok(owner.post(f"/api/prod/orders/{oid}/stages/warehouse/reopen", json={"reason": "Recheck a count"}))
    # Reopening does not complete it again on the spot: that would undo the reopen.
    assert _stage(reopened, "warehouse")["status"] == "todo"
    assert reopened["stage"]["key"] == "warehouse"
    assert reopened["next_action"]["what"] == "Check the delivery counts"
    # Saving a delivery, even unchanged, completes it once everything is counted.
    saved = _ok(staff.patch(f"/api/prod/deliveries/{reopened['deliveries'][0]['id']}", json={}))
    assert _stage(saved, "warehouse")["status"] == "done"


def test_an_inspection_size_must_be_sent_whole(owner, staff):
    oid = _new(owner)["id"]
    _to_cutting(owner, oid)
    _cut(owner, oid)
    url = f"/api/prod/orders/{oid}/inspection"
    _ok(staff.put(url, json={"sizes": {"M": {"passed": 200, "to_fix": 2, "rejected": 1}}}))
    for partial in ({"passed": 5}, {"passed": 5, "to_fix": 1}, {"to_fix": 1, "rejected": 0}, {}):
        assert staff.put(url, json={"sizes": {"M": partial}}).status_code == 422, partial
    kept = owner.get(f"/api/prod/orders/{oid}").json()["order"]
    m = next(s for s in kept["sizes"] if s["size"] == "M")
    assert (m["passed"], m["to_fix"], m["rejected"]) == (200, 2, 1)  # nothing was zeroed
    # The service refuses it too, whoever calls it.
    with SessionLocal() as db:
        actor = db.scalar(select(UserAccount).limit(1))
        with pytest.raises(service.Refused, match="together"):
            service.save_inspection(db, oid, {"sizes": {"M": {"passed": 5}}}, actor)
        db.rollback()


def test_who_buys_the_fabric_and_printing_are_locked_once_cutting_is_done(owner):
    oid = _new(owner)["id"]
    code = owner.get(f"/api/prod/orders/{oid}").json()["order"]["code"]
    url = f"/api/prod/orders/{oid}"
    # Before cutting they can change, and the history says old and new in words.
    _ok(owner.patch(url, json={"fabric_bought_by": "factory", "printing": "none"}))
    assert _summaries(owner, oid)[0] == (
        f"Changed {code}'s who buys the fabric (from HBA to the factory) "
        "and printing (from at the factory to no printing)"
    )
    _ok(owner.patch(url, json={"printing": "factory"}))
    _to_cutting(owner, oid)
    _cut(owner, oid)

    fabric = owner.patch(url, json={"fabric_bought_by": "hba"})
    assert fabric.status_code == 409
    assert fabric.json()["detail"] == "Who buys the fabric cannot change after cutting. Reopen cutting first."
    printing = owner.patch(url, json={"printing": "none"})
    assert printing.status_code == 409
    assert printing.json()["detail"] == "Printing cannot change after cutting. Reopen cutting first."
    assert owner.patch(url, json={"printing": "outside", "print_supplier_id": "prt"}).status_code == 409
    # The same value sent again is no change, so the form can send everything.
    kept = _ok(
        owner.patch(
            url, json={"fabric_bought_by": "factory", "printing": "factory", "print_supplier_id": None, "colour": "Red"}
        )
    )
    assert kept["colour"] == "Red" and kept["fabric_bought_by"] == "factory" and kept["printing"] == "factory"
    # Reopen cutting and they can change again.
    _ok(owner.post(f"/api/prod/orders/{oid}/stages/cutting/reopen", json={"reason": "Wrong fabric buyer"}))
    assert _ok(owner.patch(url, json={"fabric_bought_by": "hba"}))["fabric_bought_by"] == "hba"


def test_a_change_of_print_house_is_told_with_both_names(owner):
    order = _new(owner, printing="outside", print_supplier_id="prt")
    oid = order["id"]
    _ok(owner.patch(f"/api/prod/orders/{oid}", json={"print_supplier_id": "fac"}))
    assert _summaries(owner, oid)[0] == (
        f"Changed {order['code']}'s print house (from Print house A to Main factory)"
    )
    locked = _new(owner, printing="outside", print_supplier_id="prt")["id"]
    _to_cutting(owner, locked)
    _cut(owner, locked)
    refused = owner.patch(f"/api/prod/orders/{locked}", json={"print_supplier_id": "fac"})
    assert refused.status_code == 409 and "Printing cannot change" in refused.json()["detail"]


def test_an_inactive_factory_or_print_house_already_on_the_order_may_stay(owner):
    with SessionLocal() as db:
        db.add(ProductionSupplier(id="alt", code="ALT", name="Second factory", category_id="cat-make", active=True))
        db.commit()
    oid = _new(owner, printing="outside", print_supplier_id="prt")["id"]
    with SessionLocal() as db:
        for supplier in ("fac", "prt"):
            db.get(ProductionSupplier, supplier).active = False
        db.commit()
    url = f"/api/prod/orders/{oid}"

    # What the form sends on every save: the factory and print house it has.
    kept = {"factory_id": "fac", "printing": "outside", "print_supplier_id": "prt"}
    order = _ok(owner.patch(url, json={**kept, "colour": "Red"}))
    assert order["colour"] == "Red"
    assert order["factory"]["id"] == "fac" and order["print_supplier"]["id"] == "prt"

    # A *changed* supplier must be active.
    for body in ({"factory_id": "old"}, {"print_supplier_id": "old"}):
        refused = owner.patch(url, json=body)
        assert refused.status_code == 422 and "not an active supplier" in refused.json()["detail"], body
    assert _ok(owner.patch(url, json={"factory_id": "alt"}))["factory"]["id"] == "alt"
    # Once moved off the inactive factory, it cannot come back.
    assert owner.patch(url, json={"factory_id": "fac"}).status_code == 422


def test_a_stray_key_error_is_a_bug_not_a_404(owner, monkeypatch):
    oid = _new(owner)["id"]
    assert issubclass(service.NotFound, LookupError)

    def boom(*args, **kwargs):
        raise KeyError("size")

    monkeypatch.setattr(service, "complete_stage", boom)
    with pytest.raises(KeyError):
        owner.post(f"/api/prod/orders/{oid}/stages/materials/complete", json={})
    # The real not-founds still answer 404, everywhere they can occur.
    assert owner.get("/api/prod/orders/9999").status_code == 404
    assert owner.get("/api/prod/orders/9999/history").status_code == 404
    assert owner.get("/api/prod/orders/9999/files").status_code == 404
    assert owner.patch("/api/prod/deliveries/99999", json={}).status_code == 404
    assert owner.delete("/api/prod/files/99999").status_code == 404
    with SessionLocal() as db:
        with pytest.raises(service.NotFound):
            service.edit_delivery(db, 99999, {}, None)


def test_editing_a_delivery_locks_the_order_before_reading_the_delivery(owner, staff):
    order = _all_the_way(owner)
    delivery = order["deliveries"][0]["id"]
    seen, stop = _record_sql()
    try:
        _ok(staff.patch(f"/api/prod/deliveries/{delivery}", json={"mismatch_reason": "Checked again"}))
    finally:
        stop()
    lock = next(i for i, sql in enumerate(seen) if "FROM prod_order" in sql and "FOR UPDATE" in sql)
    row = next(i for i, sql in enumerate(seen) if "FROM prod_delivery" in sql and "prod_delivery.number" in sql)
    assert lock < row


def test_files_lock_the_order_and_store_only_after_the_checks(owner, staff, bucket):
    oid = _new(owner)["id"]
    url = f"/api/prod/orders/{oid}/files"
    assert staff.post(url, files={"file": ("x.txt", b"hello", "text/plain")}).status_code == 422
    assert bucket.files == {}  # a refused file is never stored

    seen, stop = _record_sql()
    real_put = bucket.put

    def put(key, content, content_type):
        seen.append("BUCKET PUT")
        real_put(key, content, content_type)

    bucket.put = put
    try:
        photo = staff.post(url, files={"file": ("front.png", PNG, "image/png")}).json()["file"]
        stored = seen.index("BUCKET PUT")
        assert staff.delete(photo["url"]).status_code == 200
    finally:
        stop()
    locks = [i for i, sql in enumerate(seen) if "FROM prod_order" in sql and "FOR UPDATE" in sql]
    assert locks and locks[0] < stored  # the upload locked the order first
    assert any(i > stored for i in locks)  # and so did the removal


def test_a_file_is_served_without_a_cache_header_of_its_own(owner, staff, bucket):
    oid = _new(owner)["id"]
    photo = staff.post(f"/api/prod/orders/{oid}/files", files={"file": ("front.png", PNG, "image/png")}).json()["file"]
    with SessionLocal() as db:
        response = orders_api.one_file(photo["id"], db)
    assert "cache-control" not in response.headers  # the app adds no-store to every /api response
    assert response.headers["x-content-type-options"] == "nosniff"
    assert staff.get(photo["url"]).headers["cache-control"] == "no-store"


# ── The migration ─────────────────────────────────────────────────────────────


def test_the_downgrade_refuses_while_an_order_exists(owner):
    from alembic import command
    from alembic.config import Config

    _new(owner)
    with pytest.raises(RuntimeError, match="production order"):
        command.downgrade(Config("alembic.ini"), "b2d8f4a60029")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "c3e9a5b70030"
        assert connection.execute(text("SELECT count(*) FROM prod_order")).scalar_one() == 1
