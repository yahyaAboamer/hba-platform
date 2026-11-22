"""Production's fabric storage under /api/prod (ADR 0089).

A fabric's stock is the sum of its movements; purchases in kg of the fabric
part fill it, orders take from it and give back, a cancelled order gives back
everything, a purchase whose kilos are used cannot be voided, and the price
per kg is the owner's alone.

Every name and figure here is invented. The order and supplier helpers are
batches 1 and 4's.
"""

import pytest
from sqlalchemy import select, text

from app.db import SessionLocal, engine
from app.modules.production.orders.models import ProdFabricMove, ProdOrder, ProdPurchase
from app.modules.production.orders.services import suppliers as supplier_service
from app.modules.production.orders.services.orders import Refused
from app.shared.models.identity import UserAccount
from tests.conftest import alembic_head
from tests.test_prod_orders import (  # noqa: F401  (fixtures)
    _cut,
    _new,
    _no_money,
    _ok,
    _to_cutting,
    staff,
    viewer,
)
from tests.test_prod_suppliers import (  # noqa: F401  (fixtures)
    _buy,
    _make,
    _page,
    owner,
)

FLEECE = "Heavy fleece"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _fabric(client, name: str = FLEECE, **over) -> dict:
    response = client.post("/api/prod/fabrics", json={"name": name, **over})
    assert response.status_code == 201, response.text
    return response.json()["fabric"]


def _detail(client, fid: int) -> dict:
    response = client.get(f"/api/prod/fabrics/{fid}")
    assert response.status_code == 200, response.text
    return response.json()


def _row(client, fid: int) -> dict:
    return next(row for row in client.get("/api/prod/fabrics").json()["fabrics"] if row["id"] == fid)


def _stock(client, fid: int) -> str:
    return _row(client, fid)["in_stock_kg"]


def _into(client, sid: str, fid: int, kg, price: int = 16000, **over) -> dict:
    return _buy(client, sid, quantity=kg, unit_price_piastres=price, fabric_id=fid, **over)


def _take(client, oid: int, fid: int, kg):
    return client.post(f"/api/prod/orders/{oid}/fabric", json={"fabric_id": fid, "kg": kg})


def _give_back(client, oid: int, move_id: int):
    return client.delete(f"/api/prod/orders/{oid}/fabric/{move_id}")


def _purchase_id(sid: str, item: str) -> int:
    with SessionLocal() as db:
        return db.scalar(
            select(ProdPurchase.id).where(ProdPurchase.supplier_id == sid, ProdPurchase.item == item)
            .order_by(ProdPurchase.id.desc())
        )


def _moves(fid: int) -> list[tuple[str, str]]:
    with SessionLocal() as db:
        return [
            (m.kind, f"{m.kg}")
            for m in db.scalars(select(ProdFabricMove).where(ProdFabricMove.fabric_id == fid).order_by(ProdFabricMove.id))
        ]


# ── Storage is the sum of its moves ───────────────────────────────────────────


def test_storage_is_the_sum_of_its_moves(owner, staff):
    sid = _make(owner)["id"]
    fid = _fabric(staff, colour="Black", in_storage_kg="12.5")["id"]
    assert _stock(owner, fid) == "12.500"
    _into(owner, sid, fid, 100)
    oid = _new(owner)["id"]
    _ok(_take(staff, oid, fid, "30.25"))

    row = _row(owner, fid)
    assert (row["in_stock_kg"], row["bought_kg"], row["used_kg"], row["orders"]) == ("82.250", "100.000", "30.250", 1)
    moves = _detail(owner, fid)["moves"]
    assert [(m["kind"], m["kg"]) for m in moves] == [("use", "-30.250"), ("purchase", "100.000"), ("count", "12.500")]
    assert moves[0]["order"]["id"] == oid and moves[0]["returned"] is False and moves[0]["by"] == "QC Manager"
    assert moves[1]["purchase"]["item"] == "Heavy fleece, black"
    assert moves[1]["purchase"]["supplier"]["id"] == sid
    assert moves[2]["note"] == "Already in storage when added"


