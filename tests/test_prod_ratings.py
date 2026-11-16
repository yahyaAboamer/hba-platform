"""Production ratings and the performance record (ADR 0084, decision 10; batch 6a).

The owner rates each supplier on a settled order; the timing stars are
suggested from the real lateness; a supplier's record (usual lateness, average
stars, reject rate) is calculated, never typed. **No money anywhere**: the QC
manager and the viewer read all of it.

Every name and figure here is invented. The order helpers are batch 1's.
"""

import importlib.util  # noqa: F401
from pathlib import Path  # noqa: F401

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.db import SessionLocal, engine
from app.modules.production.orders.models import ProdRating
from app.modules.production.orders.services import ratings as service
from app.shared.models.audit import AuditEvent
from tests.test_prod_orders import (  # noqa: F401  (fixtures)
    FIRST,
    FIX,
    SECOND,
    TODAY,
    _day,
    _deliver,
    _inspected,
    _cut,
    _new,
    _ok,
    _record_sql,
    _to_cutting,
    owner,
    staff,
    viewer,
)

#: Keys that name money. (`reject_rate` is a share of pieces, not a rate of pay.)
MONEY_WORDS = (
    "piastres", "cost", "settlement", "payable", "price", "value", "deduction", "held", "owed", "paid",
    "balance", "amount", "account", "deposit", "receipt", "total", "payment", "opening", "adjustment", "method",
)


def _no_money(payload, where: str = "") -> None:
    """Recursively: no key that names money, at any depth."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = key.lower().replace("reject_rate", "")
            assert not any(word in lowered for word in MONEY_WORDS), f"money key {where}.{key}"
            assert "rate" not in lowered, f"money key {where}.{key}"
            _no_money(value, f"{where}.{key}")
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            _no_money(item, f"{where}[{index}]")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _supplier(client: TestClient, name: str) -> str:
    response = client.post("/api/prod/suppliers", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["supplier"]["id"]


def _buy(client: TestClient, sid: str, item: str, *, order_id: int | None = None, expected: int = -20, late: int | None = 0,
         bought: int = -30) -> int:
    """One purchase expected on day ``expected`` and, when ``late`` is not None,
    received ``late`` days after that."""
    body = {
        "item": item, "quantity": 10, "unit": "kg", "unit_price_piastres": 1000, "part": "fabric",
        "bought_on": _day(bought), "expected_on": _day(expected),
    }
    if order_id:
        body["order_id"] = order_id
    response = client.post(f"/api/prod/suppliers/{sid}/purchases", json=body)
    assert response.status_code == 201, response.text
    pid = response.json()["purchase_id"]
    if late is not None:
        received = client.patch(f"/api/prod/purchases/{pid}", json={"received_on": _day(expected + late)})
        assert received.status_code == 200, received.text
    return pid


def _through_the_warehouse(client: TestClient, oid: int) -> None:
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
    _ok(_deliver(client, oid, "fix", FIX, counted_on=_day(-1), counted=FIX))


def _lateness(oid: int, days: int) -> None:
    """Make the order's lateness ``days``: the warehouse was done on day -1."""
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE prod_order SET target_date = :d WHERE id = :id"),
            {"d": TODAY.fromordinal(TODAY.toordinal() - 1 - days), "id": oid},
        )


def _closed(client: TestClient, *, late: int = 0, buys=(), **over) -> int:
    """A settled order. ``buys`` is ``(supplier_id, days_late)`` for a purchase
    bought for it while it was open (``None`` days: never received)."""
    oid = _new(client, **over)["id"]
    for index, (sid, days) in enumerate(buys):
        _buy(client, sid, f"Material {oid}-{index}", order_id=oid, late=days)
    _through_the_warehouse(client, oid)
    _ok(client.post(f"/api/prod/orders/{oid}/settle"))
    _lateness(oid, late)
    return oid


def _sheet(client: TestClient, oid: int) -> dict:
    response = client.get(f"/api/prod/orders/{oid}/ratings")
    assert response.status_code == 200, response.text
    return response.json()


def _rate(client: TestClient, oid: int, sid: str, quality=4, timing=4, dealing=4, **extra):
    return client.put(
        f"/api/prod/orders/{oid}/ratings/{sid}",
        json={"quality": quality, "timing": timing, "dealing": dealing, **extra},
    )


def _on(sheet: dict) -> dict:
    return {row["supplier"]["id"]: row for row in sheet["suppliers"]}


def _page(client: TestClient, sid: str) -> dict:
    response = client.get(f"/api/prod/suppliers/{sid}")
    assert response.status_code == 200, response.text
    return response.json()["supplier"]


