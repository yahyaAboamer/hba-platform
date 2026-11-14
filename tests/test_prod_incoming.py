"""Production's Incoming under /api/prod/incoming (ADR 0084, decision 5; batch 3).

What is still to arrive at Khazenly, and every delivery with its two counts,
worked out on each read from the orders. Nothing is stored. Every name and
figure here is invented. The order helpers are batch 1's.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.db import SessionLocal, engine
from app.main import app
from app.modules.production.orders.models import ProdOrder, SIZES
from app.modules.production.orders.services import incoming
from tests.test_prod_orders import (  # noqa: F401  (fixtures)
    CUT,
    FIRST,
    FIX,
    INSPECTED,
    INSPECTION_REASONS,
    PLANNED,
    SECOND,
    TARGET,
    TODAY,
    _all_the_way,
    _cut,
    _day,
    _deliver,
    _inspected,
    _new,
    _no_money,
    _ok,
    _person,
    _to_cutting,
    owner,
    staff,
    viewer,
)

URL = "/api/prod/incoming"


def _incoming(client: TestClient) -> dict:
    response = client.get(URL)
    assert response.status_code == 200, response.text
    return response.json()


def _full(counts: dict) -> dict:
    """Every size, in the screens' order, zero where there are none."""
    return {size: counts.get(size, 0) for size in SIZES}


def _set_due(order_id: int, day: date) -> None:
    with SessionLocal() as db:
        db.get(ProdOrder, order_id).delivery_date = day
        db.commit()


def _ready(client: TestClient, **over) -> int:
    """An order through the final inspection: 926 finished pieces to come, 30 to fix."""
    oid = _new(client, **over)["id"]
    _to_cutting(client, oid)
    _cut(client, oid)
    _inspected(client, oid)
    return oid


def _arrival(payload: dict, order_id: int, kind: str = "finished") -> dict:
    [row] = [r for r in payload["arrivals"] if r["order"]["id"] == order_id and r["kind"] == kind]
    return row


def _delivery_of(payload: dict, order_id: int, number: int) -> dict:
    [row] = [r for r in payload["deliveries"] if r["order"]["id"] == order_id and r["number"] == number]
    return row


# ── Who may come in ───────────────────────────────────────────────────────────


def test_signed_out_and_other_departments_are_refused(owner):
    with TestClient(app) as stranger:
        assert stranger.get(URL).status_code == 401
    inbox = _person("cs@example.com", "customer_service")
    assert inbox.get(URL).status_code == 403


def test_the_owner_the_qc_manager_and_a_viewer_all_read_it(owner, staff, viewer):
    _new(owner)
    for client in (owner, staff, viewer):
        assert _incoming(client)["arrivals"][0]["order"]["style_name"] == "Oversized hoodie"


def test_nothing_is_written_by_reading_it(owner):
    for verb in (owner.post, owner.put, owner.patch, owner.delete):
        assert verb(URL).status_code == 405


# ── The shape ─────────────────────────────────────────────────────────────────


def test_with_no_orders_there_is_nothing_and_the_months_are_still_named(owner):
    payload = _incoming(owner)
    assert payload["today"] == TODAY.isoformat()
    assert payload["arrivals"] == [] and payload["deliveries"] == []
    this_first = TODAY.replace(day=1)
    next_first = date(this_first.year + (this_first.month == 12), this_first.month % 12 + 1, 1)
    assert payload["totals"] == {
        "to_come_total": 0,
        "this_month": {"month": this_first.strftime("%Y-%m"), "label": this_first.strftime("%B"), "pieces": 0},
        "next_month": {"month": next_first.strftime("%Y-%m"), "label": next_first.strftime("%B"), "pieces": 0},
        "waiting_for_count": 0,
        "mismatch_pieces": 0,
    }


def test_a_new_order_is_one_arrival_from_the_plan(owner):
    order = _new(owner)
    payload = _incoming(owner)
    assert _full(PLANNED) == {"XS": 0, "S": 150, "M": 300, "L": 300, "XL": 180, "XXL": 70}
    assert payload["arrivals"] == [
        {
            "key": f"order:{order['id']}:finished",
            "kind": "finished",
            "order": {"id": order["id"], "code": order["code"], "style_name": "Oversized hoodie", "colour": "Black"},
            "factory": "Main factory",
            "basis": "planned",
            "expected": {"sizes": _full(PLANNED), "total": 1000},
            "shipped": {"sizes": _full({}), "total": 0},
            "to_come": {"sizes": _full(PLANNED), "total": 1000},
            "due": TARGET.isoformat(),
            "late_days": 0,
            "stage": {"key": "sample", "label": "Sample", "position": 2},
            "status_words": "sample not approved yet",
            "can_record": False,
        }
    ]
    assert payload["deliveries"] == []
    assert payload["totals"]["to_come_total"] == 1000


