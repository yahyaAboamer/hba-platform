"""Production's Suppliers under /api/prod (ADR 0084, decision 9; batch 4).

Sections, suppliers, purchases, the supplier's append-only account, payments,
receipts, the work line that settling an order writes, the two purchase tasks
and what the order's cost card learns from purchases. **This batch holds
money**: every figure is an integer of piastres and every rule has a test.

Every name and figure here is invented. The order helpers are batch 1's.
"""

import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db import SessionLocal, engine
from app.modules.production.orders.models import ProdSupplierEntry
from app.modules.production.orders.services import account
from app.modules.production.orders.services import suppliers as service
from app.shared.models.audit import AuditEvent
from tests.test_prod_orders import (  # noqa: F401  (fixtures)
    FIRST,
    FIX,
    PNG,
    SECOND,
    TODAY,
    _all_the_way,
    _Bucket,
    _day,
    _deliver,
    _inspected,
    _cut,
    _new,
    _no_money as _orders_no_money,
    _ok,
    _person,
    _record_sql,
    _to_cutting,
    BOOTSTRAP,
    _seed,
    staff,
    viewer,
)

#: A key naming any of these is money: an amount, a price, a total, what is
#: owed, held or paid, the account, a deposit or a receipt. (`cost` is the old
#: list's word too: the purchase's part is therefore called `part`.)
MONEY_WORDS = (
    "piastres", "cost", "rate", "settlement", "payable", "price", "value", "deduction", "held", "owed", "paid",
    "balance", "amount", "account", "deposit", "receipt", "total", "payment", "opening", "adjustment", "method",
)


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


@pytest.fixture()
def owner(fresh_database):
    """Batch 1's signed-in owner and its suppliers (``fac``, ``prt``, ``old``),
    with the five sections the migration seeded taken away: the first test of
    a session meets them (the later ones meet an emptied database), and every
    test here makes its own."""
    with TestClient(app_for_stranger()) as client:
        response = client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf"]
        _seed()
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM prod_supplier_section"))
            connection.execute(text("DELETE FROM prod_section"))
        yield client


@pytest.fixture()
def manager(owner):
    return _person("manager@example.com", "production_manager", name="Manager")


@pytest.fixture()
def bucket(monkeypatch):
    store = _Bucket()
    monkeypatch.setattr(service, "file_bucket", lambda: store)
    monkeypatch.setattr("app.modules.production.orders.suppliers_api.file_bucket", lambda: store)
    return store


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make(client: TestClient, name: str = "Fabric supplier A", **over) -> dict:
    response = client.post("/api/prod/suppliers", json={"name": name, **over})
    assert response.status_code == 201, response.text
    return response.json()["supplier"]


def _purchase_body(**over) -> dict:
    body = {
        "item": "Heavy fleece, black", "quantity": 1075, "unit": "kg",
        "unit_price_piastres": 16000, "part": "fabric",
    }
    body.update(over)
    return body


def _buy(client: TestClient, sid: str, **over) -> dict:
    response = client.post(f"/api/prod/suppliers/{sid}/purchases", json=_purchase_body(**over))
    assert response.status_code == 201, response.text
    return response.json()


def _page(client: TestClient, sid: str) -> dict:
    response = client.get(f"/api/prod/suppliers/{sid}")
    assert response.status_code == 200, response.text
    return response.json()["supplier"]