def test_a_fabric_needs_a_name_of_its_own_whatever_its_case(owner, staff, viewer):
    _fabric(staff)
    response = staff.post("/api/prod/fabrics", json={"name": "heavy FLEECE"})
    assert response.status_code == 422 and response.json()["detail"] == "There is already a fabric called heavy FLEECE."
    assert staff.post("/api/prod/fabrics", json={"name": "  "}).status_code == 422
    assert staff.post("/api/prod/fabrics", json={"name": "X", "in_storage_kg": 0}).status_code == 422
    assert staff.post("/api/prod/fabrics", json={"name": "X", "in_storage_kg": "1.2345"}).status_code == 422
    assert staff.post("/api/prod/fabrics", json={"name": "X", "price": 1}).status_code == 422
    assert viewer.post("/api/prod/fabrics", json={"name": "Y"}).status_code == 403
    assert [row["name"] for row in viewer.get("/api/prod/fabrics").json()["fabrics"]] == [FLEECE]


def test_a_fabric_is_edited_and_retired(owner, staff):
    sid = _make(owner)["id"]
    fid = _fabric(staff)["id"]
    other = _fabric(staff, "Jersey")["id"]
    response = staff.patch(f"/api/prod/fabrics/{fid}", json={"name": "JERSEY"})
    assert response.status_code == 422
    body = staff.patch(
        f"/api/prod/fabrics/{fid}", json={"colour": "Navy", "colour_code": "19-4024", "supplier_id": sid, "note": "Soft"}
    ).json()
    assert body["fabric"]["colour"] == "Navy" and body["fabric"]["supplier"]["id"] == sid
    assert body["fabric"]["note"] == "Soft" and body["moves"] == []
    assert staff.patch(f"/api/prod/fabrics/{fid}", json={"supplier_id": "nobody"}).status_code == 422
    assert staff.patch("/api/prod/fabrics/999999", json={"colour": "Red"}).status_code == 404

    assert owner.post(f"/api/prod/fabrics/{fid}/count", json={"kg_in_storage": 10, "note": "Found a roll"}).status_code == 200
    staff.patch(f"/api/prod/fabrics/{fid}", json={"active": False})
    # Retired: last in the list, gone from the New order form, and not taken.
    assert [row["id"] for row in staff.get("/api/prod/fabrics").json()["fabrics"]] == [other, fid]
    assert [f["id"] for f in staff.get("/api/prod/choices").json()["fabrics"]] == [other]
    oid = _new(owner)["id"]
    response = _take(staff, oid, fid, 1)
    assert response.status_code == 422 and response.json()["detail"] == f"{FLEECE} is no longer kept in storage."


def test_the_new_order_form_offers_the_active_fabrics_with_their_kilos(owner, staff):
    fid = _fabric(staff, colour="Black", in_storage_kg=40)["id"]
    choices = staff.get("/api/prod/choices").json()["fabrics"]
    assert choices == [{"id": fid, "name": FLEECE, "colour": "Black", "in_stock_kg": "40.000"}]


# ── Purchases fill storage ────────────────────────────────────────────────────


def test_a_purchase_by_the_kilo_fills_an_existing_fabric(owner, staff):
    sid = _make(owner)["id"]
    fid = _fabric(staff)["id"]
    _into(owner, sid, fid, "75.5")
    assert _stock(owner, fid) == "75.500"
    assert _moves(fid) == [("purchase", "75.500")]


def test_a_purchase_by_the_kilo_makes_a_new_fabric_with_its_supplier(owner):
    supplier = _make(owner, "Knit mill")
    _buy(owner, supplier["id"], quantity=40, new_fabric={"name": "Jersey navy", "colour": "Navy", "fabric_type": "Jersey"})
    row = next(r for r in owner.get("/api/prod/fabrics").json()["fabrics"] if r["name"] == "Jersey navy")
    assert row["supplier"] == {"id": supplier["id"], "name": "Knit mill"}
    assert (row["colour"], row["fabric_type"], row["in_stock_kg"]) == ("Navy", "Jersey", "40.000")


@pytest.mark.parametrize(
    "over",
    [
        {"unit": "m"},
        {"unit": "piece"},
        {"part": "accessories"},
    ],
)
def test_only_fabric_bought_by_the_kilo_goes_into_storage(owner, staff, over):
    sid = _make(owner)["id"]
    fid = _fabric(staff)["id"]
    body = {"item": "Rib", "quantity": 10, "unit": "kg", "unit_price_piastres": 100, "part": "fabric", "fabric_id": fid}
    response = owner.post(f"/api/prod/suppliers/{sid}/purchases", json={**body, **over})
    assert response.status_code == 422
    assert response.json()["detail"] == "Only fabric bought by the kilo goes into storage."
    response = owner.post(
        f"/api/prod/suppliers/{sid}/purchases", json={**body, **over, "fabric_id": None, "new_fabric": {"name": "Rib"}}
    )
    assert response.status_code == 422
    # Nothing was written: no purchase, no fabric, no move.
    assert _page(owner, sid)["purchases"] == []
    assert [r["name"] for r in owner.get("/api/prod/fabrics").json()["fabrics"]] == [FLEECE]
    assert _moves(fid) == []