# ── The expected count, at each point ────────────────────────────────────────


def test_the_expected_count_follows_the_order_from_the_plan_to_cut_to_passed(owner, staff):
    oid = _new(owner)["id"]
    assert _arrival(_incoming(owner), oid)["status_words"] == "sample not approved yet"

    _ok(owner.post(f"/api/prod/orders/{oid}/sample", json={"decision": "changes", "note": "Longer sleeves"}))
    assert _arrival(_incoming(owner), oid)["status_words"] == "waiting for the changed sample"

    _ok(owner.post(f"/api/prod/orders/{oid}/sample", json={"decision": "approved"}))
    _ok(staff.post(f"/api/prod/orders/{oid}/stages/materials/complete", json={}))
    row = _arrival(_incoming(owner), oid)
    assert (row["stage"]["key"], row["status_words"]) == ("fabric_check", "fabric being checked")
    _ok(staff.post(f"/api/prod/orders/{oid}/stages/fabric_check/complete", json={"result": "passed"}))
    assert _arrival(_incoming(owner), oid)["status_words"] == "pattern being checked"
    _ok(staff.post(f"/api/prod/orders/{oid}/stages/pattern_check/complete", json={}))
    row = _arrival(_incoming(owner), oid)
    assert (row["basis"], row["expected"]["total"], row["can_record"]) == ("planned", 1000, False)
    assert (row["stage"]["key"], row["status_words"]) == ("cutting", "being cut, final numbers after cutting")

    _cut(owner, oid)
    row = _arrival(_incoming(owner), oid)
    assert row["basis"] == "cut"
    assert row["expected"] == {"sizes": _full(CUT), "total": 972}
    assert row["to_come"] == {"sizes": _full(CUT), "total": 972}
    assert row["stage"]["key"] == "making" and row["status_words"].startswith("being made")
    # Nothing has passed inspection yet, so the order's own form would refuse a delivery.
    assert row["can_record"] is False

    _ok(staff.post(f"/api/prod/orders/{oid}/stages/making/complete", json={}))
    row = _arrival(_incoming(owner), oid)
    assert (row["stage"]["key"], row["basis"]) == ("final_inspection", "cut")
    assert row["status_words"].startswith("being inspected")

    # Saved in part: still counted from the cut, but pieces that passed can already leave.
    _ok(
        staff.put(
            f"/api/prod/orders/{oid}/inspection",
            json={"sizes": {"M": {"passed": 200, "to_fix": 0, "rejected": 0}}},
        )
    )
    row = _arrival(_incoming(owner), oid)
    assert (row["basis"], row["expected"]["total"], row["can_record"]) == ("cut", 972, True)

    _ok(
        staff.put(
            f"/api/prod/orders/{oid}/inspection",
            json={"sizes": INSPECTED, "complete": True, "reasons": INSPECTION_REASONS},
        )
    )
    payload = _incoming(owner)
    row = _arrival(payload, oid)
    assert row["basis"] == "passed"
    assert row["expected"]["total"] == 926 and row["to_come"]["total"] == 926
    assert row["expected"]["sizes"] == _full({s: v["passed"] for s, v in INSPECTED.items()})
    assert (row["stage"]["key"], row["status_words"], row["can_record"]) == ("warehouse", "arriving as pieces finish", True)
    # The same figure the order says it is waiting for.
    assert owner.get(f"/api/prod/orders/{oid}").json()["order"]["next_action"]["what"] == "Receive 926 pieces"
    assert payload["totals"]["to_come_total"] == 926 + 30