def _pay(client: TestClient, sid: str, amount: int = 3_000_000, **over) -> dict:
    body = {"amount_piastres": amount, "method": "bank_transfer", "kind": "weekly", **over}
    response = client.post(f"/api/prod/suppliers/{sid}/payments", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _lines(page: dict, **match) -> list[dict]:
    return [line for line in page["account"] if all(line[k] == v for k, v in match.items())]


def _line(page: dict, **match) -> dict:
    found = _lines(page, **match)
    assert len(found) == 1, (match, found)
    return found[0]


def _reverse(client: TestClient, entry_id: int, reason: str = "Typed in wrongly"):
    return client.post(f"/api/prod/entries/{entry_id}/reverse", json={"reason": reason})


def _walk(client: TestClient, *, settle: bool = True, **over) -> int:
    """An order all the way through, the fix pieces back and (by default)
    settled. Returns its id."""
    oid = _new(client, **over)["id"]
    _to_cutting(client, oid)
    _cut(client, oid)
    _inspected(client, oid)
    _ok(_deliver(client, oid, "finished", FIRST, counted_on=_day(-1), counted=FIRST))
    _ok(
        _deliver(
            client, oid, "finished", SECOND, counted_on=_day(-1), counted={**SECOND, "M": 139},
            mismatch_reason="One piece not found at Khazenly",
        )
    )
    if settle:
        _ok(_deliver(client, oid, "fix", FIX, counted_on=_day(0), counted=FIX))
        _ok(client.post(f"/api/prod/orders/{oid}/settle"))
    return oid


def _entries(sid: str) -> list[ProdSupplierEntry]:
    with SessionLocal() as db:
        return list(
            db.scalars(select(ProdSupplierEntry).where(ProdSupplierEntry.supplier_id == sid).order_by(ProdSupplierEntry.id))
        )


# ── The migration ─────────────────────────────────────────────────────────────


def _migration():
    path = next(Path("migrations/versions").glob("b8d5f1a30035_*.py"))
    spec = importlib.util.spec_from_file_location("suppliers_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "category, section",
    [
        ("Manufacturers", "Manufacturers"),
        ("Garment MANUFACTURING", "Manufacturers"),
        ("Fabrics & textile", "Fabric"),
        ("Screen print shops", "Printing houses"),
        ("Accessories", "Accessories"),
        ("Trims and zips", "Accessories"),
        ("Packaging", "Packaging"),
        # The first rule that matches wins.
        ("Fabric printing", "Fabric"),
        ("Printing manufacturers", "Manufacturers"),
        # None of the five: the category's own name, tidied.
        ("  Buttons   and  snaps ", "Buttons and snaps"),
        ("   ", None),
        ("x" * 100, "x" * 60),
    ],
)
def test_the_section_a_category_belongs_in(category, section):
    assert _migration().section_for(category) == section


def test_the_migration_places_todays_suppliers_in_sections(fresh_database):
    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    categories = [
        ("c1", "Garment Manufacturing"), ("c2", "FABRICS"), ("c3", "Screen print shop"), ("c4", "Trims and zips"),
        ("c5", "Packaging"), ("c6", "Buttons"), ("c7", "Fabric printing"), ("c8", "buttons"), ("c9", "L" * 100),
    ]
    suppliers = [
        ("s-a", "c1"), ("s-b", "c2"), ("s-c", "c3"), ("s-d", "c4"), ("s-e", "c5"), ("s-f", "c6"), ("s-g", "c7"),
        ("s-h", "c8"), ("s-i", "c9"), ("s-j", None),
    ]
    try:
        command.downgrade(config, "a7c4e9f20034")
        with engine.begin() as connection:
            for cid, name in categories:
                connection.execute(
                    text("INSERT INTO production_supplier_category (id, name) VALUES (:i, :n)"), {"i": cid, "n": name}
                )
            for sid, cid in suppliers:
                connection.execute(
                    text(
                        "INSERT INTO production_supplier (id, code, name, category_id, active) "
                        "VALUES (:i, :c, :n, :cat, true)"
                    ),
                    {"i": sid, "c": sid.upper(), "n": f"Supplier {sid}", "cat": cid},
                )
    finally:
        command.upgrade(config, "head")

    with engine.connect() as connection:
        sections = connection.execute(text("SELECT id, name, position FROM prod_section ORDER BY position")).all()
        placed = dict(
            connection.execute(
                text(
                    "SELECT l.supplier_id, s.name FROM prod_supplier_section l "
                    "JOIN prod_section s ON s.id = l.section_id"
                )
            ).all()
        )
        untouched = connection.execute(text("SELECT count(*) FROM production_supplier")).scalar_one()
        categories_left = connection.execute(text("SELECT count(*) FROM production_supplier_category")).scalar_one()
    assert [(name, position) for _, name, position in sections] == [
        ("Manufacturers", 1), ("Fabric", 2), ("Printing houses", 3), ("Accessories", 4), ("Packaging", 5),
        ("Buttons", 6), ("L" * 60, 7),
    ]
    assert placed == {
        "s-a": "Manufacturers", "s-b": "Fabric", "s-c": "Printing houses", "s-d": "Accessories",
        "s-e": "Packaging", "s-f": "Buttons", "s-g": "Fabric", "s-h": "Buttons", "s-i": "L" * 60,
    }
    # Nothing is lost and nothing old is altered.
    assert untouched == 10 and categories_left == 9


def test_the_downgrade_refuses_while_a_purchase_or_a_line_exists(owner):
    from alembic import command
    from alembic.config import Config

    sid = _make(owner)["id"]
    _buy(owner, sid)
    with pytest.raises(RuntimeError, match="purchase"):
        command.downgrade(Config("alembic.ini"), "a7c4e9f20034")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "b8d5f1a30035"
        assert connection.execute(text("SELECT count(*) FROM prod_supplier_entry")).scalar_one() == 1


def test_the_account_cannot_be_edited_or_deleted_or_truncated(owner):
    sid = _make(owner)["id"]
    _pay(owner, sid, 1_000)
    before = _entries(sid)[0]
    for statement in (
        "UPDATE prod_supplier_entry SET amount_piastres = -1",
        "UPDATE prod_supplier_entry SET note = 'edited'",
        "DELETE FROM prod_supplier_entry",
        "TRUNCATE prod_supplier_entry CASCADE",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            with engine.begin() as connection:
                connection.execute(text(statement))
    after = _entries(sid)
    assert len(after) == 1 and after[0].amount_piastres == before.amount_piastres == -1_000 and after[0].note is None


def test_a_line_is_never_zero_and_a_payment_always_has_its_method(owner):
    sid = _make(owner)["id"]
    for statement in (
        "INSERT INTO prod_supplier_entry (supplier_id, kind, amount_piastres, happened_on, note) "
        "VALUES (:s, 'adjustment', 0, current_date, 'x')",
        "INSERT INTO prod_supplier_entry (supplier_id, kind, amount_piastres, happened_on) "
        "VALUES (:s, 'payment', -5, current_date)",
        "INSERT INTO prod_supplier_entry (supplier_id, kind, amount_piastres, happened_on) "
        "VALUES (:s, 'adjustment', 5, current_date)",
        "INSERT INTO prod_supplier_entry (supplier_id, kind, amount_piastres, happened_on) "
        "VALUES (:s, 'work', 5, current_date)",
    ):
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(text(statement), {"s": sid})
    assert _entries(sid) == []


# ── Who may come in ───────────────────────────────────────────────────────────


def test_signed_out_and_other_departments_are_refused(owner):
    sid = _make(owner)["id"]
    with TestClient(app_for_stranger()) as stranger:
        assert stranger.get("/api/prod/suppliers").status_code == 401
        assert stranger.post(f"/api/prod/suppliers/{sid}/payments", json={}).status_code == 401
    inbox = _person("cs@example.com", "customer_service")
    assert inbox.get("/api/prod/suppliers").status_code == 403
    assert inbox.get(f"/api/prod/suppliers/{sid}").status_code == 403


def app_for_stranger():
    from app.main import app

    return app


# ── Sections ──────────────────────────────────────────────────────────────────


def test_sections_are_added_renamed_and_removed_only_when_empty(owner, manager, staff):
    assert staff.post("/api/prod/sections", json={"name": "Dyeing"}).status_code == 403
    made = manager.post("/api/prod/sections", json={"name": "  Dyeing  houses "})
    assert made.status_code == 201, made.text
    section = next(s for s in made.json()["sections"] if s["id"] == made.json()["section_id"])
    assert section["name"] == "Dyeing houses" and section["supplier_count"] == 0 and section["position"] == 1
    other = owner.post("/api/prod/sections", json={"name": "Labels"}).json()
    assert [s["name"] for s in other["sections"]] == ["Dyeing houses", "Labels"]

    # The names are unique whatever their case, and a name is required.
    assert owner.post("/api/prod/sections", json={"name": "dyeing HOUSES"}).status_code == 422
    assert owner.post("/api/prod/sections", json={"name": "   "}).status_code == 422
    assert owner.post("/api/prod/sections", json={"name": "x" * 61}).status_code == 422
    renamed = owner.patch(f"/api/prod/sections/{section['id']}", json={"name": "Dye works"})
    assert renamed.status_code == 200 and renamed.json()["sections"][0]["name"] == "Dye works"
    assert owner.patch(f"/api/prod/sections/{other['section_id']}", json={"name": "dye works"}).status_code == 422
    assert owner.patch("/api/prod/sections/9999", json={"name": "Nope"}).status_code == 404

    # A section with a supplier in it stays.
    supplier = _make(owner, section_ids=[section["id"]])
    refused = owner.delete(f"/api/prod/sections/{section['id']}")
    assert refused.status_code == 422 and "still in Dye works" in refused.json()["detail"]
    assert owner.get("/api/prod/suppliers").json()["sections"][0]["supplier_count"] == 1
    owner.patch(f"/api/prod/suppliers/{supplier['id']}", json={"section_ids": []})
    assert staff.delete(f"/api/prod/sections/{section['id']}").status_code == 403
    gone = manager.delete(f"/api/prod/sections/{section['id']}")
    assert gone.status_code == 200 and [s["name"] for s in gone.json()["sections"]] == ["Labels"]
    assert owner.delete(f"/api/prod/sections/{section['id']}").status_code == 404

    # Adding a removed section's name again brings it back, at the end.
    back = owner.post("/api/prod/sections", json={"name": "dye WORKS"})
    assert back.status_code == 201
    assert [s["name"] for s in back.json()["sections"]] == ["Labels", "dye WORKS"]
    assert back.json()["section_id"] == section["id"]


def test_a_removed_sections_name_cannot_be_taken_by_a_rename(owner):
    a = owner.post("/api/prod/sections", json={"name": "Old"}).json()["section_id"]
    b = owner.post("/api/prod/sections", json={"name": "New"}).json()["section_id"]
    assert owner.delete(f"/api/prod/sections/{a}").status_code == 200
    refused = owner.patch(f"/api/prod/sections/{b}", json={"name": "old"})
    assert refused.status_code == 422 and "removed" in refused.json()["detail"]


# ── Suppliers ─────────────────────────────────────────────────────────────────


def test_a_supplier_is_added_edited_and_never_deleted(owner, manager, staff, viewer):
    fabric = owner.post("/api/prod/sections", json={"name": "Fabric"}).json()["section_id"]
    trims = owner.post("/api/prod/sections", json={"name": "Trims"}).json()["section_id"]
    body = {
        "name": "  Fabric   supplier A ", "contact_person": "Mona", "phone": "0100", "whatsapp": "0101",
        "city": "Cairo", "notes": "Pays late", "section_ids": [fabric, trims, fabric],
    }
    assert staff.post("/api/prod/suppliers", json=body).status_code == 403
    assert viewer.post("/api/prod/suppliers", json=body).status_code == 403
    made = manager.post("/api/prod/suppliers", json=body)
    assert made.status_code == 201, made.text
    supplier = made.json()["supplier"]
    assert supplier["name"] == "Fabric supplier A" and supplier["active"] is True
    # The old tab's own numbering: the seeded FAC, PRT and OLD are three, so the next is SUP-004.
    assert supplier["code"] == "SUP-004"
    assert [s["name"] for s in supplier["sections"]] == ["Fabric", "Trims"]
    assert (supplier["contact_person"], supplier["phone"], supplier["whatsapp"], supplier["city"]) == (
        "Mona", "0100", "0101", "Cairo"
    )
    assert _make(owner, "Second")["code"] == "SUP-005"
    with SessionLocal() as db:
        row = db.execute(
            text("SELECT category_id, active, length(id) FROM production_supplier WHERE code = 'SUP-004'")
        ).one()
    assert row == (None, True, 36)  # a UUID id, no old category

    sid = supplier["id"]
    assert staff.patch(f"/api/prod/suppliers/{sid}", json={"city": "Giza"}).status_code == 403
    changed = manager.patch(f"/api/prod/suppliers/{sid}", json={"city": "Giza", "section_ids": [trims]})
    assert changed.status_code == 200, changed.text
    after = changed.json()["supplier"]
    assert after["city"] == "Giza" and after["phone"] == "0100" and [s["name"] for s in after["sections"]] == ["Trims"]
    # A supplier in no section is fine, and a blank contact clears it.
    cleared = owner.patch(f"/api/prod/suppliers/{sid}", json={"section_ids": [], "notes": ""}).json()["supplier"]
    assert cleared["sections"] == [] and cleared["notes"] is None
    assert owner.get("/api/prod/suppliers").json()["unsectioned"] >= 1

    assert owner.patch(f"/api/prod/suppliers/{sid}", json={"name": "  "}).status_code == 422
    assert owner.patch(f"/api/prod/suppliers/{sid}", json={"section_ids": [9999]}).status_code == 422
    assert owner.post("/api/prod/suppliers", json={**body, "section_ids": [9999]}).status_code == 422
    assert owner.post("/api/prod/suppliers", json={"name": ""}).status_code == 422
    assert owner.patch("/api/prod/suppliers/nope", json={"city": "x"}).status_code == 404
    assert owner.get("/api/prod/suppliers/nope").status_code == 404

    off = manager.patch(f"/api/prod/suppliers/{sid}", json={"active": False}).json()["supplier"]
    assert off["active"] is False
    assert manager.delete(f"/api/prod/suppliers/{sid}").status_code == 405  # there is no delete
    assert any(s["id"] == sid and s["active"] is False for s in owner.get("/api/prod/suppliers").json()["suppliers"])
    assert manager.patch(f"/api/prod/suppliers/{sid}", json={"active": True}).json()["supplier"]["active"] is True


def test_a_supplier_that_was_deleted_in_the_database_is_gone_from_the_screens(owner):
    sid = _make(owner)["id"]
    with engine.begin() as connection:
        connection.execute(text("UPDATE production_supplier SET deleted_at = now() WHERE id = :i"), {"i": sid})
    assert owner.get(f"/api/prod/suppliers/{sid}").status_code == 404
    assert sid not in [s["id"] for s in owner.get("/api/prod/suppliers").json()["suppliers"]]
    assert owner.post(f"/api/prod/suppliers/{sid}/payments", json={"amount_piastres": 1, "method": "cash", "kind": "final"}).status_code == 404


def test_the_list_counts_open_orders_and_unreceived_purchases(owner):
    fabric = _make(owner)
    _new(owner)  # at the main factory "fac", printing "factory"
    _new(owner, printing="outside", print_supplier_id="prt")
    _buy(owner, fabric["id"])
    done = _buy(owner, fabric["id"], item="Thread")
    _ok_pr = owner.patch(f"/api/prod/purchases/{done['purchase_id']}", json={"received_on": TODAY.isoformat()})
    assert _ok_pr.status_code == 200
    voided = _buy(owner, fabric["id"], item="Mistake")
    assert owner.post(f"/api/prod/purchases/{voided['purchase_id']}/void", json={"reason": "x"}).status_code == 200
    rows = {s["id"]: s for s in owner.get("/api/prod/suppliers").json()["suppliers"]}
    assert rows["fac"]["open_orders"] == 2 and rows["prt"]["open_orders"] == 1
    assert rows[fabric["id"]]["open_orders"] == 0 and rows[fabric["id"]]["open_purchases"] == 1
    # Active suppliers first, then by name.
    names = [s["name"] for s in owner.get("/api/prod/suppliers").json()["suppliers"]]
    assert names[-1] == "Closed mill"


# ── Purchases: the total, the lines and the deposit ───────────────────────────


@pytest.mark.parametrize(
    "quantity, price, total",
    [
        (0.333, 10050, 3347),  # 3346.65
        ("0.333", 10050, 3347),
        (0.5, 1, 1),  # half rounds up
        (2.5, 1, 3),
        (1.5, 1, 2),
        (0.004, 125, 1),  # 0.5
        (12.345, 1000, 12345),
        (0.35, 3, 1),  # 1.05
        (1075, 16000, 17_200_000),
        ("999999.999", 99_999_999, 99_999_998_900_000),  # near the ceilings, whole numbers all the way
    ],
)
def test_the_total_is_quantity_times_price_rounded_half_up(owner, quantity, price, total):
    sid = _make(owner)["id"]
    if total > service.MAX_LINE_PIASTRES:
        assert owner.post(
            f"/api/prod/suppliers/{sid}/purchases", json=_purchase_body(quantity=quantity, unit_price_piastres=price)
        ).status_code == 422
        return
    _buy(owner, sid, quantity=quantity, unit_price_piastres=price)
    page = _page(owner, sid)
    assert page["purchases"][0]["total_piastres"] == total
    assert page["owed_piastres"] == total
    assert isinstance(page["purchases"][0]["total_piastres"], int)


def test_a_purchase_that_comes_to_less_than_a_piastre_is_refused(owner):
    sid = _make(owner)["id"]
    for quantity, price in ((0.003, 125), (0.1, 3), (0.001, 1)):
        refused = owner.post(
            f"/api/prod/suppliers/{sid}/purchases", json=_purchase_body(quantity=quantity, unit_price_piastres=price)
        )
        assert refused.status_code == 422 and "less than a piastre" in refused.json()["detail"], (quantity, price)
    assert _entries(sid) == []


@pytest.mark.parametrize(
    "over",
    [
        {"item": "  "},
        {"item": "x" * 401},
        {"quantity": 0},
        {"quantity": -1},
        {"quantity": 1_000_001},
        {"quantity": "1.2345"},  # four decimal places
        {"unit": "litre"},
        {"part": "cost"},
        {"unit_price_piastres": 0},
        {"unit_price_piastres": 100_000_001},
        {"unit_price_piastres": 10.5},
        {"bought_on": "2999-01-01"},
        {"order_id": 9999},
        {"deposit_piastres": -1},
        {"deposit_piastres": 17_200_001, "deposit_method": "cash"},  # more than the total
        {"deposit_piastres": 100},  # no method
        {"deposit_piastres": 100, "deposit_method": "barter"},
    ],
)
def test_purchase_refusals_write_nothing(owner, over):
    sid = _make(owner)["id"]
    response = owner.post(f"/api/prod/suppliers/{sid}/purchases", json=_purchase_body(**over))
    assert response.status_code == 422, (over, response.text)
    assert _entries(sid) == [] and _page(owner, sid)["purchases"] == []


def test_a_purchase_with_a_deposit_writes_two_lines(owner):
    """The mockup's: 1,075 kg of fleece at EGP 160, EGP 40,000 paid now."""
    sid = _make(owner)["id"]
    order = _new(owner)
    made = _buy(
        owner, sid, order_id=order["id"], expected_on=_day(6), deposit_piastres=4_000_000,
        deposit_method="bank_transfer", note="Heavy",
    )
    page = made["supplier"]
    assert made["purchase_id"] == page["purchases"][0]["id"]
    purchase = page["purchases"][0]
    assert purchase["total_piastres"] == 17_200_000 and purchase["unit_price_piastres"] == 16000
    assert purchase["deposit_piastres"] == 4_000_000 and purchase["quantity"] == "1075"
    assert purchase["order"]["code"] == order["code"] and purchase["bought_on"] == TODAY.isoformat()
    assert purchase["part"] == "fabric" and purchase["voided"] is False and purchase["expected_on"] == _day(6)
    assert page["owed_piastres"] == 13_200_000 and page["held_piastres"] == 0
    bought, deposit = page["account"][1], page["account"][0]  # newest first
    assert (bought["kind"], bought["amount_piastres"], bought["balance_after_piastres"]) == ("purchase", 17_200_000, 17_200_000)
    assert (deposit["kind"], deposit["amount_piastres"], deposit["balance_after_piastres"]) == ("payment", -4_000_000, 13_200_000)
    assert (deposit["method"], deposit["payment_kind"], deposit["purchase"]["id"]) == ("bank_transfer", "deposit", purchase["id"])
    assert bought["what"] == "Purchase · Heavy fleece, black" and deposit["what"].startswith("Deposit · Bank transfer")
    assert bought["happened_on"] == deposit["happened_on"] == TODAY.isoformat()
    assert page["paid_piastres"] == 4_000_000  # the deposit is paid money


def test_a_deposit_equal_to_the_total_leaves_nothing_owed(owner):
    sid = _make(owner)["id"]
    _buy(owner, sid, quantity="0.333", unit_price_piastres=10050, deposit_piastres=3347, deposit_method="cash")
    page = _page(owner, sid)
    assert page["owed_piastres"] == 0 and [l["amount_piastres"] for l in page["account"]] == [-3347, 3347]


def test_a_zero_deposit_writes_no_second_line_and_the_day_may_be_earlier(owner):
    sid = _make(owner)["id"]
    _buy(owner, sid, deposit_piastres=0, bought_on=_day(-10))
    page = _page(owner, sid)
    assert len(page["account"]) == 1 and page["account"][0]["happened_on"] == _day(-10)
    assert page["purchases"][0]["bought_on"] == _day(-10)


def test_a_purchase_needs_an_active_supplier_and_an_open_order(owner):
    assert owner.post("/api/prod/suppliers/old/purchases", json=_purchase_body()).status_code == 422
    assert owner.post("/api/prod/suppliers/nope/purchases", json=_purchase_body()).status_code == 404
    sid = _make(owner)["id"]
    gone = _new(owner)["id"]
    assert owner.post(f"/api/prod/orders/{gone}/cancel", json={"reason": "Dropped"}).status_code == 200
    refused = owner.post(f"/api/prod/suppliers/{sid}/purchases", json=_purchase_body(order_id=gone))
    assert refused.status_code == 422 and "still in production" in refused.json()["detail"]
    # Payments to an inactive supplier are still paid.
    assert owner.post("/api/prod/suppliers/old/payments", json={"amount_piastres": 5, "method": "cash", "kind": "final"}).status_code == 201


# ── Voiding a purchase ────────────────────────────────────────────────────────


def test_voiding_a_purchase_reverses_both_lines_and_strikes_it_through(owner, staff, viewer):
    sid = _make(owner)["id"]
    purchase = _buy(owner, sid, deposit_piastres=4_000_000, deposit_method="cash")["purchase_id"]
    url = f"/api/prod/purchases/{purchase}/void"
    assert staff.post(url, json={"reason": "Wrong"}).status_code == 403
    assert viewer.post(url, json={"reason": "Wrong"}).status_code == 403
    assert owner.post(url, json={"reason": "  "}).status_code == 422
    assert owner.post(url, json={}).status_code == 422
    assert owner.post("/api/prod/purchases/9999/void", json={"reason": "x"}).status_code == 404

    voided = owner.post(url, json={"reason": "Wrong supplier"})
    assert voided.status_code == 200, voided.text
    page = voided.json()["supplier"]
    assert page["purchases"][0]["voided"] is True and page["purchases"][0]["void_reason"] == "Wrong supplier"
    assert page["purchases"][0]["voided_at"]
    assert page["owed_piastres"] == 0 and page["paid_piastres"] == 0 and len(page["account"]) == 4
    reversals = _lines(page, reversal=True)
    assert sorted(l["amount_piastres"] for l in reversals) == [-17_200_000, 4_000_000]
    assert all(l["note"] == "Wrong supplier" and l["happened_on"] == TODAY.isoformat() for l in reversals)
    assert len(_lines(page, reversed=True)) == 2
    assert page["open_purchases"] == 0
    # Reversed means: the originals say so, and point at their reversals.
    original = _line(page, kind="purchase", reversal=False)
    assert original["reversed"] is True and original["reversed_by_id"] in {l["id"] for l in reversals}

    assert owner.post(url, json={"reason": "Again"}).status_code == 409
    assert owner.patch(f"/api/prod/purchases/{purchase}", json={"note": "x"}).status_code == 409
    # Not even the lines can be reversed twice.
    for line in reversals + [original]:
        assert _reverse(owner, line["id"]).status_code in (409, 422)


def test_voiding_after_the_deposit_was_reversed_reverses_only_what_still_stands(owner):
    sid = _make(owner)["id"]
    purchase = _buy(owner, sid, deposit_piastres=4_000_000, deposit_method="cash")["purchase_id"]
    deposit = _line(_page(owner, sid), kind="payment", reversal=False)
    assert _reverse(owner, deposit["id"], "Never paid").status_code == 200
    assert _page(owner, sid)["owed_piastres"] == 17_200_000
    voided = owner.post(f"/api/prod/purchases/{purchase}/void", json={"reason": "Cancelled"}).json()["supplier"]
    assert voided["owed_piastres"] == 0 and len(voided["account"]) == 4  # purchase, deposit, its reversal, purchase reversal


def test_a_voided_purchase_is_not_in_what_a_cost_card_learns_nor_in_the_tasks(owner):
    sid = _make(owner)["id"]
    order = _new(owner)["id"]
    purchase = _buy(owner, sid, order_id=order, expected_on=_day(-2))["purchase_id"]
    assert owner.get("/api/prod/tasks").json()["counts"]["factory"] == 1
    owner.post(f"/api/prod/purchases/{purchase}/void", json={"reason": "Wrong"})
    card = owner.get(f"/api/prod/orders/{order}").json()["order"]["cost"]["from_purchases"]
    assert all(part["purchases"] == [] and part["per_piece_piastres"] is None for part in card["parts"])
    assert owner.get("/api/prod/tasks").json()["counts"]["factory"] == 0


# ── Marking a purchase received (the QC manager's) ────────────────────────────


def test_the_qc_manager_sets_the_expected_date_and_marks_it_received_without_money(owner, staff, viewer, manager):
    sid = _make(owner)["id"]
    purchase = _buy(owner, sid)["purchase_id"]
    url = f"/api/prod/purchases/{purchase}"
    assert viewer.patch(url, json={"received_on": TODAY.isoformat()}).status_code == 403

    changed = staff.patch(url, json={"expected_on": _day(5), "note": "Call first"})
    assert changed.status_code == 200, changed.text
    _no_money(changed.json())
    assert "piastres" not in changed.text
    p = changed.json()["supplier"]["purchases"][0]
    assert p["expected_on"] == _day(5) and p["note"] == "Call first" and p["received_on"] is None

    assert staff.patch(url, json={"received_on": _day(1)}).status_code == 422  # not in the future
    received = staff.patch(url, json={"received_on": TODAY.isoformat()}).json()["supplier"]
    assert received["purchases"][0]["received_on"] == TODAY.isoformat() and received["open_purchases"] == 0
    # What is left out stays; null clears; money is not something this route knows.
    assert manager.patch(url, json={"note": None}).json()["supplier"]["purchases"][0]["received_on"] == TODAY.isoformat()
    cleared = owner.patch(url, json={"received_on": None, "expected_on": None}).json()["supplier"]["purchases"][0]
    assert cleared["received_on"] is None and cleared["expected_on"] is None and cleared["note"] is None
    assert owner.patch(url, json={"unit_price_piastres": 1, "total_piastres": 1}).status_code == 200
    assert _page(owner, sid)["purchases"][0]["total_piastres"] == 17_200_000
    assert staff.patch("/api/prod/purchases/9999", json={"note": "x"}).status_code == 404
    assert owner.patch(url, json={"received_on": "2999-01-01"}).status_code == 422


# ── Payments, reversals, the balance brought forward, adjustments ─────────────


def test_payments_write_one_negative_line_and_a_wrong_one_is_reversed_never_edited(owner, staff, viewer, manager):
    sid = _make(owner)["id"]
    url = f"/api/prod/suppliers/{sid}/payments"
    good = {"amount_piastres": 3_000_000, "method": "instapay", "kind": "weekly", "note": "Week 46"}
    for person in (viewer, staff, manager):
        assert person.post(url, json=good).status_code == 403
    for bad in (
        {**good, "amount_piastres": 0},
        {**good, "amount_piastres": -5},
        {**good, "amount_piastres": 10_000_000_001},
        {**good, "amount_piastres": 1.5},
        {**good, "method": "barter"},
        {**good, "kind": "tip"},
        {**good, "paid_on": "2999-01-01"},
        {"amount_piastres": 5, "kind": "final"},
    ):
        assert owner.post(url, json=bad).status_code == 422, bad
    assert _entries(sid) == []

    made = owner.post(url, json={**good, "paid_on": _day(-3)})
    assert made.status_code == 201
    page = made.json()["supplier"]
    line = page["account"][0]
    assert (line["kind"], line["amount_piastres"], line["happened_on"], line["note"]) == ("payment", -3_000_000, _day(-3), "Week 46")
    assert line["what"] == "Weekly payment · InstaPay" and made.json()["entry_id"] == line["id"]
    assert page["owed_piastres"] == -3_000_000 and page["paid_piastres"] == 3_000_000  # a negative balance: overpaid

    assert _reverse(owner, line["id"], " ").status_code == 422
    assert owner.post(f"/api/prod/entries/{line['id']}/reverse", json={}).status_code == 422
    for person in (viewer, staff, manager):
        assert _reverse(person, line["id"]).status_code == 403
    assert _reverse(owner, 9999).status_code == 404
    reversed_ = _reverse(owner, line["id"], "Wrong supplier")
    assert reversed_.status_code == 200, reversed_.text
    after = reversed_.json()["supplier"]
    assert after["owed_piastres"] == 0 and after["paid_piastres"] == 0
    back = after["account"][0]
    assert back["id"] == reversed_.json()["entry_id"] and back["reversal"] is True and back["reverses_id"] == line["id"]
    assert (back["amount_piastres"], back["happened_on"], back["note"]) == (3_000_000, TODAY.isoformat(), "Wrong supplier")
    assert back["what"] == "Reversal · Weekly payment · InstaPay"
    # The original is struck through, with its reversal beside it.
    struck = _line(after, id=line["id"])
    assert struck["reversed"] is True and struck["reversed_by_id"] == back["id"]
    # Once. And a reversal is not itself reversed.
    assert _reverse(owner, line["id"]).status_code == 409
    again = _reverse(owner, back["id"])
    assert again.status_code == 422 and "itself a reversal" in again.json()["detail"]
    assert len(_entries(sid)) == 2  # the refusals wrote nothing


def test_only_this_years_unreversed_payments_count_as_paid_this_year(owner):
    sid = _make(owner)["id"]
    _pay(owner, sid, 1_000_000)
    _pay(owner, sid, 500_000, paid_on=f"{TODAY.year - 1}-12-31")
    wrong = _pay(owner, sid, 700_000)["entry_id"]
    _reverse(owner, wrong)
    page = _page(owner, sid)
    assert page["paid_piastres"] == 1_000_000 and page["paid_year"] == TODAY.year
    assert page["owed_piastres"] == -1_500_000  # last year's still counts against what is owed


def test_a_balance_brought_forward_is_one_line_and_corrected_by_an_adjustment(owner, staff, manager):
    sid = _make(owner)["id"]
    url = f"/api/prod/suppliers/{sid}/opening"
    for person in (staff, manager):
        assert person.post(url, json={"amount_piastres": 100}).status_code == 403
    assert owner.post(url, json={"amount_piastres": 0}).status_code == 422
    assert owner.post(url, json={"amount_piastres": 100, "happened_on": "2999-01-01"}).status_code == 422
    first = owner.post(url, json={"amount_piastres": 4_200_000, "happened_on": _day(-40), "note": "From the notebook"})
    assert first.status_code == 201, first.text
    page = first.json()["supplier"]
    assert page["has_opening"] is True and page["owed_piastres"] == 4_200_000
    assert (page["account"][0]["kind"], page["account"][0]["what"], page["account"][0]["happened_on"]) == (
        "opening", "Balance brought forward", _day(-40)
    )
    refused = owner.post(url, json={"amount_piastres": 5})
    assert refused.status_code == 422 and "adjustment" in refused.json()["detail"]
    assert len(_entries(sid)) == 1

    # Reversing it frees the supplier for a new one, which may be an overpayment.
    assert _reverse(owner, first.json()["entry_id"], "Wrong sheet").status_code == 200
    assert _page(owner, sid)["has_opening"] is False
    second = owner.post(url, json={"amount_piastres": -900_000})
    assert second.status_code == 201 and second.json()["supplier"]["owed_piastres"] == -900_000

    adjust = f"/api/prod/suppliers/{sid}/adjustments"
    assert owner.post(adjust, json={"amount_piastres": 250_000}).status_code == 422  # a note is required
    assert owner.post(adjust, json={"amount_piastres": 250_000, "note": "  "}).status_code == 422
    assert owner.post(adjust, json={"amount_piastres": 0, "note": "x"}).status_code == 422
    for person in (staff, manager):
        assert person.post(adjust, json={"amount_piastres": 1, "note": "x"}).status_code == 403
    more = owner.post(adjust, json={"amount_piastres": 250_000, "note": "Missed invoice"})
    less = owner.post(adjust, json={"amount_piastres": -50_000, "note": "Discount"})
    assert more.status_code == less.status_code == 201
    final = less.json()["supplier"]
    assert final["owed_piastres"] == -900_000 + 250_000 - 50_000
    assert _line(final, id=less.json()["entry_id"])["note"] == "Discount"
    assert _reverse(owner, more.json()["entry_id"], "Duplicate").status_code == 200
    assert _page(owner, sid)["owed_piastres"] == -950_000


def test_a_purchase_line_and_a_work_line_are_not_reversed_directly(owner):
    sid = _make(owner)["id"]
    _buy(owner, sid)
    purchase_line = _line(_page(owner, sid), kind="purchase")
    refused = _reverse(owner, purchase_line["id"])
    assert refused.status_code == 422 and "voiding" in refused.json()["detail"]

    oid = _walk(owner)
    work = _line(_page(owner, "fac"), kind="work")
    refused = _reverse(owner, work["id"])
    assert refused.status_code == 422 and "can't be reversed" in refused.json()["detail"]
    assert _page(owner, "fac")["owed_piastres"] == 10_994_000 and oid


def test_two_suppliers_never_leak_into_each_other(owner):
    a, b = _make(owner, "A")["id"], _make(owner, "B")["id"]
    _buy(owner, a)
    _pay(owner, b, 1_234)
    owner.post(f"/api/prod/suppliers/{b}/opening", json={"amount_piastres": 77})
    pa, pb = _page(owner, a), _page(owner, b)
    assert pa["owed_piastres"] == 17_200_000 and len(pa["account"]) == 1 and len(pa["purchases"]) == 1
    assert pb["owed_piastres"] == 77 - 1_234 and len(pb["account"]) == 2 and pb["purchases"] == []
    rows = {s["id"]: s for s in owner.get("/api/prod/suppliers").json()["suppliers"]}
    assert (rows[a]["owed_piastres"], rows[b]["owed_piastres"]) == (17_200_000, -1_157)
    # What is owed in total leaves the overpaid out.
    assert owner.get("/api/prod/suppliers").json()["owed_total_piastres"] == 17_200_000
    # A reversal on one never reaches the other.
    _reverse(owner, _line(pb, kind="opening")["id"])
    assert _page(owner, a)["owed_piastres"] == 17_200_000


# ── What the factory is owed: settling writes one work line ───────────────────


def test_owed_and_held_before_and_after_settling_with_no_double_count(owner):
    order = _all_the_way(owner)
    oid = order["id"]
    page = _page(owner, "fac")
    # Cutting is done and the order is not settled: it is worked out, not a ledger line.
    assert page["owed_piastres"] == 10_649_000 and page["held_piastres"] == 345_000
    assert _entries("fac") == []
    pending = page["account"][0]
    assert pending["not_settled"] is True and pending["id"] is None and pending["kind"] == "work"
    assert pending["amount_piastres"] == 10_649_000 and pending["balance_after_piastres"] == 10_649_000
    assert pending["order"] == {"id": oid, "code": order["code"]} and "not settled" in pending["what"]
    assert [o["id"] for o in page["orders"]] == [oid] and page["orders"][0]["role"] == "factory"
    assert page["orders"][0]["stage"]["key"] == "warehouse"
    row = next(s for s in owner.get("/api/prod/suppliers").json()["suppliers"] if s["id"] == "fac")
    assert (row["owed_piastres"], row["held_piastres"], row["open_orders"]) == (10_649_000, 345_000, 1)

    # A payment in between: the ledger moves, the order still counts once.
    _pay(owner, "fac", 3_000_000)
    page = _page(owner, "fac")
    assert page["owed_piastres"] == 7_649_000 and page["held_piastres"] == 345_000
    assert [l["balance_after_piastres"] for l in page["account"]] == [7_649_000, -3_000_000]

    # The fix pieces come back, and the order is settled.
    _ok(_deliver(owner, oid, "fix", FIX, counted_on=_day(0), counted=FIX))
    assert _page(owner, "fac")["held_piastres"] == 0 and _page(owner, "fac")["owed_piastres"] == 7_994_000
    _ok(owner.post(f"/api/prod/orders/{oid}/settle"))
    page = _page(owner, "fac")
    work = _line(page, kind="work")
    assert not _lines(page, not_settled=True)
    assert (work["amount_piastres"], work["happened_on"], work["order"]["id"]) == (10_994_000, TODAY.isoformat(), oid)
    assert work["what"] == f"Work on {order['code']}" and work["reversal"] is False
    assert page["owed_piastres"] == 7_994_000 == -3_000_000 + 10_994_000  # not 18.6 million
    assert page["held_piastres"] == 0 and page["orders"][0]["status"] == "closed" and page["orders"][0]["stage"] is None
    assert len([e for e in _entries("fac") if e.kind == "work"]) == 1
    # The same work is not written twice.
    assert owner.post(f"/api/prod/orders/{oid}/settle").status_code == 409
    assert len([e for e in _entries("fac") if e.kind == "work"]) == 1


def test_an_order_not_yet_cut_and_a_cancelled_one_count_for_nothing(owner):
    fresh = _new(owner)["id"]
    assert _page(owner, "fac")["owed_piastres"] == 0 and _page(owner, "fac")["account"] == []
    gone = _all_the_way(owner)["id"]
    assert _page(owner, "fac")["owed_piastres"] == 10_649_000
    assert owner.post(f"/api/prod/orders/{gone}/cancel", json={"reason": "Dropped"}).status_code == 200
    assert _page(owner, "fac")["owed_piastres"] == 0 and fresh


def test_a_settled_payable_of_zero_writes_no_line(owner):
    oid = _walk(owner, target_manufacturing_piastres=0, target_printing_piastres=0, printing="none")
    assert owner.get(f"/api/prod/orders/{oid}").json()["order"]["settlement"]["payable_piastres"] == 0
    assert _entries("fac") == []
    assert _page(owner, "fac")["owed_piastres"] == 0


def test_a_negative_settled_payable_writes_a_negative_line(owner):
    """The factory bought the fabric and the rejects came to more than the work."""
    oid = _walk(owner, fabric_bought_by="factory", printing="none", target_manufacturing_piastres=100)
    assert owner.get(f"/api/prod/orders/{oid}").json()["order"]["settlement"]["payable_piastres"] == 972 * 100 - 16 * 16600
    page = _page(owner, "fac")
    assert _line(page, kind="work")["amount_piastres"] == -168_400 and page["owed_piastres"] == -168_400


def test_settling_locks_the_order_then_the_factory_then_writes(owner):
    oid = _walk(owner, settle=False)
    _ok(_deliver(owner, oid, "fix", FIX, counted_on=_day(0), counted=FIX))
    seen, stop = _record_sql()
    try:
        _ok(owner.post(f"/api/prod/orders/{oid}/settle"))
    finally:
        stop()
    order_lock = next(i for i, s in enumerate(seen) if "FROM prod_order " in s and "FOR UPDATE" in s)
    supplier_lock = next(i for i, s in enumerate(seen) if "FROM production_supplier" in s and "FOR UPDATE" in s)
    insert = next(i for i, s in enumerate(seen) if s.startswith("INSERT INTO prod_supplier_entry"))
    assert order_lock < supplier_lock < insert


def test_a_payment_and_a_reversal_lock_the_supplier_before_they_read_or_write(owner):
    sid = _make(owner)["id"]
    seen, stop = _record_sql()
    try:
        entry = _pay(owner, sid)["entry_id"]
    finally:
        stop()
    lock = next(i for i, s in enumerate(seen) if "FROM production_supplier" in s and "FOR UPDATE" in s)
    assert lock < next(i for i, s in enumerate(seen) if s.startswith("INSERT INTO prod_supplier_entry"))

    seen, stop = _record_sql()
    try:
        assert _reverse(owner, entry).status_code == 200
    finally:
        stop()
    lock = next(i for i, s in enumerate(seen) if "FROM production_supplier" in s and "FOR UPDATE" in s)
    check = next(i for i, s in enumerate(seen) if "prod_supplier_entry.reverses_id =" in s)
    assert lock < check < next(i for i, s in enumerate(seen) if s.startswith("INSERT INTO prod_supplier_entry"))


# ── What the order's cost card learns from purchases ──────────────────────────


@pytest.mark.parametrize("total, pieces, expected", [(1, 2, 1), (1, 3, 0), (2, 3, 1), (5, 10, 1), (4, 10, 0), (100, 0, None), (17_200_000, 972, 17_695)])
def test_per_piece_is_rounded_half_up_in_whole_numbers(total, pieces, expected):
    assert account.per_piece(total, pieces) == expected


def test_from_purchases_is_per_piece_over_planned_then_over_cut_and_never_changes_the_order(owner, staff):
    fabric = _make(owner)["id"]
    oid = _new(owner)["id"]
    _buy(owner, fabric, order_id=oid)  # 17,200,000 of fabric
    _buy(owner, fabric, order_id=oid, item="Lining", quantity=100, unit_price_piastres=5000, part="fabric")
    _buy(owner, fabric, order_id=oid, item="Zips", quantity=1000, unit="piece", unit_price_piastres=300, part="accessories")
    _buy(owner, fabric, order_id=oid, item="Courier", quantity=1, unit="piece", unit_price_piastres=40_000, part="other")
    _buy(owner, fabric, item="Another order's fabric")  # tied to no order
    order = owner.get(f"/api/prod/orders/{oid}").json()["order"]
    card = order["cost"]["from_purchases"]
    assert card["basis"] == "planned" and card["pieces"] == 1000
    fabric_part = next(p for p in card["parts"] if p["part"] == "fabric")
    assert fabric_part["total_piastres"] == 17_700_000 and fabric_part["per_piece_piastres"] == 17_700
    assert [p["item"] for p in fabric_part["purchases"]] == ["Heavy fleece, black", "Lining"]
    assert fabric_part["purchases"][0]["supplier"] == {"id": fabric, "name": "Fabric supplier A"}
    accessories = next(p for p in card["parts"] if p["part"] == "accessories")
    assert accessories["per_piece_piastres"] == 300 and accessories["label"] == "Accessories"
    assert [p["part"] for p in card["parts"]] == ["fabric", "printing", "accessories", "packaging"]
    assert next(p for p in card["parts"] if p["part"] == "printing")["per_piece_piastres"] is None
    assert card["other"]["total_piastres"] == 40_000 and card["other"]["purchases"][0]["item"] == "Courier"
    # It never changes the typed costs by itself.
    assert order["cost"]["parts"][0]["actual_piastres"] is None and order["cost"]["target_total_piastres"] == 30000
    # "Use this" is the existing edit.
    used = owner.patch(f"/api/prod/orders/{oid}", json={"actual_fabric_piastres": fabric_part["per_piece_piastres"]})
    assert used.status_code == 200 and used.json()["order"]["cost"]["parts"][0]["actual_piastres"] == 17_700

    # Once cutting is done it is over the pieces cut (972).
    _to_cutting(owner, oid)
    _cut(owner, oid)
    after = owner.get(f"/api/prod/orders/{oid}").json()["order"]["cost"]["from_purchases"]
    assert after["basis"] == "cut" and after["pieces"] == 972
    assert next(p for p in after["parts"] if p["part"] == "fabric")["per_piece_piastres"] == 18_210  # 17,700,000 / 972 = 18,209.88


def test_the_cost_card_for_anybody_but_the_owner_has_no_cost_at_all(owner, staff, viewer):
    fabric = _make(owner)["id"]
    oid = _new(owner)["id"]
    _buy(owner, fabric, order_id=oid)
    for person in (staff, viewer):
        body = person.get(f"/api/prod/orders/{oid}")
        assert "cost" not in body.json()["order"] and "from_purchases" not in body.text and "piastres" not in body.text


# ── The two generated tasks ───────────────────────────────────────────────────


def test_a_late_purchase_is_chased_and_a_coming_one_is_checked_on_arrival(owner, staff, viewer):
    fabric = _make(owner, "Fabric supplier A")
    oid = _new(owner)
    late = _buy(owner, fabric["id"], expected_on=_day(-3), order_id=oid["id"])["purchase_id"]
    today_ = _buy(owner, fabric["id"], item="Thread", expected_on=TODAY.isoformat())["purchase_id"]
    soon = _buy(owner, fabric["id"], item="Labels", expected_on=_day(4), part="accessories")["purchase_id"]
    _buy(owner, fabric["id"], item="Boxes", part="packaging")  # no date: no task
    received = _buy(owner, fabric["id"], item="Buttons", expected_on=_day(-5), part="accessories")["purchase_id"]
    owner.patch(f"/api/prod/purchases/{received}", json={"received_on": TODAY.isoformat()})

    for person in (owner, staff, viewer):
        payload = person.get("/api/prod/tasks").json()
        mine = {t["key"]: t for t in payload["tasks"] if t["key"].startswith("purchase:")}
        assert set(mine) == {f"purchase:{late}:chase", f"purchase:{today_}:arrival", f"purchase:{soon}:arrival"}
        chase = mine[f"purchase:{late}:chase"]
        assert chase["title"] == "Chase the Heavy fleece, black delivery"
        assert (chase["who"], chase["due"], chase["waiting_on"], chase["open"]) == (
            "factory", _day(-3), "Fabric supplier A", f"purchase:{late}"
        )
        assert chase["supplier"] == {"id": fabric["id"], "name": "Fabric supplier A"}
        assert chase["order"]["id"] == oid["id"] and chase["group"] == "overdue" and chase["overdue_days"] == 3
        assert chase["since"] == TODAY.isoformat() and chase["kind"] == "generated"
        arrival = mine[f"purchase:{today_}:arrival"]
        assert arrival["title"] == "Check Thread on arrival" and arrival["who"] == "qc" and arrival["due"] == TODAY.isoformat()
        assert arrival["waiting_on"] is None and arrival["order"] is None and arrival["group"] == "today"
        assert mine[f"purchase:{soon}:arrival"]["group"] == "week"
        _no_money(payload["tasks"])
        assert "piastres" not in str(payload)
    counts = owner.get("/api/prod/tasks").json()["counts"]
    assert counts["factory"] == 1 and counts["qc"] >= 2

    # Marking it received takes the task away; so does moving the date.
    assert staff.patch(f"/api/prod/purchases/{late}", json={"received_on": TODAY.isoformat()}).status_code == 200
    assert not any(t["key"] == f"purchase:{late}:chase" for t in owner.get("/api/prod/tasks").json()["tasks"])
    staff.patch(f"/api/prod/purchases/{soon}", json={"expected_on": _day(-1)})
    keys = [t["key"] for t in owner.get("/api/prod/tasks").json()["tasks"] if t["key"].startswith("purchase:")]
    assert f"purchase:{soon}:chase" in keys and f"purchase:{soon}:arrival" not in keys


# ── Receipts ──────────────────────────────────────────────────────────────────


def test_a_receipt_is_added_served_replaced_and_removed_by_the_owner_alone(owner, staff, viewer, manager, bucket):
    sid = _make(owner)["id"]
    entry = _pay(owner, sid)["entry_id"]
    url = f"/api/prod/entries/{entry}/receipt"
    photo = {"file": ("slip.png", PNG, "image/png")}
    for person in (viewer, staff, manager):
        assert person.post(url, files=photo).status_code == 403
    saved = owner.post(url, files=photo)
    assert saved.status_code == 201, saved.text
    line = _line(saved.json()["supplier"], id=entry)
    assert line["receipt"] == {"url": url, "mime_type": "image/png", "size_bytes": len(PNG)}
    assert len(bucket.files) == 1 and next(iter(bucket.files)).startswith(f"production/suppliers/{sid}/")

    served = owner.get(url)
    assert served.status_code == 200 and served.content == PNG
    assert served.headers["x-content-type-options"] == "nosniff" and served.headers["cache-control"] == "no-store"
    for person in (viewer, staff, manager):  # the photo is refused to everybody but the owner
        assert person.get(url).status_code == 403
        assert person.delete(url).status_code == 403
    with TestClient(app_for_stranger()) as stranger:
        assert stranger.get(url).status_code == 401

    # Replaced: one live receipt, the old copy stays in the bucket.
    pdf = owner.post(url, files={"file": ("slip.pdf", b"%PDF-1.7 ...", "application/pdf")})
    assert pdf.status_code == 201 and _line(pdf.json()["supplier"], id=entry)["receipt"]["mime_type"] == "application/pdf"
    assert owner.get(url).content == b"%PDF-1.7 ..." and len(bucket.files) == 2
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM prod_supplier_receipt WHERE deleted_at IS NULL")).scalar_one() == 1

    removed = owner.delete(url)
    assert removed.status_code == 200 and _line(removed.json()["supplier"], id=entry)["receipt"] is None
    assert owner.get(url).status_code == 404 and owner.delete(url).status_code == 404


def test_a_receipt_goes_on_a_payment_and_is_checked_before_it_is_stored(owner, bucket):
    sid = _make(owner)["id"]
    _buy(owner, sid)
    purchase_line = _line(_page(owner, sid), kind="purchase")
    entry = _pay(owner, sid)["entry_id"]
    refused = owner.post(f"/api/prod/entries/{purchase_line['id']}/receipt", files={"file": ("a.png", PNG, "image/png")})
    assert refused.status_code == 422 and "payment" in refused.json()["detail"]
    assert owner.post("/api/prod/entries/9999/receipt", files={"file": ("a.png", PNG, "image/png")}).status_code == 404
    url = f"/api/prod/entries/{entry}/receipt"
    assert owner.post(url, files={"file": ("a.txt", b"hello", "text/plain")}).status_code == 422
    assert owner.post(url, files={"file": ("a.png", b"", "image/png")}).status_code == 422
    assert owner.get(url).status_code == 404  # none yet
    assert bucket.files == {}  # nothing stored by a refusal
    reversal = _reverse(owner, entry).json()["entry_id"]
    assert owner.post(f"/api/prod/entries/{reversal}/receipt", files={"file": ("a.png", PNG, "image/png")}).status_code == 422


# ── The permission table, and no money for anybody without the owner's ────────


ROLES = {
    "viewer": {"view"},
    "staff": {"view", "edit"},
    "manager": {"view", "edit", "suppliers"},
}


@pytest.mark.parametrize("role", ["viewer", "staff", "manager"])
def test_every_route_asks_its_permission_and_answers_nobody_else_money(owner, role, bucket):
    """Every endpoint, for each Production role short of the owner's: what its
    permission allows works and carries no money at any depth (nor the word
    ``piastres`` in the raw body); what it does not is refused."""
    held = ROLES[role]
    supplier = _make(owner, "Fabric supplier A")
    sid = supplier["id"]
    order = _all_the_way(owner)
    other_order = _new(owner, colour="Off-white")
    purchase = _buy(owner, sid, order_id=other_order["id"], deposit_piastres=100_000, deposit_method="cash", expected_on=_day(-1))
    entry = _pay(owner, sid, 200_000)["entry_id"]
    owner.post(f"/api/prod/entries/{entry}/receipt", files={"file": ("a.png", PNG, "image/png")})
    section = owner.post("/api/prod/sections", json={"name": "Spare"}).json()["section_id"]
    spare = owner.post("/api/prod/sections", json={"name": "Spare two"}).json()["section_id"]
    assert owner.get("/api/prod/suppliers").json()["suppliers"][0].get("owed_piastres") is not None  # the owner's has money

    person = _person(f"{role}@example.com", {"viewer": "production_viewer", "staff": "production_staff", "manager": "production_manager"}[role])
    p = purchase["purchase_id"]
    calls = [
        ("get", "/api/prod/suppliers", None, "view"),
        ("get", f"/api/prod/suppliers/{sid}", None, "view"),
        ("get", "/api/prod/suppliers/fac", None, "view"),
        ("get", f"/api/prod/orders/{order['id']}", None, "view"),
        ("get", "/api/prod/tasks", None, "view"),
        ("post", "/api/prod/suppliers", {"name": "New supplier"}, "suppliers"),
        ("patch", f"/api/prod/suppliers/{sid}", {"city": "Giza"}, "suppliers"),
        ("post", "/api/prod/sections", {"name": "Brand new"}, "suppliers"),
        ("patch", f"/api/prod/sections/{section}", {"name": "Spare renamed"}, "suppliers"),
        ("delete", f"/api/prod/sections/{spare}", None, "suppliers"),
        ("patch", f"/api/prod/purchases/{p}", {"expected_on": _day(2)}, "edit"),
        ("post", f"/api/prod/suppliers/{sid}/purchases", _purchase_body(), "owner"),
        ("post", f"/api/prod/purchases/{p}/void", {"reason": "x"}, "owner"),
        ("post", f"/api/prod/suppliers/{sid}/payments", {"amount_piastres": 1, "method": "cash", "kind": "final"}, "owner"),
        ("post", f"/api/prod/suppliers/{sid}/opening", {"amount_piastres": 1}, "owner"),
        ("post", f"/api/prod/suppliers/{sid}/adjustments", {"amount_piastres": 1, "note": "x"}, "owner"),
        ("post", f"/api/prod/entries/{entry}/reverse", {"reason": "x"}, "owner"),
        ("post", f"/api/prod/entries/{entry}/receipt", None, "owner"),
        ("get", f"/api/prod/entries/{entry}/receipt", None, "owner"),
        ("delete", f"/api/prod/entries/{entry}/receipt", None, "owner"),
    ]
    answered = 0
    for verb, path, body, needs in calls:
        kwargs = {"json": body} if body is not None else {}
        if path.endswith("/receipt") and verb == "post":
            kwargs = {"files": {"file": ("b.png", PNG, "image/png")}}
        response = getattr(person, verb)(path, **kwargs)
        if needs == "owner" or needs not in held:
            assert response.status_code == 403, (role, verb, path, response.status_code)
            continue
        assert response.status_code in (200, 201), (role, verb, path, response.text)
        # An order's own view has legitimate non-money keys (`planned_total`) that
        # this batch's wider list would flag; it is held to batch 1's list.
        (_orders_no_money if "/orders/" in path else _no_money)(response.json(), path)
        assert "piastres" not in response.text, (role, path)
        answered += 1
    assert answered >= {"viewer": 5, "staff": 6, "manager": 11}[role]

    # What a person without the owner's permission does see of a supplier.
    page = person.get(f"/api/prod/suppliers/{sid}").json()["supplier"]
    assert {"purchases", "orders", "sections", "open_orders", "open_purchases"} <= set(page)
    assert page["purchases"][0]["item"] == "Heavy fleece, black" and page["purchases"][0]["quantity"] == "1075"
    assert "account" not in page and "owed_piastres" not in page and "has_opening" not in page
    assert all("owed_piastres" not in s for s in person.get("/api/prod/suppliers").json()["suppliers"])
    assert "owed_total_piastres" not in person.get("/api/prod/suppliers").json()
    fac = person.get("/api/prod/suppliers/fac").json()["supplier"]
    assert {o["id"] for o in fac["orders"]} == {order["id"], other_order["id"]} and fac["open_orders"] == 2


# ── The history: words, never an amount ───────────────────────────────────────


def test_every_write_is_in_the_history_without_an_amount(owner, bucket):
    section = owner.post("/api/prod/sections", json={"name": "Fabric"}).json()["section_id"]
    owner.patch(f"/api/prod/sections/{section}", json={"name": "Fabrics"})
    sid = _make(owner, section_ids=[section])["id"]
    owner.patch(f"/api/prod/suppliers/{sid}", json={"city": "Giza"})
    owner.patch(f"/api/prod/suppliers/{sid}", json={"active": False})
    owner.patch(f"/api/prod/suppliers/{sid}", json={"active": True})
    p = _buy(owner, sid, deposit_piastres=4_000_000, deposit_method="cash", quantity="1234.5", note="9876543")["purchase_id"]
    owner.patch(f"/api/prod/purchases/{p}", json={"expected_on": _day(3), "note": "n"})
    owner.patch(f"/api/prod/purchases/{p}", json={"received_on": TODAY.isoformat()})
    owner.patch(f"/api/prod/purchases/{p}", json={"received_on": None})
    entry = _pay(owner, sid, 3_333_000, note="3333000")["entry_id"]
    assert owner.post(f"/api/prod/entries/{entry}/receipt", files={"file": ("a.png", PNG, "image/png")}).status_code == 201
    assert owner.delete(f"/api/prod/entries/{entry}/receipt").status_code == 200
    opening = owner.post(f"/api/prod/suppliers/{sid}/opening", json={"amount_piastres": 4_200_000}).json()["entry_id"]
    owner.post(f"/api/prod/suppliers/{sid}/adjustments", json={"amount_piastres": 250_000, "note": "Missed invoice 5555"})
    _reverse(owner, opening, "Typed 4,200 by mistake 7777")
    _reverse(owner, entry, "Wrong 8888")
    owner.post(f"/api/prod/purchases/{p}/void", json={"reason": "Wrong 9999"})
    owner.delete(f"/api/prod/sections/{section}")  # refused: still in use, writes nothing
    owner.patch(f"/api/prod/suppliers/{sid}", json={"section_ids": []})
    owner.delete(f"/api/prod/sections/{section}")

    with SessionLocal() as db:
        events = list(
            db.scalars(
                select(AuditEvent)
                .where(AuditEvent.subject.like("production:supplier:%") | AuditEvent.subject.like("production:section:%"))
                .order_by(AuditEvent.id)
            )
        )
    actions = [e.action for e in events]
    assert {
        "production.section_added", "production.section_renamed", "production.section_removed",
        "production.supplier_added", "production.supplier_changed", "production.supplier_deactivated",
        "production.supplier_activated", "production.purchase_added", "production.purchase_changed",
        "production.purchase_received", "production.purchase_unreceived", "production.purchase_voided",
        "production.payment_recorded", "production.payment_reversed", "production.supplier_opening_recorded",
        "production.supplier_adjusted", "production.supplier_line_reversed",
        "production.payment_receipt_added", "production.payment_receipt_removed",
    } <= set(actions)
    assert all(a.startswith(("production.supplier_", "production.section_", "production.purchase_", "production.payment_")) for a in actions)
    assert {e.subject for e in events if e.action.startswith("production.supplier_added")} == {f"production:supplier:{sid}"}
    assert all(e.department == "production" for e in events)
    everything = " ".join(str(e.after_json) + " " + (e.reason or "") for e in events)
    for figure in ("4000000", "4,000,000", "40,000", "3333000", "3,333,000", "4200000", "4,200", "250000",
                   "9876543", "5555", "7777", "8888", "9999", "EGP", "piastre", "1234.5"):
        assert figure not in everything, figure
    for event in events:
        assert event.after_json["summary"]