def test_a_purchase_fills_one_known_active_fabric_or_none(owner, staff):
    sid = _make(owner)["id"]
    fid = _fabric(staff)["id"]
    body = {"item": "Rib", "quantity": 10, "unit": "kg", "unit_price_piastres": 100, "part": "fabric"}
    url = f"/api/prod/suppliers/{sid}/purchases"
    assert owner.post(url, json={**body, "fabric_id": fid, "new_fabric": {"name": "Rib"}}).status_code == 422
    assert owner.post(url, json={**body, "fabric_id": 999999}).status_code == 422
    response = owner.post(url, json={**body, "new_fabric": {"name": FLEECE.upper()}})
    assert response.status_code == 422 and "already a fabric" in response.json()["detail"]
    staff.patch(f"/api/prod/fabrics/{fid}", json={"active": False})
    assert owner.post(url, json={**body, "fabric_id": fid}).status_code == 422
    assert _page(owner, sid)["purchases"] == []
    # Fabric bought by the kilo may also stay out of storage.
    assert owner.post(url, json=body).status_code == 201
    assert _moves(fid) == []


def test_the_price_per_kg_is_the_average_of_live_purchases_for_the_owner_only(owner, staff, viewer):
    sid = _make(owner)["id"]
    fid = _fabric(staff)["id"]
    _into(owner, sid, fid, 100, 16000, item="Fleece lot 1")  # 1,600,000
    assert _row(owner, fid)["price_per_kg_piastres"] == 16000
    _into(owner, sid, fid, 3, 10001, item="Fleece lot 2")  # 30,003
    # 1,630,003 / 103 = 15,825.27 -> 15,825
    assert _row(owner, fid)["price_per_kg_piastres"] == 15825
    second = _purchase_id(sid, "Fleece lot 2")
    assert owner.post(f"/api/prod/purchases/{second}/void", json={"reason": "Wrong lot"}).status_code == 200
    assert _row(owner, fid)["price_per_kg_piastres"] == 16000
    assert _detail(owner, fid)["fabric"]["price_per_kg_piastres"] == 16000

    for client in (staff, viewer):
        _no_money(client.get("/api/prod/fabrics").json())
        _no_money(client.get(f"/api/prod/fabrics/{fid}").json())
        assert "price_per_kg_piastres" not in _row(client, fid)


def test_a_fabric_with_no_live_purchase_has_no_price(owner, staff):
    fid = _fabric(staff, in_storage_kg=5)["id"]
    assert _row(owner, fid)["price_per_kg_piastres"] is None


# ── Counting ──────────────────────────────────────────────────────────────────


def test_a_count_records_the_difference_with_its_reason(owner, staff):
    fid = _fabric(staff, in_storage_kg="82.5")["id"]
    url = f"/api/prod/fabrics/{fid}/count"
    body = staff.post(url, json={"kg_in_storage": 80, "note": "Weighed the rolls"}).json()
    assert body["fabric"]["in_stock_kg"] == "80.000"
    assert (body["moves"][0]["kind"], body["moves"][0]["kg"], body["moves"][0]["note"]) == (
        "count", "-2.500", "Weighed the rolls",
    )
    response = staff.post(url, json={"kg_in_storage": "80.000", "note": "Again"})
    assert response.status_code == 422 and response.json()["detail"] == "Storage already holds that much."
    assert staff.post(url, json={"kg_in_storage": -1, "note": "Below"}).status_code == 422
    assert staff.post(url, json={"kg_in_storage": 70, "note": " "}).status_code == 422
    assert staff.post(url, json={"kg_in_storage": "1.0001", "note": "Fine"}).status_code == 422
    assert staff.post(url, json={"kg_in_storage": 1_000_001, "note": "Big"}).status_code == 422
    assert staff.post(url, json={"kg_in_storage": 0, "note": "All used"}).json()["fabric"]["in_stock_kg"] == "0.000"
    assert staff.post("/api/prod/fabrics/999999/count", json={"kg_in_storage": 1, "note": "x"}).status_code == 404


# ── Orders take and give back ─────────────────────────────────────────────────