def _listed(client: TestClient, sid: str) -> dict:
    rows = client.get("/api/prod/suppliers").json()["suppliers"]
    return next(row for row in rows if row["id"] == sid)


# ── Who is on an order ────────────────────────────────────────────────────────


def test_who_is_rated_is_the_factory_the_print_house_and_each_seller_of_materials_once(owner):
    mat = _supplier(owner, "Fabric A")
    zip_ = _supplier(owner, "Zips B")
    voided = _supplier(owner, "Void C")
    oid = _new(owner, printing="outside", print_supplier_id="prt")["id"]
    _buy(owner, mat, "Fleece", order_id=oid, late=None)
    _buy(owner, mat, "Lining", order_id=oid, late=None)  # the same supplier twice: still once
    _buy(owner, zip_, "Zips", order_id=oid, late=None)
    _buy(owner, "fac", "Thread", order_id=oid, late=None)  # the factory sells too: once, as the factory
    _buy(owner, "prt", "Ink", order_id=oid, late=None)  # the print house sells too: once, as the print house
    gone = _buy(owner, voided, "Buttons", order_id=oid, late=None)
    assert owner.post(f"/api/prod/purchases/{gone}/void", json={"reason": "Wrong order"}).status_code == 200
    _through_the_warehouse(owner, oid)
    _ok(owner.post(f"/api/prod/orders/{oid}/settle"))

    sheet = _sheet(owner, oid)
    assert sheet["ratable"] is True
    assert [(row["supplier"]["id"], row["role"]) for row in sheet["suppliers"]] == [
        ("fac", "factory"), ("prt", "print"), (mat, "materials"), (zip_, "materials"),
    ]
    assert sheet["suppliers"][0]["supplier"]["name"] == "Main factory"
    assert all(row["rating"] is None for row in sheet["suppliers"])


def test_a_print_house_is_only_on_the_order_when_printing_is_outside(owner):
    oid = _closed(owner, printing="factory")
    assert [row["supplier"]["id"] for row in _sheet(owner, oid)["suppliers"]] == ["fac"]


def test_only_a_closed_order_is_ratable(owner):
    open_order = _new(owner)["id"]
    assert _sheet(owner, open_order) == {"ratable": False, "suppliers": []}
    assert _rate(owner, open_order, "fac").status_code == 409

    cancelled = _new(owner)["id"]
    assert owner.post(f"/api/prod/orders/{cancelled}/cancel", json={"reason": "Changed our mind"}).status_code == 200
    assert _sheet(owner, cancelled) == {"ratable": False, "suppliers": []}
    assert _rate(owner, cancelled, "fac").status_code == 409

    assert owner.get("/api/prod/orders/9999/ratings").status_code == 404
    assert _rate(owner, 9999, "fac").status_code == 404


# ── The timing suggestion ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "days, stars",
    [(0, 5), (1, 4), (2, 4), (3, 3), (4, 3), (5, 3), (6, 2), (9, 2), (10, 1), (11, 1), (60, 1)],
)
def test_the_suggestion_table(days, stars):
    assert service.stars_for_days(days) == stars


def test_the_suggestion_follows_the_real_lateness_of_each_supplier(owner):
    mat = _supplier(owner, "Fabric A")
    oid = _closed(owner, printing="outside", print_supplier_id="prt", buys=[(mat, 4)])
    # The factory: the order's own lateness at each boundary, read afresh every time.
    for days, stars in [(0, 5), (1, 4), (2, 4), (3, 3), (5, 3), (6, 2), (9, 2), (10, 1)]:
        _lateness(oid, days)
        row = _on(_sheet(owner, oid))["fac"]
        assert (row["lateness_days"], row["suggested_timing"]) == (days, stars)
    # A materials supplier: its own purchase, 4 days late, whatever the factory was.
    row = _on(_sheet(owner, oid))[mat]
    assert (row["lateness_days"], row["suggested_timing"]) == (4, 3)
    # A print house with no purchases has no lateness and no suggestion.
    row = _on(_sheet(owner, oid))["prt"]
    assert (row["lateness_days"], row["suggested_timing"]) == (None, None)


def test_a_materials_supplier_is_as_late_as_its_latest_purchase_and_none_until_one_arrived(owner):
    mat = _supplier(owner, "Fabric A")
    waiting = _supplier(owner, "Zips B")
    oid = _new(owner)["id"]
    _buy(owner, mat, "Fleece", order_id=oid, late=1)
    _buy(owner, mat, "Lining", order_id=oid, late=7)
    _buy(owner, mat, "Thread", order_id=oid, late=0)
    _buy(owner, waiting, "Zips", order_id=oid, late=None)
    _through_the_warehouse(owner, oid)
    _ok(owner.post(f"/api/prod/orders/{oid}/settle"))
    on = _on(_sheet(owner, oid))
    assert (on[mat]["lateness_days"], on[mat]["suggested_timing"]) == (7, 2)
    assert (on[waiting]["lateness_days"], on[waiting]["suggested_timing"]) == (None, None)