def test_a_partial_delivery_takes_its_pieces_off_per_size_and_in_total(owner):
    oid = _ready(owner)
    _ok(_deliver(owner, oid, "finished", FIRST))
    payload = _incoming(owner)
    row = _arrival(payload, oid)
    assert row["shipped"] == {"sizes": _full(FIRST), "total": 480}
    assert row["expected"]["total"] == 926
    assert row["to_come"]["total"] == 446
    assert row["to_come"]["sizes"] == _full(SECOND)  # 926 passed minus the first 480, size by size
    assert row["can_record"] is True
    # A delivery of fix pieces does not touch the finished row, and the other way round.
    assert _arrival(payload, oid, "fix")["to_come"]["total"] == 30

    _ok(_deliver(owner, oid, "fix", {"S": 5, "M": 8}))
    payload = _incoming(owner)
    fix = _arrival(payload, oid, "fix")
    assert fix["shipped"]["total"] == 13 and fix["to_come"]["total"] == 17
    assert fix["to_come"]["sizes"] == _full({"L": 9, "XL": 5, "XXL": 3})
    assert _arrival(payload, oid)["to_come"]["total"] == 446
    assert payload["totals"]["to_come_total"] == 446 + 17


def test_an_arrival_goes_once_everything_of_its_kind_has_left_the_factory(owner):
    oid = _ready(owner)
    _ok(_deliver(owner, oid, "finished", FIRST))
    _ok(_deliver(owner, oid, "finished", SECOND))
    payload = _incoming(owner)
    assert [(r["kind"], r["to_come"]["total"]) for r in payload["arrivals"]] == [("fix", 30)]
    _ok(_deliver(owner, oid, "fix", FIX))
    payload = _incoming(owner)
    assert payload["arrivals"] == [] and payload["totals"]["to_come_total"] == 0
    assert len(payload["deliveries"]) == 3  # shipped but not yet counted: they still need Khazenly


def test_a_fix_row_waits_for_the_final_inspection(owner):
    oid = _new(owner)["id"]
    _to_cutting(owner, oid)
    _cut(owner, oid)
    assert {r["kind"] for r in _incoming(owner)["arrivals"]} == {"finished"}
    _ok(owner.post(f"/api/prod/orders/{oid}/stages/making/complete", json={}))
    assert {r["kind"] for r in _incoming(owner)["arrivals"]} == {"finished"}
    _ok(
        owner.put(
            f"/api/prod/orders/{oid}/inspection",
            json={"sizes": INSPECTED, "complete": True, "reasons": INSPECTION_REASONS},
        )
    )
    fix = _arrival(_incoming(owner), oid, "fix")
    assert (fix["basis"], fix["status_words"], fix["can_record"]) == (None, "repaired pieces", True)
    assert fix["expected"] == {"sizes": _full(FIX), "total": 30}
    assert fix["due"] == TARGET.isoformat() and fix["key"] == f"order:{oid}:fix"
    assert fix["stage"]["key"] == "warehouse"


def test_the_arrival_is_late_by_the_orders_own_lateness(owner):
    oid = _new(owner)["id"]
    _ok(owner.post(
        f"/api/prod/orders/{oid}/delivery-date",
        json={"new_date": _day(70), "set_by": "factory", "reason": "Fabric came late"},
    ))
    row = _arrival(_incoming(owner), oid)
    listed = owner.get("/api/prod/orders").json()["orders"][0]
    assert row["due"] == _day(70)
    assert row["late_days"] == listed["lateness_days"] == 10


# ── Order and money-free-ness ─────────────────────────────────────────────────


def test_arrivals_are_nearest_first_then_by_code_with_fix_after_finished(owner):
    far = _new(owner, colour="Olive")["id"]
    soon = _ready(owner, colour="Grey")
    same_day = _new(owner, colour="Sand")["id"]
    _set_due(far, TODAY + timedelta(days=40))
    _set_due(soon, TODAY + timedelta(days=5))
    _set_due(same_day, TODAY + timedelta(days=5))
    payload = _incoming(owner)
    assert [(r["order"]["id"], r["kind"]) for r in payload["arrivals"]] == [
        (soon, "finished"), (soon, "fix"), (same_day, "finished"), (far, "finished"),
    ]
    codes = [r["order"]["code"] for r in payload["arrivals"] if r["kind"] == "finished"]
    assert codes[:2] == sorted(codes[:2])  # same day: by order code