def test_an_order_takes_fabric_and_gives_it_back_once(owner, staff, viewer):
    fid = _fabric(staff, colour="Black", in_storage_kg="82.5")["id"]
    oid = _new(owner)["id"]
    assert _take(viewer, oid, fid, 1).status_code == 403

    response = _take(staff, oid, fid, 83)
    assert response.status_code == 422 and response.json()["detail"] == f"Only 82.5 kg of {FLEECE} is in storage."
    assert _take(staff, oid, fid, 0).status_code == 422
    assert _take(staff, oid, fid, "abc").status_code == 422
    assert _take(staff, oid, 999999, 1).status_code == 422
    assert _take(staff, 999999, fid, 1).status_code == 404

    order = _ok(_take(staff, oid, fid, "82.5"))
    assert order["fabric_uses"] == [
        {"move_id": order["fabric_uses"][0]["move_id"], "fabric": {"id": fid, "name": FLEECE, "colour": "Black"}, "kg": "82.500"}
    ]
    assert _stock(staff, fid) == "0.000"
    move_id = order["fabric_uses"][0]["move_id"]

    other = _new(owner)["id"]
    assert _give_back(staff, other, move_id).status_code == 404
    assert _give_back(staff, oid, 999999).status_code == 404
    order = _ok(_give_back(staff, oid, move_id))
    assert order["fabric_uses"] == []
    assert _stock(staff, fid) == "82.500"
    response = _give_back(staff, oid, move_id)
    assert response.status_code == 422 and response.json()["detail"] == "That fabric was already given back."
    use = next(m for m in _detail(staff, fid)["moves"] if m["kind"] == "use")
    assert use["returned"] is True
    assert _row(staff, fid)["orders"] == 0


def test_an_order_whose_fabric_the_factory_buys_takes_none(owner, staff):
    fid = _fabric(staff, in_storage_kg=50)["id"]
    oid = _new(owner, fabric_bought_by="factory")["id"]
    response = _take(staff, oid, fid, 1)
    assert response.status_code == 422 and response.json()["detail"] == "The factory buys this order's fabric."
    assert _stock(staff, fid) == "50.000"


def test_a_closed_order_neither_takes_nor_gives_back(owner, staff):
    fid = _fabric(staff, in_storage_kg=50)["id"]
    oid = _new(owner)["id"]
    move_id = _ok(_take(staff, oid, fid, 5))["fabric_uses"][0]["move_id"]
    _ok(owner.post(f"/api/prod/orders/{oid}/cancel", json={"reason": "Dropped"}))
    response = _take(staff, oid, fid, 1)
    assert response.status_code == 422 and response.json()["detail"] == "Pick an order that is still in production."
    assert _give_back(staff, oid, move_id).status_code == 409


def test_who_buys_the_fabric_stays_hba_while_the_order_holds_some(owner, staff):
    fid = _fabric(staff, in_storage_kg=50)["id"]
    oid = _new(owner)["id"]
    move_id = _ok(_take(staff, oid, fid, 5))["fabric_uses"][0]["move_id"]
    response = owner.patch(f"/api/prod/orders/{oid}", json={"fabric_bought_by": "factory"})
    assert response.status_code == 422 and "Give it back" in response.json()["detail"]
    _ok(_give_back(staff, oid, move_id))
    assert _ok(owner.patch(f"/api/prod/orders/{oid}", json={"fabric_bought_by": "factory"}))["fabric_bought_by"] == "factory"


def test_cancelling_an_order_gives_back_everything_it_took(owner, staff):
    first = _fabric(staff, in_storage_kg=50)["id"]
    second = _fabric(staff, "Rib", in_storage_kg=10)["id"]
    oid = _new(owner)["id"]
    _ok(_take(staff, oid, first, 20))
    _ok(_take(staff, oid, first, 5))
    move_id = _ok(_take(staff, oid, second, 4))["fabric_uses"][-1]["move_id"]
    _ok(_give_back(staff, oid, move_id))
    _ok(_take(staff, oid, second, 3))
    assert (_stock(staff, first), _stock(staff, second)) == ("25.000", "7.000")

    order = _ok(owner.post(f"/api/prod/orders/{oid}/cancel", json={"reason": "Style dropped"}))
    assert order["fabric_uses"] == []
    assert (_stock(staff, first), _stock(staff, second)) == ("50.000", "10.000")
    returns = [m for m in _detail(staff, first)["moves"] if m["kind"] == "return"]
    assert sorted(m["kg"] for m in returns) == ["20.000", "5.000"]
    assert all(m["note"] == "Order cancelled" for m in returns)