# ── Saving and changing a rating ──────────────────────────────────────────────


def test_a_rating_is_saved_changed_in_place_and_audited_without_its_note(owner, viewer):
    oid = _closed(owner)
    saved = _rate(owner, oid, "fac", 4, 5, 3, note="  Quick to answer,\n clean work  ")
    assert saved.status_code == 200, saved.text
    row = _on(saved.json())["fac"]["rating"]
    assert (row["quality"], row["timing"], row["dealing"]) == (4, 5, 3)
    assert row["note"] == "Quick to answer, clean work"  # tidied like every other note
    assert row["updated_at"].endswith("Z")
    assert _on(_sheet(viewer, oid))["fac"]["rating"]["quality"] == 4

    changed = _rate(owner, oid, "fac", 2, 2, 2)
    assert changed.status_code == 200
    row = _on(changed.json())["fac"]["rating"]
    assert (row["quality"], row["timing"], row["dealing"], row["note"]) == (2, 2, 2, None)
    with SessionLocal() as db:
        rows = list(db.scalars(select(ProdRating)))
        assert len(rows) == 1 and rows[0].created_by is not None and rows[0].updated_by is not None
        events = list(
            db.scalars(
                select(AuditEvent).where(AuditEvent.action == "production.rating_saved").order_by(AuditEvent.id)
            )
        )
    assert [e.subject for e in events] == [f"production:order:{oid}"] * 2
    summaries = [e.after_json["summary"] for e in events]
    assert summaries[0].startswith("Rated Main factory on PO-") and summaries[0].endswith(
        "quality 4, timing 5, dealing 3"
    )
    assert "quality 2, timing 2, dealing 2" in summaries[1]
    assert not any("Quick to answer" in str(e.after_json) for e in events)  # never the note


def test_every_supplier_on_the_order_can_be_rated_separately(owner):
    mat = _supplier(owner, "Fabric A")
    oid = _closed(owner, printing="outside", print_supplier_id="prt", buys=[(mat, 0)])
    for sid, stars in (("fac", 5), ("prt", 3), (mat, 1)):
        assert _rate(owner, oid, sid, stars, stars, stars).status_code == 200
    on = _on(_sheet(owner, oid))
    assert {sid: row["rating"]["quality"] for sid, row in on.items()} == {"fac": 5, "prt": 3, mat: 1}


def test_a_rating_refuses_what_it_should(owner, staff, viewer):
    other = _supplier(owner, "Not on it")
    oid = _closed(owner)
    # A supplier that did not work on the order: 404 (also an unknown one).
    assert _rate(owner, oid, other).status_code == 404
    assert _rate(owner, oid, "nobody").status_code == 404
    # Stars outside 1..5, missing or not whole numbers: 422.
    for bad in (0, 6, -1, 2.5, "4", None, True):
        response = owner.put(
            f"/api/prod/orders/{oid}/ratings/fac", json={"quality": bad, "timing": 4, "dealing": 4}
        )
        assert response.status_code == 422, (bad, response.text)
    assert owner.put(f"/api/prod/orders/{oid}/ratings/fac", json={"quality": 4, "timing": 4}).status_code == 422
    assert _rate(owner, oid, "fac", note="x" * 1001).status_code == 422
    assert _rate(owner, oid, "fac", note="x" * 1000).status_code == 200
    # Only the owner writes; the QC manager and a viewer read.
    assert _rate(staff, oid, "fac").status_code == 403
    assert _rate(viewer, oid, "fac").status_code == 403
    assert staff.get(f"/api/prod/orders/{oid}/ratings").status_code == 200
    assert viewer.get(f"/api/prod/orders/{oid}/ratings").status_code == 200
    with TestClient(owner.app) as stranger:
        assert stranger.get(f"/api/prod/orders/{oid}/ratings").status_code == 401
    with SessionLocal() as db:
        assert len(list(db.scalars(select(ProdRating)))) == 1  # only the good one


def test_the_service_checks_the_stars_itself(owner):
    oid = _closed(owner)
    with SessionLocal() as db:
        from app.shared.models.identity import UserAccount

        actor = db.scalar(select(UserAccount))
        with pytest.raises(service.Refused):
            service.save(db, oid, "fac", {"quality": 7, "timing": 4, "dealing": 4}, actor)
        with pytest.raises(service.Refused):
            service.save(db, oid, "fac", {"quality": True, "timing": 4, "dealing": 4}, actor)
        db.rollback()