def test_cancelled_orders_are_never_listed_arrivals_or_deliveries(owner):
    order = _all_the_way(owner)
    kept = _new(owner, colour="Sand")["id"]
    assert {r["order"]["id"] for r in _incoming(owner)["arrivals"]} == {order["id"], kept}
    assert len(_incoming(owner)["deliveries"]) == 2
    _ok(owner.post(f"/api/prod/orders/{order['id']}/cancel", json={"reason": "Style dropped"}))
    payload = _incoming(owner)
    assert [r["order"]["id"] for r in payload["arrivals"]] == [kept]
    assert payload["deliveries"] == []
    assert payload["totals"]["to_come_total"] == 1000 and payload["totals"]["waiting_for_count"] == 0


def test_an_order_received_in_full_has_no_arrival_but_keeps_its_deliveries(owner):
    order = _all_the_way(owner)
    _ok(_deliver(owner, order["id"], "fix", FIX, counted_on=_day(0), counted=FIX))
    current = owner.get(f"/api/prod/orders/{order['id']}").json()["order"]
    assert current["status"] == "open" and current["current_stage"] == "settle"
    payload = _incoming(owner)
    assert payload["arrivals"] == []
    assert [d["number"] for d in payload["deliveries"]] == [3, 2, 1]


# ── Deliveries ────────────────────────────────────────────────────────────────


def test_a_delivery_is_in_one_of_four_states(owner, staff):
    oid = _ready(owner)
    # 1: counted, and every size matches.
    _ok(_deliver(staff, oid, "finished", FIRST, shipped_on=_day(-5), counted_on=_day(-4), counted=FIRST))
    # 2: Khazenly counted one piece fewer in size M, and nobody has said why.
    _ok(_deliver(staff, oid, "finished", SECOND, shipped_on=_day(-3), counted_on=_day(-2), counted={**SECOND, "M": 139}))
    # 3: the fix pieces left the factory and nobody has counted them.
    fix = _ok(_deliver(staff, oid, "fix", FIX, shipped_on=_day(-1)))
    payload = _incoming(staff)

    assert [d["number"] for d in payload["deliveries"]] == [3, 2, 1]  # newest first
    match, mismatch, waiting = (_delivery_of(payload, oid, n) for n in (1, 2, 3))
    ref = {"id": oid, "code": fix["code"], "style_name": "Oversized hoodie", "colour": "Black"}

    assert match == {
        "id": match["id"], "order": ref, "number": 1, "kind": "finished",
        "shipped_on": _day(-5), "counted_on": _day(-4),
        "shipped": {s: FIRST[s] for s in SIZES if s in FIRST}, "shipped_total": 480,
        "counted": {s: FIRST[s] for s in SIZES if s in FIRST}, "counted_total": 480,
        "state": "match", "difference": None, "missing": 0, "extra": 0, "sizes_differ": [], "reason": None,
    }

    assert mismatch["state"] == "mismatch"
    assert (mismatch["shipped_total"], mismatch["counted_total"]) == (446, 445)
    assert mismatch["difference"] == -1 and (mismatch["missing"], mismatch["extra"]) == (1, 0)
    assert mismatch["sizes_differ"] == [{"size": "M", "shipped": 140, "counted": 139, "difference": -1}]
    assert mismatch["reason"] is None

    assert waiting["kind"] == "fix" and waiting["state"] == "waiting_for_count"
    assert (waiting["shipped_total"], waiting["counted_total"], waiting["counted_on"]) == (30, None, None)
    assert waiting["counted"] == {} and waiting["difference"] is None and waiting["sizes_differ"] == []

    totals = payload["totals"]
    assert (totals["waiting_for_count"], totals["mismatch_pieces"]) == (30, 1)

    # Once somebody says why, it is explained: the reason travels with it, and it is no longer owed.
    _ok(staff.patch(f"/api/prod/deliveries/{mismatch['id']}", json={"mismatch_reason": "One piece not found at Khazenly"}))
    payload = _incoming(staff)
    explained = _delivery_of(payload, oid, 2)
    assert explained["state"] == "explained" and explained["reason"] == "One piece not found at Khazenly"
    assert explained["difference"] == -1 and explained["sizes_differ"] == mismatch["sizes_differ"]
    assert payload["totals"]["mismatch_pieces"] == 0 and payload["totals"]["waiting_for_count"] == 30