# ── A New order with fabric ───────────────────────────────────────────────────


def _orders() -> int:
    with SessionLocal() as db:
        return db.query(ProdOrder).count()


def test_a_new_order_takes_its_fabric_in_the_same_save(owner, staff):
    first = _fabric(staff, in_storage_kg=50)["id"]
    second = _fabric(staff, "Rib", in_storage_kg=10)["id"]
    order = _new(owner, fabric=[{"fabric_id": second, "kg": "2.5"}, {"fabric_id": first, "kg": 40}])
    assert sorted((u["fabric"]["id"], u["kg"]) for u in order["fabric_uses"]) == sorted(
        [(first, "40.000"), (second, "2.500")]
    )
    assert (_stock(staff, first), _stock(staff, second)) == ("10.000", "7.500")


@pytest.mark.parametrize(
    "lines, over, words",
    [
        ([("first", 10), ("second", 11)], {}, "Only 7.5 kg of Rib is in storage."),
        ([("first", 1)], {"fabric_bought_by": "factory"}, "The factory buys this order's fabric: take none from storage."),
        ([("first", 1), ("first", 2)], {}, "Take each fabric once, with all its kilos."),
        ([("first", 0)], {}, "The kilos must be more than 0."),
    ],
)
def test_a_new_order_short_of_fabric_is_refused_and_writes_nothing(owner, staff, lines, over, words):
    ids = {"first": _fabric(staff, in_storage_kg=50)["id"], "second": _fabric(staff, "Rib", in_storage_kg="7.5")["id"]}
    before = _orders()
    body = [{"fabric_id": ids[name], "kg": kg} for name, kg in lines]
    from tests.test_prod_orders import _body

    response = owner.post("/api/prod/orders", json=_body(fabric=body, **over))
    assert response.status_code == 422 and response.json()["detail"] == words
    assert _orders() == before
    assert (_stock(staff, ids["first"]), _stock(staff, ids["second"])) == ("50.000", "7.500")


def test_a_new_order_takes_at_most_ten_fabrics(owner):
    from tests.test_prod_orders import _body

    lines = [{"fabric_id": n, "kg": 1} for n in range(1, 12)]
    assert owner.post("/api/prod/orders", json=_body(fabric=lines)).status_code == 422
    assert owner.post("/api/prod/orders", json=_body(fabric=[{"fabric_id": 1, "kg": 1, "x": 1}])).status_code == 422


# ── Voiding and editing a purchase that filled storage ────────────────────────


def test_voiding_a_purchase_takes_its_kilos_out_unless_orders_use_them(owner, staff):
    sid = _make(owner)["id"]
    fid = _fabric(staff)["id"]
    _into(owner, sid, fid, 100)
    pid = _purchase_id(sid, "Heavy fleece, black")
    oid = _new(owner)["id"]
    move_id = _ok(_take(staff, oid, fid, "30.5"))["fabric_uses"][0]["move_id"]

    response = owner.post(f"/api/prod/purchases/{pid}/void", json={"reason": "Wrong supplier"})
    assert response.status_code == 422
    assert response.json()["detail"] == (
        f"30.5 kg of {FLEECE} from this purchase is already used by orders. Give it back or count storage first."
    )
    assert _page(owner, sid)["purchases"][0]["voided"] is False
    assert _stock(owner, fid) == "69.500"

    _ok(_give_back(staff, oid, move_id))
    assert owner.post(f"/api/prod/purchases/{pid}/void", json={"reason": "Wrong supplier"}).status_code == 200
    assert _stock(owner, fid) == "0.000"
    moves = _detail(owner, fid)["moves"]
    assert (moves[0]["kind"], moves[0]["kg"], moves[0]["purchase"]["id"]) == ("void", "-100.000", pid)
    assert moves[0]["note"] == "Purchase voided"  # never the owner's reason
    assert _row(owner, fid)["bought_kg"] == "0.000"
    assert _row(owner, fid)["price_per_kg_piastres"] is None