# ── The record ────────────────────────────────────────────────────────────────


def test_usual_lateness_is_the_median_of_the_last_ten_known_figures(owner):
    mat = _supplier(owner, "Fabric A")
    assert _listed(owner, mat)["usual_lateness_days"] is None and _page(owner, mat)["usual_lateness_days"] is None
    # 14 received purchases, oldest first: four 40 days late, then 1,1,1,1,1,3,3,3,3,3.
    lates = [40, 40, 40, 40, 1, 1, 1, 1, 1, 3, 3, 3, 3, 3]
    for index, late in enumerate(lates):
        _buy(owner, mat, f"Roll {index}", expected=-40 + index - late, late=late, bought=-200)
    # The last ten are 1 x5 and 3 x5: the median is 2. (All fourteen would give 3.)
    assert _listed(owner, mat)["usual_lateness_days"] == 2
    assert _page(owner, mat)["usual_lateness_days"] == 2


def test_usual_lateness_rounds_whole_days_and_says_on_time_as_zero(owner):
    mat = _supplier(owner, "Fabric A")
    for index, late in enumerate([0, 0, 0]):
        _buy(owner, mat, f"Roll {index}", expected=-20 + index, late=late)
    assert _listed(owner, mat)["usual_lateness_days"] == 0
    other = _supplier(owner, "Fabric B")
    for index, late in enumerate([2, 3]):  # median 2.5 -> 3
        _buy(owner, other, f"Roll {index}", expected=-20 + index, late=late)
    assert _listed(owner, other)["usual_lateness_days"] == 3
    # Early or not received yet or no expected date: not a figure.
    third = _supplier(owner, "Fabric C")
    _buy(owner, third, "Early", expected=-10, late=-3)  # arrived early: counts as on time
    _buy(owner, third, "Waiting", expected=-10, late=None)
    assert _listed(owner, third)["usual_lateness_days"] == 0


def test_a_factory_s_figures_are_its_orders_lateness_and_the_reject_rate_of_its_closed_orders(owner):
    first = _closed(owner, late=4)
    second = _closed(owner, late=0)
    # Two finished orders, 4 and 0 days late: the median is 2.
    assert _listed(owner, "fac")["usual_lateness_days"] == 2
    page = _page(owner, "fac")
    orders = {o["id"]: o for o in page["orders"]}
    assert (orders[first]["lateness_days"], orders[second]["lateness_days"]) == (4, 0)
    # 16 rejected of 972 cut: 1.6 per cent, on each closed factory order.
    assert orders[first]["reject_rate"] == 1.6 and orders[second]["reject_rate"] == 1.6
    assert orders[first]["status"] == "closed" and orders[first]["role"] == "factory"
    assert orders[first]["closed_on"] == TODAY.isoformat()
    assert orders[first]["rating"] is None
    # An open order carries none of it.
    open_order = _new(owner)["id"]
    row = next(o for o in _page(owner, "fac")["orders"] if o["id"] == open_order)
    assert (row["lateness_days"], row["reject_rate"], row["closed_on"], row["rating"]) == (None, None, None, None)


def test_ratings_are_averaged_to_one_decimal_with_their_count(owner):
    assert _listed(owner, "fac")["ratings"] is None and _page(owner, "fac")["ratings"] is None
    orders = [_closed(owner) for _ in range(3)]
    for oid, (q, t, d) in zip(orders, [(4, 5, 3), (5, 5, 4), (5, 2, 4)]):
        assert _rate(owner, oid, "fac", q, t, d).status_code == 200
    want = {"quality": 4.7, "timing": 4.0, "dealing": 3.7, "count": 3}  # 14/3, 12/3, 11/3
    assert _listed(owner, "fac")["ratings"] == want
    assert _page(owner, "fac")["ratings"] == want
    # A supplier that was never rated stays null.
    assert _listed(owner, "prt")["ratings"] is None