def test_pieces_over_and_under_in_different_sizes_are_one_mismatch_of_both(owner):
    oid = _ready(owner)
    _ok(_deliver(owner, oid, "finished", FIRST, counted_on=_day(-1), counted={**FIRST, "S": 69, "M": 142}))
    row = _delivery_of(_incoming(owner), oid, 1)
    assert row["state"] == "mismatch"
    assert (row["missing"], row["extra"], row["difference"]) == (1, 2, 1)
    assert [(d["size"], d["difference"]) for d in row["sizes_differ"]] == [("S", -1), ("M", 2)]
    # The figure counts every piece that is off, the way the screen says "3 pieces".
    assert _incoming(owner)["totals"]["mismatch_pieces"] == 3
    # The totals can match while the sizes do not.
    _ok(owner.patch(f"/api/prod/deliveries/{row['id']}", json={"counted": {**FIRST, "S": 69, "M": 141}, "counted_on": _day(-1)}))
    row = _delivery_of(_incoming(owner), oid, 1)
    assert (row["state"], row["difference"], row["missing"], row["extra"]) == ("mismatch", 0, 1, 1)
    assert row["counted_total"] == row["shipped_total"] == 480


def test_a_size_added_after_the_count_waits_for_its_own_count(owner):
    oid = _ready(owner)
    first = _ok(_deliver(owner, oid, "finished", FIRST, counted_on=_day(-1), counted=FIRST))["deliveries"][0]
    assert _delivery_of(_incoming(owner), oid, 1)["state"] == "match"
    _ok(owner.patch(f"/api/prod/deliveries/{first['id']}", json={"shipped": {**FIRST, "XS": 5}}))
    payload = _incoming(owner)
    row = _delivery_of(payload, oid, 1)
    assert row["state"] == "waiting_for_count"
    assert row["counted_on"] == _day(-1) and "XS" not in row["counted"]
    assert payload["totals"]["waiting_for_count"] == 5  # only the size nobody has counted


def test_deliveries_of_every_open_order_are_listed_newest_first(owner):
    first, second = _ready(owner), _ready(owner, colour="Olive")
    _ok(_deliver(owner, first, "finished", FIRST, shipped_on=_day(-6)))
    _ok(_deliver(owner, second, "finished", FIRST, shipped_on=_day(-3)))
    _ok(_deliver(owner, first, "finished", SECOND, shipped_on=_day(-1)))
    payload = _incoming(owner)
    assert [(d["order"]["id"], d["number"], d["shipped_on"]) for d in payload["deliveries"]] == [
        (first, 2, _day(-1)), (second, 1, _day(-3)), (first, 1, _day(-6)),
    ]
    assert payload["totals"]["waiting_for_count"] == 480 + 480 + 446


# ── Closed orders ─────────────────────────────────────────────────────────────


def test_a_closed_order_drops_out_and_its_counted_deliveries_stay_for_thirty_days(owner, monkeypatch):
    order = _all_the_way(owner)
    oid = order["id"]
    _ok(_deliver(owner, oid, "fix", FIX, counted_on=_day(0), counted=FIX))
    _ok(owner.post(f"/api/prod/orders/{oid}/settle"))
    assert owner.get(f"/api/prod/orders/{oid}").json()["order"]["status"] == "closed"

    payload = _incoming(owner)
    assert payload["arrivals"] == []
    assert [d["number"] for d in payload["deliveries"]] == [3, 2, 1]
    assert [d["state"] for d in payload["deliveries"]] == ["match", "explained", "match"]
    assert payload["totals"]["waiting_for_count"] == 0 and payload["totals"]["to_come_total"] == 0

    # Counted yesterday and today: 30 days on, today's count is exactly 30 days old and stays, yesterday's has gone.
    monkeypatch.setattr(incoming, "today", lambda: TODAY + timedelta(days=30))
    assert [d["number"] for d in _incoming(owner)["deliveries"]] == [3]
    monkeypatch.setattr(incoming, "today", lambda: TODAY + timedelta(days=31))
    assert _incoming(owner)["deliveries"] == []


# ── The four figures ──────────────────────────────────────────────────────────


def _planned(owner, pieces: int, due: date, colour: str) -> int:
    oid = _new(owner, colour=colour, planned={"M": pieces})["id"]
    _set_due(oid, due)
    return oid


