"""Production's Overview under /api/prod/overview (ADR 0084, decision 11; batch 5).

One read of what the four batches before it already work out: what waits for
the owner, what is wrong now, every open order, what arrives next, and (the
owner's alone) what is owed. Worked out on each read; nothing is stored.
Every name and figure here is invented. The order helpers are batch 1's, the
supplier helpers batch 4's.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.modules.production.orders.models import ProdOrder
from app.modules.production.orders.services import orders as orders_service
from tests.test_prod_orders import (  # noqa: F401  (fixtures)
    FIRST,
    SECOND,
    TARGET,
    TODAY,
    _all_the_way,
    _cut,
    _day,
    _deliver,
    _inspected,
    _new,
    _ok,
    _person,
    _to_cutting,
    owner,
    staff,
    viewer,
)
from tests.test_prod_suppliers import _buy, _make, _pay

URL = "/api/prod/overview"


def _overview(client: TestClient) -> dict:
    response = client.get(URL)
    assert response.status_code == 200, response.text
    return response.json()


def _kinds(payload: dict, kind: str) -> list[dict]:
    return [problem for problem in payload["problems"] if problem["kind"] == kind]


def _short(offset: int) -> str:
    day = TODAY + timedelta(days=offset)
    return f"{day.day} {day.strftime('%b')}"


def _set_due(order_id: int, offset: int) -> None:
    with SessionLocal() as db:
        db.get(ProdOrder, order_id).delivery_date = TODAY + timedelta(days=offset)
        db.commit()


def _ready(client: TestClient, **over) -> int:
    """An order through the final inspection: 926 finished pieces to come, 30 to fix."""
    oid = _new(client, **over)["id"]
    _to_cutting(client, oid)
    _cut(client, oid)
    _inspected(client, oid)
    return oid


def _money_keys(payload, where: str = "") -> list[str]:
    """Every key that ends ``_piastres``, and every string that says EGP, at any depth."""
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.endswith("_piastres"):
                found.append(f"{where}.{key}")
            found += _money_keys(value, f"{where}.{key}")
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            found += _money_keys(item, f"{where}[{index}]")
    elif isinstance(payload, str) and "EGP" in payload:
        found.append(f"{where} = {payload!r}")
    return found


# ── Who may come in ───────────────────────────────────────────────────────────


def test_signed_out_and_other_departments_are_refused(owner):
    with TestClient(app) as stranger:
        assert stranger.get(URL).status_code == 401
    inbox = _person("cs@example.com", "customer_service")
    assert inbox.get(URL).status_code == 403


def test_the_owner_the_qc_manager_and_a_viewer_all_read_it(owner, staff, viewer):
    _new(owner)
    for client in (owner, staff, viewer):
        assert _overview(client)["orders"][0]["style_name"] == "Oversized hoodie"


def test_nothing_is_written_by_reading_it(owner):
    for verb in (owner.post, owner.put, owner.patch, owner.delete):
        assert verb(URL).status_code == 405


# ── The shape ─────────────────────────────────────────────────────────────────


def test_with_nothing_in_production_the_page_is_empty_but_whole(owner):
    payload = _overview(owner)
    this_first = TODAY.replace(day=1)
    assert payload == {
        "today": TODAY.isoformat(),
        "summary": {"open_orders": 0, "planned_pieces": 0},
        "figures": {
            "decisions": 0,
            "late_orders": 0,
            "open_orders": 0,
            "arriving_this_month": {
                "month": this_first.strftime("%Y-%m"), "label": this_first.strftime("%B"), "pieces": 0,
            },
            "owed_piastres": 0,
        },
        "decisions": [],
        "problems": [],
        "orders": [],
        "arriving": [],
        "owed": [],
    }


def test_the_orders_are_the_open_list_unchanged(owner, staff):
    _all_the_way(owner)
    _new(owner, colour="Off-white", repeat_run=True)
    cancelled = _new(owner, colour="Red")
    _ok(owner.post(f"/api/prod/orders/{cancelled['id']}/cancel", json={"reason": "Style dropped"}))
    for client in (owner, staff):
        payload = _overview(client)
        assert payload["orders"] == client.get("/api/prod/orders").json()["orders"]
        with SessionLocal() as db:
            assert payload["orders"] == orders_service.rows(db, "open")
        assert [row["colour"] for row in payload["orders"]] == ["Black", "Off-white"]


def test_the_summary_and_the_late_and_open_counts(owner):
    first = _new(owner)["id"]
    _new(owner, colour="Off-white", planned={"M": 40, "L": 60})
    late = _new(owner, colour="Red")["id"]
    _set_due(late, 0)
    _ok(owner.patch(f"/api/prod/orders/{late}", json={"target_date": _day(-2)}))
    cancelled = _new(owner, colour="Green")
    _ok(owner.post(f"/api/prod/orders/{cancelled['id']}/cancel", json={"reason": "Style dropped"}))
    payload = _overview(owner)
    assert payload["summary"] == {"open_orders": 3, "planned_pieces": 1000 + 100 + 1000}
    assert payload["figures"]["open_orders"] == 3 and payload["figures"]["late_orders"] == 1
    assert first in [row["id"] for row in payload["orders"]]
    [problem] = _kinds(payload, "late_order")
    assert problem["link"] == {"to": "order", "id": late}


# ── Decisions: what waits for the owner ───────────────────────────────────────


def test_the_decisions_are_the_owners_tasks_and_nobody_elses(owner, staff):
    order = _new(owner)
    own = _ok_task(owner, title="Decide the autumn colours", for_owner=True, due_on=_day(3))
    _ok_task(owner, title="Visit the print house")  # the QC manager's
    payload = _overview(owner)

    # Sorted as the Tasks list sorts them: the nearer date first.
    mine, sample = payload["decisions"]
    assert mine["title"] == "Decide the autumn colours" and mine["kind"] == "manual" and mine["id"] == own["id"]
    assert (mine["key"], mine["due"], mine["order"], mine["open"], mine["overdue_days"]) == (
        f"task:{own['id']}", _day(3), None, None, 0,
    )
    assert sample["kind"] == "generated" and sample["title"] == "Approve the sample"
    assert sample["key"] == f"order:{order['id']}:stage:sample" and sample["open"] == "sample" and sample["id"] is None
    assert sample["order"]["id"] == order["id"]
    assert set(sample) == {"kind", "key", "id", "title", "order", "due", "since", "open", "overdue_days"}
    assert payload["figures"]["decisions"] == 2
    # The QC manager reads the same list.
    assert [d["key"] for d in _overview(staff)["decisions"]] == [mine["key"], sample["key"]]

    # They go when the work is done.
    _ok(owner.post(f"/api/prod/orders/{order['id']}/sample", json={"decision": "approved"}))
    assert owner.patch(f"/api/prod/tasks/{own['id']}", json={"done": True}).status_code == 200
    payload = _overview(owner)
    assert payload["decisions"] == [] and payload["figures"]["decisions"] == 0


def test_an_order_to_settle_is_a_decision(owner):
    order = _all_the_way(owner)
    assert _overview(owner)["decisions"] == []  # the fix pieces are the factory's to send
    _ok(_deliver(owner, order["id"], "fix", {"S": 5, "M": 8, "L": 9, "XL": 5, "XXL": 3}, counted_on=_day(0),
                 counted={"S": 5, "M": 8, "L": 9, "XL": 5, "XXL": 3}))
    [decision] = _overview(owner)["decisions"]
    assert decision["title"] == "Settle with the factory" and decision["open"] == "settle"


def _ok_task(client: TestClient, **over) -> dict:
    response = client.post("/api/prod/tasks", json=over)
    assert response.status_code == 201, response.text
    return response.json()["task"]


# ── Problems ──────────────────────────────────────────────────────────────────


def test_a_late_order_is_a_problem_until_it_is_no_longer_late(owner, staff):
    oid = _new(owner)["id"]
    assert _kinds(_overview(owner), "late_order") == []
    _set_due(oid, 0)
    _ok(owner.patch(f"/api/prod/orders/{oid}", json={"target_date": _day(-3)}))
    [problem] = _kinds(_overview(owner), "late_order")
    assert problem == {
        "kind": "late_order",
        "title": "Oversized hoodie · Black is 3 days late",
        "detail": "At Sample",  # no date move yet: the stage it is at
        "link": {"to": "order", "id": oid},
    }

    # The factory moves its date: the last move is the detail.
    _ok(staff.post(f"/api/prod/orders/{oid}/delivery-date",
                   json={"new_date": _day(2), "set_by": "factory", "reason": "Waiting in the print queue"}))
    [problem] = _kinds(_overview(owner), "late_order")
    assert problem["title"] == "Oversized hoodie · Black is 5 days late"
    assert problem["detail"] == f"Factory moved {_short(0)} to {_short(2)} · Waiting in the print queue"

    _ok(staff.post(f"/api/prod/orders/{oid}/delivery-date",
                   json={"new_date": _day(1), "set_by": "owner", "reason": "Pushed them"}))
    assert _kinds(_overview(owner), "late_order")[0]["detail"] == f"Owner moved {_short(2)} to {_short(1)} · Pushed them"

    # Late no more: gone.
    _ok(owner.patch(f"/api/prod/orders/{oid}", json={"target_date": _day(30)}))
    assert _kinds(_overview(owner), "late_order") == []
    assert _overview(owner)["figures"]["late_orders"] == 0


def test_the_most_late_order_comes_first(owner):
    a, b = _new(owner, colour="Red")["id"], _new(owner, colour="Blue")["id"]
    for oid, days in ((a, 2), (b, 9)):
        _set_due(oid, 0)
        _ok(owner.patch(f"/api/prod/orders/{oid}", json={"target_date": _day(-days)}))
    assert [p["link"]["id"] for p in _kinds(_overview(owner), "late_order")] == [b, a]
    assert _kinds(_overview(owner), "late_order")[1]["title"] == "Oversized hoodie · Red is 2 days late"


def test_a_material_that_is_late_is_a_problem_until_it_arrives(owner, staff):
    oid = _new(owner)["id"]
    supplier = _make(owner)
    bought = _buy(owner, supplier["id"], order_id=oid, expected_on=_day(-3), bought_on=_day(-10))
    unattached = _buy(owner, supplier["id"], item="Zips", quantity=10, unit="piece", expected_on=_day(-1), bought_on=_day(-5))
    _buy(owner, supplier["id"], item="Thread", expected_on=_day(4), bought_on=_day(-2))  # not late yet

    for client in (owner, staff):
        late = _kinds(_overview(client), "late_material")
        assert late == [
            {
                "kind": "late_material",
                "title": "Heavy fleece, black for Oversized hoodie are 3 days late",
                "detail": "Fabric supplier A · order at Sample",
                "link": {"to": "tasks"},
            },
            {
                "kind": "late_material",
                "title": "Zips from Fabric supplier A are 1 day late",
                "detail": "Fabric supplier A",
                "link": {"to": "tasks"},
            },
        ]
    assert "EGP" not in str(_kinds(_overview(staff), "late_material"))

    for purchase in (bought, unattached):
        assert owner.patch(f"/api/prod/purchases/{purchase['purchase_id']}",
                           json={"received_on": TODAY.isoformat()}).status_code == 200
    assert _kinds(_overview(owner), "late_material") == []


def test_a_count_that_does_not_match_is_a_problem_until_a_reason_is_given(owner, staff):
    oid = _ready(owner)
    assert _kinds(_overview(owner), "count_mismatch") == []
    _ok(_deliver(staff, oid, "finished", FIRST, shipped_on=_day(-5), counted_on=_day(-4), counted=FIRST))
    short = _ok(_deliver(staff, oid, "finished", SECOND, shipped_on=_day(-3), counted_on=_day(-2),
                         counted={**SECOND, "M": 139, "L": 137}))
    delivery_id = short["deliveries"][1]["id"]
    [problem] = _kinds(_overview(owner), "count_mismatch")
    assert problem == {
        "kind": "count_mismatch",
        "title": "2 pieces missing between factory and Khazenly",
        "detail": "Oversized hoodie · Black · no reason given yet",
        "link": {"to": "order", "id": oid, "open": f"delivery-reason:{delivery_id}"},
    }

    _ok(staff.patch(f"/api/prod/deliveries/{delivery_id}", json={"mismatch_reason": "Two pieces not found"}))
    assert _kinds(_overview(owner), "count_mismatch") == []


def test_more_counted_than_shipped_and_a_single_piece_are_said_in_plain_words(owner, staff):
    oid = _ready(owner)
    _ok(_deliver(staff, oid, "finished", FIRST, shipped_on=_day(-5), counted_on=_day(-4), counted=FIRST))
    _ok(_deliver(staff, oid, "finished", SECOND, shipped_on=_day(-3), counted_on=_day(-2),
                 counted={**SECOND, "M": 141, "L": 137}))
    [problem] = _kinds(_overview(owner), "count_mismatch")
    assert problem["title"] == "1 piece missing between factory and Khazenly"  # a short size wins over a long one

    other = _ready(owner, colour="Off-white")
    _ok(_deliver(staff, other, "finished", FIRST, shipped_on=_day(-5), counted_on=_day(-4), counted={**FIRST, "M": 142}))
    titles = [p["title"] for p in _kinds(_overview(owner), "count_mismatch")]
    assert "2 more counted than shipped" in titles


def test_a_cost_over_the_plan_is_the_owners_problem_and_goes_when_it_is_back_on_plan(owner, staff):
    oid = _new(owner)["id"]
    assert _kinds(_overview(owner), "cost_over") == []
    # Typed actuals that are exactly the target, or under, are no problem.
    _ok(owner.patch(f"/api/prod/orders/{oid}", json={"actual_fabric_piastres": 16500}))
    assert _kinds(_overview(owner), "cost_over") == []

    _ok(owner.patch(f"/api/prod/orders/{oid}", json={"actual_fabric_piastres": 17200}))
    [problem] = _kinds(_overview(owner), "cost_over")
    assert problem == {
        "kind": "cost_over",
        "title": "Oversized hoodie · Black costs EGP 7 more per piece than planned",
        "detail": "EGP 307 actual against EGP 300 target · Fabric over target",
        "link": {"to": "order", "id": oid},
    }
    _ok(owner.patch(f"/api/prod/orders/{oid}", json={"actual_accessories_piastres": 1400, "actual_fabric_piastres": 17250}))
    [problem] = _kinds(_overview(owner), "cost_over")
    assert problem["title"].endswith("costs EGP 9.50 more per piece than planned")
    assert problem["detail"] == "EGP 309.50 actual against EGP 300 target · Fabric and Accessories over target"
    # The QC manager never gets it: the item is left out, not blanked.
    assert _kinds(_overview(staff), "cost_over") == []
    assert all(p["kind"] != "cost_over" for p in _overview(staff)["problems"])

    # A part under its target does not hide another that is over, but the total is what counts.
    _ok(owner.patch(f"/api/prod/orders/{oid}", json={"actual_fabric_piastres": 16000, "actual_accessories_piastres": 1300}))
    assert _kinds(_overview(owner), "cost_over") == []


def test_problems_come_in_the_order_the_plan_gives(owner, staff):
    late = _new(owner, colour="Late one")["id"]
    _set_due(late, 0)
    _ok(owner.patch(f"/api/prod/orders/{late}", json={"target_date": _day(-3), "actual_fabric_piastres": 17200}))
    supplier = _make(owner)
    _buy(owner, supplier["id"], expected_on=_day(-3), bought_on=_day(-10))
    oid = _ready(owner, colour="Counted wrong")
    _ok(_deliver(staff, oid, "finished", FIRST, shipped_on=_day(-5), counted_on=_day(-4), counted={**FIRST, "M": 139}))
    assert [p["kind"] for p in _overview(owner)["problems"]] == [
        "late_order", "late_material", "count_mismatch", "cost_over",
    ]
    assert [p["kind"] for p in _overview(staff)["problems"]] == ["late_order", "late_material", "count_mismatch"]


# ── Arriving ──────────────────────────────────────────────────────────────────


def test_arriving_is_the_five_nearest_deliveries_by_due_date(owner):
    offsets = [70, 30, 50, 40, 60, 35]
    ids = {}
    for index, offset in enumerate(offsets):
        ids[offset] = _new(owner, colour=f"Colour {index}", target_date=_day(offset))["id"]
    payload = _overview(owner)
    assert [row["due"] for row in payload["arriving"]] == [_day(30), _day(35), _day(40), _day(50), _day(60)]
    assert ids[70] not in [row["order"]["id"] for row in payload["arriving"]]
    first = payload["arriving"][0]
    assert first["kind"] == "finished" and first["order"]["id"] == ids[30]
    assert first["to_come"]["total"] == 1000 and first["late_days"] == 0
    assert set(first) == {
        "key", "kind", "order", "factory", "basis", "expected", "shipped", "to_come", "due", "late_days",
        "stage", "status_words", "can_record",
    }


def test_the_arriving_figure_is_this_months_total_as_incoming_says(owner):
    _new(owner, target_date=_day(2))
    payload = _overview(owner)
    month = payload["figures"]["arriving_this_month"]
    incoming = owner.get("/api/prod/incoming").json()["totals"]["this_month"]
    assert month == {"month": incoming["month"], "label": incoming["label"], "pieces": incoming["pieces"]}


# ── What is owed (the owner's alone) ──────────────────────────────────────────


def test_what_is_owed_sums_the_positive_balances_only_and_skips_the_overpaid(owner):
    fleece = _make(owner, "Fleece mill")
    trims = _make(owner, "Trims shop")
    paid_up = _make(owner, "Paid up shop")
    overpaid = _make(owner, "Overpaid mill")
    ledger = _make(owner, "Old balance mill")

    _buy(owner, fleece["id"])  # 1,075 kg at EGP 160: EGP 172,000, nothing paid
    _buy(owner, trims["id"], item="Zips", quantity=10, unit="piece", unit_price_piastres=5000)  # EGP 500
    _buy(owner, trims["id"], item="Thread", quantity=4, unit="piece", unit_price_piastres=2500)  # EGP 100
    _buy(owner, paid_up["id"], item="Labels", quantity=10, unit="piece", unit_price_piastres=1000,
         deposit_piastres=10_000, deposit_method="cash")  # paid in full
    _pay(owner, overpaid["id"], 2_000_000)  # HBA has paid EGP 20,000 it does not owe
    assert owner.post(f"/api/prod/suppliers/{ledger['id']}/opening", json={"amount_piastres": 500_000}).status_code == 201
    _pay(owner, ledger["id"], 100_000)

    payload = _overview(owner)
    assert payload["owed"] == [
        {"supplier": {"id": fleece["id"], "name": "Fleece mill"}, "owed_piastres": 17_200_000,
         "detail": "Rest of the Heavy fleece, black purchase"},
        {"supplier": {"id": ledger["id"], "name": "Old balance mill"}, "owed_piastres": 400_000,
         "detail": f"Last paid {_short(0)}"},
        {"supplier": {"id": trims["id"], "name": "Trims shop"}, "owed_piastres": 60_000,
         "detail": "Rest of the Zips and Thread purchases"},
    ]
    # The overpaid supplier does not reduce what is owed to the others.
    assert payload["figures"]["owed_piastres"] == 17_200_000 + 400_000 + 60_000
    suppliers = owner.get("/api/prod/suppliers").json()
    assert payload["figures"]["owed_piastres"] == suppliers["owed_total_piastres"]
    rows = {s["id"]: s for s in suppliers["suppliers"]}
    assert rows[overpaid["id"]]["owed_piastres"] == -2_000_000 and rows[paid_up["id"]]["owed_piastres"] == 0


def test_a_factory_owed_for_work_so_far_is_listed_with_no_line_of_detail(owner):
    oid = _new(owner)["id"]
    _to_cutting(owner, oid)
    _cut(owner, oid)
    [row] = _overview(owner)["owed"]
    assert row["supplier"] == {"id": "fac", "name": "Main factory"}
    assert row["owed_piastres"] == 972 * 11500  # 972 cut at the making rate, nothing yet to take off
    assert row["detail"] is None


def test_three_or_more_open_purchases_are_counted(owner):
    supplier = _make(owner)
    for item in ("Fleece", "Zips", "Thread"):
        _buy(owner, supplier["id"], item=item, quantity=1, unit="piece", unit_price_piastres=1000)
    [row] = _overview(owner)["owed"]
    assert row["detail"] == "Rest of the Fleece purchase and 2 more"


def test_a_purchase_a_lump_sum_may_have_paid_is_not_named(owner):
    """A weekly payment is tied to no purchase, so a purchase bought before it
    may be paid off: only one bought after the last lump sum is named."""
    supplier = _make(owner)
    _buy(owner, supplier["id"], item="Fleece", quantity=10, unit="piece", unit_price_piastres=10_000,
         bought_on=_day(-10), deposit_piastres=20_000, deposit_method="cash")  # EGP 1,000, EGP 200 down
    _pay(owner, supplier["id"], 50_000, paid_on=_day(-5))
    [row] = _overview(owner)["owed"]
    assert row["owed_piastres"] == 30_000
    assert row["detail"] == f"Last paid {_short(-5)}"

    _buy(owner, supplier["id"], item="Zips", quantity=1, unit="piece", unit_price_piastres=5_000, bought_on=_day(-2))
    [row] = _overview(owner)["owed"]
    assert row["detail"] == "Rest of the Zips purchase"


# ── Money: the owner's alone ──────────────────────────────────────────────────


def _everything_wrong(owner: TestClient, staff: TestClient) -> None:
    """Every kind of problem, and money owed: so a leak has something to leak."""
    late = _new(owner, colour="Late one")["id"]
    _set_due(late, 0)
    _ok(owner.patch(f"/api/prod/orders/{late}", json={"target_date": _day(-3), "actual_fabric_piastres": 17200}))
    supplier = _make(owner)
    _buy(owner, supplier["id"], order_id=late, expected_on=_day(-3), bought_on=_day(-10))
    oid = _ready(owner, colour="Counted wrong")
    _ok(_deliver(staff, oid, "finished", FIRST, shipped_on=_day(-5), counted_on=_day(-4), counted={**FIRST, "M": 139}))
    _ok_task(owner, title="Decide the autumn colours", for_owner=True)


def test_the_owner_gets_the_money(owner, staff):
    _everything_wrong(owner, staff)
    payload = _overview(owner)
    assert "owed" in payload and payload["owed"] and payload["figures"]["owed_piastres"] > 0
    assert {p["kind"] for p in payload["problems"]} == {"late_order", "late_material", "count_mismatch", "cost_over"}
    assert _money_keys(payload)  # and the owner's money does show


@pytest.mark.parametrize("role", ["production_viewer", "production_staff"])
def test_nobody_short_of_the_owner_gets_money_anywhere(owner, staff, role):
    """Walk the whole response, at any depth: no key ending `_piastres`, no string
    that says EGP, no `owed`, no cost problem. Absent, not null."""
    _everything_wrong(owner, staff)
    person = _person(f"{role}@example.com", role)
    payload = _overview(person)
    assert _money_keys(payload) == []
    assert "owed" not in payload and "owed_piastres" not in payload["figures"]
    assert payload["problems"] and all(p["kind"] != "cost_over" for p in payload["problems"])
    assert "EGP" not in person.get(URL).text and "piastres" not in person.get(URL).text


def test_the_qc_manager_sees_three_figures(owner, staff):
    _everything_wrong(owner, staff)
    figures = _overview(staff)["figures"]
    assert set(figures) == {"decisions", "late_orders", "open_orders", "arriving_this_month"}
    assert set(_overview(owner)["figures"]) == set(figures) | {"owed_piastres"}


def test_the_production_manager_gets_the_money(owner, staff):
    """ADR 0086: the production manager sees what the owner sees."""
    _everything_wrong(owner, staff)
    payload = _overview(_person("pm@example.com", "production_manager"))
    assert "owed" in payload and "owed_piastres" in payload["figures"]
    assert any(problem["kind"] == "cost_over" for problem in payload["problems"])