def test_the_supplier_page_lists_orders_it_only_sold_materials_for(owner):
    mat = _supplier(owner, "Fabric A")
    closed = _closed(owner, buys=[(mat, 3)])
    open_order = _new(owner)["id"]
    _buy(owner, mat, "Fleece", order_id=open_order, late=None)
    assert _rate(owner, closed, mat, 3, 2, 5, note="Short on the first roll").status_code == 200
    page = _page(owner, mat)
    orders = {o["id"]: o for o in page["orders"]}
    assert set(orders) == {closed, open_order}
    assert all(o["role"] == "materials" for o in orders.values())
    row = orders[closed]
    assert (row["lateness_days"], row["reject_rate"], row["closed_on"]) == (3, None, TODAY.isoformat())
    assert (row["rating"]["quality"], row["rating"]["timing"], row["rating"]["dealing"]) == (3, 2, 5)
    assert row["rating"]["note"] == "Short on the first roll"
    assert orders[open_order]["rating"] is None and orders[open_order]["lateness_days"] is None
    # A voided purchase takes it off the page.
    other = _supplier(owner, "Zips B")
    gone = _buy(owner, other, "Zips", order_id=open_order, late=None)
    assert _page(owner, other)["orders"][0]["id"] == open_order
    assert owner.post(f"/api/prod/purchases/{gone}/void", json={"reason": "Wrong order"}).status_code == 200
    assert _page(owner, other)["orders"] == []
    # The materials supplier's record counts its late purchase.
    assert _listed(owner, mat)["usual_lateness_days"] == 3


def test_a_cancelled_order_is_neither_rated_nor_counted(owner):
    oid = _new(owner)["id"]
    assert owner.post(f"/api/prod/orders/{oid}/cancel", json={"reason": "Changed our mind"}).status_code == 200
    row = next(o for o in _page(owner, "fac")["orders"] if o["id"] == oid)
    assert (row["status"], row["rating"], row["closed_on"], row["lateness_days"]) == ("cancelled", None, None, None)
    assert _listed(owner, "fac")["usual_lateness_days"] is None


def test_the_list_does_not_ask_the_database_once_per_supplier(owner):
    mat = _supplier(owner, "Fabric A")
    _buy(owner, mat, "Fleece", late=2)
    _closed(owner)

    def statements() -> int:
        seen, stop = _record_sql()
        try:
            assert owner.get("/api/prod/suppliers").status_code == 200
        finally:
            stop()
        return len(seen)

    few = statements()
    for index in range(8):
        _buy(owner, _supplier(owner, f"More {index}"), "Cloth", late=1)
    assert statements() == few


# ── No money, for anybody who is not the owner ────────────────────────────────


def test_the_ratings_and_the_record_carry_no_money_for_anybody(owner, staff, viewer):
    mat = _supplier(owner, "Fabric A")
    oid = _closed(owner, printing="outside", print_supplier_id="prt", buys=[(mat, 2)])
    for sid in ("fac", "prt", mat):
        assert _rate(owner, oid, sid, 4, 3, 5, note="Fine").status_code == 200
    answered = _rate(owner, oid, "fac", 4, 3, 5)
    _no_money(answered.json(), "put")
    for who, client in (("owner", owner), ("staff", staff), ("viewer", viewer)):
        _no_money(_sheet(client, oid), f"{who}.sheet")
    for who, client in (("staff", staff), ("viewer", viewer)):
        _no_money(client.get("/api/prod/suppliers").json(), f"{who}.list")
        for sid in ("fac", "prt", mat):
            _no_money(client.get(f"/api/prod/suppliers/{sid}").json(), f"{who}.page.{sid}")
    # The owner's answers add money only where they always did, never in the ratings sheet.
    assert "owed_piastres" in owner.get(f"/api/prod/suppliers/{mat}").json()["supplier"]


# ── The migration ─────────────────────────────────────────────────────────────


def test_the_downgrade_refuses_while_a_rating_exists(owner):
    from alembic import command
    from alembic.config import Config

    oid = _closed(owner)
    assert _rate(owner, oid, "fac").status_code == 200
    with pytest.raises(RuntimeError, match="rating"):
        command.downgrade(Config("alembic.ini"), "b8d5f1a30035")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "c9e6a2b40036"
        assert connection.execute(text("SELECT count(*) FROM prod_rating")).scalar_one() == 1


def test_the_database_refuses_stars_outside_one_to_five_and_a_second_rating(owner):
    oid = _closed(owner)
    insert = text(
        "INSERT INTO prod_rating (order_id, supplier_id, quality, timing, dealing) VALUES (:o, 'fac', :q, 3, 3)"
    )
    for bad in (0, 6):
        with pytest.raises(Exception, match="prod_rating_quality_range"):
            with engine.begin() as connection:
                connection.execute(insert, {"o": oid, "q": bad})
    with engine.begin() as connection:
        connection.execute(insert, {"o": oid, "q": 3})
    with pytest.raises(Exception, match="prod_rating_once"):
        with engine.begin() as connection:
            connection.execute(insert, {"o": oid, "q": 4})