def test_a_purchase_that_filled_storage_keeps_its_kilos_but_its_dates_change(owner, staff):
    sid = _make(owner)["id"]
    fid = _fabric(staff)["id"]
    _into(owner, sid, fid, 100)
    pid = _purchase_id(sid, "Heavy fleece, black")
    assert staff.patch(f"/api/prod/purchases/{pid}", json={"quantity": 5}).status_code == 422
    assert staff.patch(f"/api/prod/purchases/{pid}", json={"note": "Two rolls short"}).status_code == 200
    with SessionLocal() as db:
        actor = db.scalar(select(UserAccount).where(UserAccount.email == "qc@example.com"))
        for change in ({"quantity": 5}, {"unit": "m"}, {"part": "other"}):
            with pytest.raises(Refused, match="This purchase filled fabric storage; void it and record it again"):
                supplier_service.edit_purchase(db, pid, change, actor)
            db.rollback()


# ── The order's fabric cost ───────────────────────────────────────────────────


def test_the_fabric_cost_is_offered_to_the_owner_per_piece_planned_then_cut(owner, staff, viewer):
    sid = _make(owner)["id"]
    fid = _fabric(staff)["id"]
    _into(owner, sid, fid, 100, 16000)
    oid = _new(owner)["id"]  # 1,000 pieces planned
    order = _ok(_take(staff, oid, fid, "25.5"))
    # The staff's answer carries no money.
    _no_money(order)
    assert "fabric_cost" not in order

    seen = owner.get(f"/api/prod/orders/{oid}").json()["order"]
    # 25.5 kg x 16,000 = 408,000; over 1,000 planned = 408.
    assert seen["fabric_cost"] == {"total_piastres": 408000, "per_piece_piastres": 408, "pieces": 1000, "basis": "planned"}

    _to_cutting(owner, oid)
    _cut(owner, oid)  # 972 cut
    seen = owner.get(f"/api/prod/orders/{oid}").json()["order"]
    # 408,000 / 972 = 419.75 -> 420.
    assert seen["fabric_cost"] == {"total_piastres": 408000, "per_piece_piastres": 420, "pieces": 972, "basis": "cut"}
    # Nothing was written into the order's actual cost: the owner presses it.
    assert next(p for p in seen["cost"]["parts"] if p["part"] == "fabric")["actual_piastres"] is None
    pressed = _ok(owner.patch(f"/api/prod/orders/{oid}", json={"actual_fabric_piastres": 420}))
    assert next(p for p in pressed["cost"]["parts"] if p["part"] == "fabric")["actual_piastres"] == 420

    for client in (staff, viewer):
        body = client.get(f"/api/prod/orders/{oid}").json()["order"]
        _no_money(body)
        assert "fabric_cost" not in body
        assert body["fabric_uses"][0]["kg"] == "25.500"


def test_the_fabric_cost_is_none_without_uses_or_without_a_price(owner, staff):
    fid = _fabric(staff, in_storage_kg=10)["id"]
    oid = _new(owner)["id"]
    assert owner.get(f"/api/prod/orders/{oid}").json()["order"]["fabric_cost"] is None
    _ok(_take(staff, oid, fid, 2))
    assert owner.get(f"/api/prod/orders/{oid}").json()["order"]["fabric_cost"] is None


# ── The migration ─────────────────────────────────────────────────────────────


def _version() -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_the_downgrade_refuses_while_a_fabric_exists(owner, staff):
    from alembic import command
    from alembic.config import Config

    _fabric(staff)
    with pytest.raises(RuntimeError, match="fabric"):
        command.downgrade(Config("alembic.ini"), "b3d5f7a90041")
    assert _version() == alembic_head()


def test_the_moves_hold_their_shape_in_the_database(owner, staff):
    fid = _fabric(staff)["id"]
    oid = _new(owner)["id"]
    bad = [
        "INSERT INTO prod_fabric_move (fabric_id, kind, kg) VALUES (:f, 'count', 0)",
        "INSERT INTO prod_fabric_move (fabric_id, kind, kg) VALUES (:f, 'use', -1)",  # no order
        "INSERT INTO prod_fabric_move (fabric_id, kind, kg, order_id) VALUES (:f, 'use', 1, :o)",  # wrong sign
        "INSERT INTO prod_fabric_move (fabric_id, kind, kg) VALUES (:f, 'purchase', 1)",  # no purchase
        "INSERT INTO prod_fabric_move (fabric_id, kind, kg, order_id) VALUES (:f, 'return', 1, :o)",  # undoes nothing
        "INSERT INTO prod_fabric_move (fabric_id, kind, kg) VALUES (:f, 'gift', 1)",
    ]
    from sqlalchemy.exc import IntegrityError

    for sql in bad:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text(sql), {"f": fid, "o": oid})