def test_the_four_figures_around_a_month_boundary_with_overdue_in_this_month(owner, monkeypatch):
    monkeypatch.setattr(incoming, "today", lambda: date(2026, 11, 28))
    overdue = _planned(owner, 100, date(2026, 10, 20), "Olive")
    month_end = _planned(owner, 200, date(2026, 11, 30), "Grey")
    month_start = _planned(owner, 400, date(2026, 12, 1), "Sand")
    later = _planned(owner, 800, date(2027, 1, 5), "Navy")

    payload = _incoming(owner)
    assert payload["today"] == "2026-11-28"
    assert [r["order"]["id"] for r in payload["arrivals"]] == [overdue, month_end, month_start, later]
    assert payload["totals"]["this_month"] == {"month": "2026-11", "label": "November", "pieces": 300}  # 100 overdue + 200
    assert payload["totals"]["next_month"] == {"month": "2026-12", "label": "December", "pieces": 400}
    assert payload["totals"]["to_come_total"] == 1500  # January is in the total, in neither month

    # In December, "next month" is January of the next year, and November's pieces are overdue.
    monkeypatch.setattr(incoming, "today", lambda: date(2026, 12, 31))
    totals = _incoming(owner)["totals"]
    assert totals["this_month"] == {"month": "2026-12", "label": "December", "pieces": 700}
    assert totals["next_month"] == {"month": "2027-01", "label": "January", "pieces": 800}
    # Only the first of the month tells November from December: the day before is still November.
    monkeypatch.setattr(incoming, "today", lambda: date(2026, 11, 30))
    assert _incoming(owner)["totals"]["this_month"]["pieces"] == 300


def test_a_fix_arrival_counts_in_its_month_with_the_finished_pieces(owner, monkeypatch):
    monkeypatch.setattr(incoming, "today", lambda: TODAY)
    oid = _ready(owner)
    _set_due(oid, TODAY.replace(day=1))  # the first of this month
    _ok(_deliver(owner, oid, "finished", FIRST))
    totals = _incoming(owner)["totals"]
    assert totals["to_come_total"] == 446 + 30
    assert totals["this_month"]["pieces"] == 446 + 30 and totals["next_month"]["pieces"] == 0


def test_the_figures_for_pieces_waiting_for_a_count_and_for_a_mismatch(owner):
    oid = _ready(owner)
    _ok(_deliver(owner, oid, "finished", FIRST, counted_on=_day(-1), counted={**FIRST, "L": 137, "XL": 93}))
    _ok(_deliver(owner, oid, "finished", SECOND))  # 446, not counted
    totals = _incoming(owner)["totals"]
    assert totals["waiting_for_count"] == 446
    assert totals["mismatch_pieces"] == 2  # one short in L, one over in XL
    assert totals["to_come_total"] == 30


# ── Cost of the read ──────────────────────────────────────────────────────────


def test_the_number_of_queries_does_not_grow_with_the_orders(owner):
    statements: list[str] = []

    def count(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    def reads() -> int:
        statements.clear()
        event.listen(engine, "before_cursor_execute", count)
        try:
            assert owner.get(URL).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return len(statements)

    first = _ready(owner)
    _ok(_deliver(owner, first, "finished", FIRST))
    reads()  # warm: the session and permission lookups are the same on every request
    one = reads()
    _ready(owner, colour="Olive")
    oid = _ready(owner, colour="Sand")
    _ok(_deliver(owner, oid, "finished", FIRST))
    _all_the_way(owner)
    _new(owner, colour="Navy")
    many = reads()
    assert many == one, (one, many)


# ── No money, for anybody ─────────────────────────────────────────────────────


@pytest.mark.parametrize("who", ["owner", "production_staff", "production_viewer", "production_manager"])
def test_no_money_for_anybody_on_open_or_closed_orders(owner, who):
    settled = _all_the_way(owner)
    _ok(owner.patch(f"/api/prod/orders/{settled['id']}", json={"actual_fabric_piastres": 17200}))
    _ok(_deliver(owner, settled["id"], "fix", FIX, counted_on=_day(0), counted=FIX))
    _ok(owner.post(f"/api/prod/orders/{settled['id']}/settle"))
    _all_the_way(owner)
    _ready(owner, colour="Sand")
    _new(owner, colour="Navy")
    person = owner if who == "owner" else _person(f"{who}@example.com", who)
    response = person.get(URL)
    assert response.status_code == 200
    payload = response.json()
    assert payload["arrivals"] and payload["deliveries"]
    _no_money(payload)
    assert "piastres" not in response.text
    with SessionLocal() as db:
        assert db.scalars(select(ProdOrder).where(ProdOrder.status == "closed")).first() is not None
