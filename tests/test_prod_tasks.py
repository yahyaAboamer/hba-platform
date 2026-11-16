"""Production's Tasks under /api/prod/tasks (ADR 0084, decision 7; batch 2).

Generated tasks are worked out on every read from the open orders and never
stored; hand-added ones live in ``prod_task``. Every name and figure here is
invented. The order helpers are batch 1's.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.businesstime import utcnow
from app.db import SessionLocal, engine
from app.main import app
from app.modules.production.orders.models import ProdTask
from app.shared.models.audit import AuditEvent
from tests.test_prod_orders import (  # noqa: F401  (fixtures)
    FIRST,
    FIX,
    SECOND,
    TARGET,
    TODAY,
    _all_the_way,
    _body,
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

GROUPS = ["overdue", "today", "week", "later"]


def _list(client: TestClient, done: bool = False) -> dict:
    response = client.get("/api/prod/tasks" + ("?done=1" if done else ""))
    assert response.status_code == 200, response.text
    return response.json()


def _keys(payload: dict) -> list[str]:
    return [task["key"] for task in payload["tasks"]]


def _for(payload: dict, order_id: int) -> list[dict]:
    return [task for task in payload["tasks"] if task["order"] and task["order"]["id"] == order_id]


def _add(client: TestClient, **over) -> dict:
    response = client.post("/api/prod/tasks", json={"title": "Visit the new print house", **over})
    assert response.status_code == 201, response.text
    return response.json()["task"]


def _events(task_id: int) -> list[AuditEvent]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(AuditEvent).where(AuditEvent.subject == f"production:task:{task_id}").order_by(AuditEvent.id)
            )
        )


# ── Who may come in ───────────────────────────────────────────────────────────


def test_signed_out_and_other_departments_are_refused(owner):
    with TestClient(app) as stranger:
        assert stranger.get("/api/prod/tasks").status_code == 401
        assert stranger.post("/api/prod/tasks", json={"title": "x"}).status_code == 401
    inbox = _person("cs@example.com", "customer_service")
    assert inbox.get("/api/prod/tasks").status_code == 403
    assert inbox.post("/api/prod/tasks", json={"title": "x"}).status_code == 403


def test_a_viewer_reads_the_list_and_writes_nothing(owner, viewer):
    made = _add(owner)
    _new(owner)
    assert viewer.get("/api/prod/tasks").status_code == 200
    assert viewer.get("/api/prod/tasks?done=1").status_code == 200
    assert viewer.post("/api/prod/tasks", json={"title": "x"}).status_code == 403
    assert viewer.patch(f"/api/prod/tasks/{made['id']}", json={"done": True}).status_code == 403
    assert viewer.delete(f"/api/prod/tasks/{made['id']}").status_code == 403
    still = _list(owner)
    assert any(task.get("id") == made["id"] and task["done"] is False for task in still["tasks"])


def test_the_qc_manager_and_the_owner_both_write_tasks(owner, staff):
    mine = _add(staff, title="Call the print house")
    theirs = _add(owner, title="Decide the autumn colours", for_owner=True)
    assert mine["who"] == "qc" and theirs["who"] == "owner"
    assert staff.patch(f"/api/prod/tasks/{theirs['id']}", json={"done": True}).status_code == 200
    assert owner.delete(f"/api/prod/tasks/{mine['id']}").status_code == 200


# ── The generated tasks ───────────────────────────────────────────────────────


def test_a_new_order_has_one_task_its_next_action(owner):
    order = _new(owner)
    payload = _list(owner)
    assert payload["today"] == TODAY.isoformat()
    [task] = payload["tasks"]
    sample = next(stage for stage in order["stages"] if stage["key"] == "sample")
    assert task == {
        "kind": "generated",
        "key": f"order:{order['id']}:stage:sample",
        "title": "Approve the sample",
        "who": "owner",
        "due": sample["expected_date"],
        "order": {"id": order["id"], "code": order["code"], "style_name": "Oversized hoodie", "colour": "Black"},
        "stage": "sample",
        "waiting_on": None,
        "since": TODAY.isoformat(),
        "open": "sample",
        "group": "later",
        "overdue_days": 0,
    }
    # The same words and date as the order list gives the next action.
    row = owner.get("/api/prod/orders").json()["orders"][0]["next_action"]
    assert (row["what"], row["who"], row["by"], row["since"]) == (task["title"], task["who"], task["due"], task["since"])
    assert payload["counts"] == {"all": 1, "overdue": 0, "qc": 0, "owner": 1, "factory": 0}


def test_generated_tasks_are_never_stored(owner):
    _all_the_way(owner)
    _list(owner)
    _list(owner, done=True)
    with SessionLocal() as db:
        assert db.scalars(select(ProdTask)).first() is None


def test_each_stage_names_the_form_that_does_its_work(owner, staff):
    order = _new(owner, repeat_run=True)
    oid = order["id"]

    def only() -> dict:
        found = _for(_list(owner), oid)
        assert len(found) == 1, found
        return found[0]

    assert (only()["open"], only()["who"], only()["title"]) == ("stage:materials", "qc", "Record the materials arriving")
    _ok(staff.post(f"/api/prod/orders/{oid}/stages/materials/complete", json={}))
    assert (only()["open"], only()["title"]) == ("stage:fabric_check", "Check the fabric")
    _ok(staff.post(f"/api/prod/orders/{oid}/stages/fabric_check/complete", json={"result": "passed"}))
    assert (only()["open"], only()["title"]) == ("stage:pattern_check", "Check the pattern")
    _ok(staff.post(f"/api/prod/orders/{oid}/stages/pattern_check/complete", json={}))
    assert (only()["open"], only()["title"]) == ("cut", "Record cut quantities")
    _cut(owner, oid)
    making = only()
    assert (making["open"], making["stage"]) == ("stage:making", "making")
    # The factory finishes making by the promised delivery date, not a stage date.
    assert making["due"] == TARGET.isoformat() and making["title"] == "Final inspection"
    _ok(staff.post(f"/api/prod/orders/{oid}/stages/making/complete", json={}))
    assert (only()["open"], only()["title"]) == ("inspection", "Finish the final inspection")


def test_the_factory_sending_a_changed_sample_has_nothing_to_fill_in(owner):
    oid = _new(owner)["id"]
    _ok(owner.post(f"/api/prod/orders/{oid}/sample", json={"decision": "changes", "note": "Longer sleeves"}))
    [task] = _for(_list(owner), oid)
    assert task["title"] == "Factory to send the changed sample"
    assert task["who"] == "factory" and task["waiting_on"] == "Main factory"
    assert task["open"] is None


def test_after_inspection_pieces_to_come_and_fix_pieces_are_two_tasks(owner):
    order = _new(owner)
    oid = order["id"]
    _to_cutting(owner, oid)
    _cut(owner, oid)
    _inspected(owner, oid)
    tasks = _for(_list(owner), oid)
    assert sorted(task["key"] for task in tasks) == sorted([f"order:{oid}:stage:warehouse", f"order:{oid}:fix"])
    pieces = next(task for task in tasks if task["key"].endswith(":stage:warehouse"))
    fix = next(task for task in tasks if task["key"].endswith(":fix"))
    assert (pieces["title"], pieces["who"], pieces["open"]) == ("Receive 926 pieces", "factory", "delivery")
    assert (fix["title"], fix["who"], fix["open"], fix["stage"]) == ("Receive 30 fix pieces", "factory", "delivery:fix", "warehouse")
    for task in tasks:
        assert task["waiting_on"] == "Main factory"
        assert task["due"] == TARGET.isoformat()
    assert fix["since"] == TODAY.isoformat()


def test_fix_pieces_are_one_task_when_the_warehouse_stage_says_the_same(owner):
    order = _all_the_way(owner)
    assert order["next_action"]["what"] == "Receive 30 fix pieces"
    tasks = _for(_list(owner), order["id"])
    assert [(task["key"], task["title"]) for task in tasks] == [(f"order:{order['id']}:fix", "Receive 30 fix pieces")]
    assert tasks[0]["since"] == TODAY.isoformat()


def test_a_delivery_not_yet_counted_is_one_task_for_the_qc_manager(owner, staff):
    order = _new(owner)
    oid = order["id"]
    _to_cutting(owner, oid)
    _cut(owner, oid)
    _inspected(owner, oid)
    created = _ok(_deliver(staff, oid, "finished", FIRST))
    delivery = created["deliveries"][0]
    tasks = _for(_list(owner), oid)
    assert [task["key"] for task in tasks] == [f"delivery:{delivery['id']}:count", f"order:{oid}:fix"]
    count = tasks[0]
    assert count["title"] == "Enter Khazenly's count for delivery 1"
    assert (count["who"], count["waiting_on"], count["open"]) == ("qc", None, f"delivery:{delivery['id']}")
    # Due the day after it shipped (the helper ships two days ago), and late for a day.
    assert count["due"] == _day(-1) and count["since"] == _day(-2)
    assert (count["group"], count["overdue_days"]) == ("overdue", 1)
    # The order's own next action is this count, and it is not listed twice.
    assert created["next_action"]["what"] == "Enter Khazenly's count"
    assert not [task for task in tasks if task["key"].endswith(":stage:warehouse")]

    # Counted: the task goes.
    counted = _ok(staff.patch(f"/api/prod/deliveries/{delivery['id']}", json={"counted": FIRST, "counted_on": _day(-1)}))
    assert counted["deliveries"][0]["waiting_for_count"] is False
    assert sorted(_keys({"tasks": _for(_list(owner), oid)})) == sorted([f"order:{oid}:stage:warehouse", f"order:{oid}:fix"])


def test_a_count_that_does_not_match_asks_for_a_reason_on_the_day_it_was_counted(owner, staff):
    order = _new(owner)
    oid = order["id"]
    _to_cutting(owner, oid)
    _cut(owner, oid)
    _inspected(owner, oid)
    _ok(_deliver(staff, oid, "finished", FIRST, counted_on=_day(-1), counted=FIRST))
    # One piece short on delivery 2, and no reason given yet.
    second = _ok(_deliver(staff, oid, "finished", SECOND, counted_on=_day(-1), counted={**SECOND, "M": 139}))
    d2 = second["deliveries"][1]
    tasks = _for(_list(owner), oid)
    reason = next(task for task in tasks if task["key"] == f"delivery:{d2['id']}:reason")
    assert reason["title"] == "Give a reason for 1 missing piece, delivery 2"
    assert (reason["who"], reason["due"], reason["since"]) == ("qc", _day(-1), _day(-1))
    assert reason["open"] == f"delivery-reason:{d2['id']}" and reason["stage"] == "warehouse"
    assert (reason["group"], reason["overdue_days"]) == ("overdue", 1)
    assert second["next_action"]["what"] == "Give a reason for the count that does not match"
    assert not [task for task in tasks if task["key"].endswith(":stage:warehouse")]

    # Giving the reason takes the task away.
    _ok(staff.patch(f"/api/prod/deliveries/{d2['id']}", json={"mismatch_reason": "One piece lost"}))
    assert not [task for task in _for(_list(owner), oid) if ":reason" in task["key"]]


def test_more_than_shipped_is_worded_as_such_and_a_single_delivery_needs_no_number(owner, staff):
    oid = _new(owner)["id"]
    _to_cutting(owner, oid)
    _cut(owner, oid)
    _inspected(owner, oid)
    _ok(_deliver(staff, oid, "finished", FIRST, counted_on=_day(-1), counted={**FIRST, "M": 141}))
    [reason] = [task for task in _for(_list(owner), oid) if task["key"].endswith(":reason")]
    assert reason["title"] == "Give a reason for 1 piece more than shipped"


def test_each_delivery_that_needs_something_has_its_own_task(owner, staff):
    oid = _new(owner)["id"]
    _to_cutting(owner, oid)
    _cut(owner, oid)
    _inspected(owner, oid)
    short = _ok(_deliver(staff, oid, "finished", FIRST, counted_on=_day(-1), counted={**FIRST, "S": 68, "M": 139}))
    waiting = _ok(_deliver(staff, oid, "finished", SECOND))
    ids = [d["id"] for d in waiting["deliveries"]]
    assert short["deliveries"][0]["needs_reason"] is True
    found = _for(_list(owner), oid)
    keys = [task["key"] for task in found]
    assert f"delivery:{ids[0]}:reason" in keys and f"delivery:{ids[1]}:count" in keys
    reason = next(task for task in found if task["key"] == f"delivery:{ids[0]}:reason")
    assert reason["title"] == "Give a reason for 3 missing pieces, delivery 1"
    assert next(task for task in found if task["key"] == f"delivery:{ids[1]}:count")["title"] == (
        "Enter Khazenly's count for delivery 2"
    )
    assert len(keys) == len(set(keys))


def test_an_order_that_is_settled_or_cancelled_has_no_tasks(owner):
    done = _all_the_way(owner)
    _ok(_deliver(owner, done["id"], "fix", FIX, counted_on=_day(0), counted=FIX))
    # Settle is now the owner's, and listed.
    assert [task["title"] for task in _for(_list(owner), done["id"])] == ["Settle with the factory"]
    assert _for(_list(owner), done["id"])[0]["open"] == "settle"
    _ok(owner.post(f"/api/prod/orders/{done['id']}/settle"))
    gone = _new(owner, colour="Off-white")
    _ok(owner.post(f"/api/prod/orders/{gone['id']}/cancel", json={"reason": "Style dropped"}))
    assert _list(owner)["tasks"] == []


def test_no_work_is_listed_twice_across_the_whole_life_of_an_order(owner, staff):
    """At every step of an order's life, every key is unique and no title
    appears twice for the same order and the same delivery."""
    order = _new(owner)
    oid = order["id"]

    def check():
        payload = _list(owner)
        keys = _keys(payload)
        assert len(keys) == len(set(keys)), keys
        titles = [(task["order"]["id"], task["title"]) for task in payload["tasks"]]
        assert len(titles) == len(set(titles)), titles
        return payload

    check()
    _ok(owner.post(f"/api/prod/orders/{oid}/sample", json={"decision": "approved"}))
    check()
    _to_cutting(owner, oid, repeat=True)
    check()
    _cut(owner, oid)
    check()
    _inspected(owner, oid)
    check()
    _ok(_deliver(staff, oid, "finished", FIRST))
    check()
    _ok(_deliver(staff, oid, "finished", SECOND))
    check()
    _ok(_deliver(staff, oid, "fix", FIX))
    check()


def test_the_key_of_a_task_stays_the_same_while_its_work_is_the_same(owner):
    order = _new(owner)
    first = _list(owner)["tasks"][0]["key"]
    _ok(owner.patch(f"/api/prod/orders/{order['id']}/stages/sample", json={"expected_date": _day(40)}))
    assert _list(owner)["tasks"][0]["key"] == first == f"order:{order['id']}:stage:sample"


# ── Grouping, order and counts ────────────────────────────────────────────────


def test_tasks_are_grouped_around_todays_date_in_cairo(owner):
    _add(owner, title="Yesterday", due_on=_day(-1))
    _add(owner, title="Today", due_on=_day(0))
    _add(owner, title="In seven days", due_on=_day(7))
    _add(owner, title="In eight days", due_on=_day(8))
    _add(owner, title="No date")
    _add(owner, title="A long time ago", due_on=_day(-30))
    found = {task["title"]: task for task in _list(owner)["tasks"]}
    assert (found["Yesterday"]["group"], found["Yesterday"]["overdue_days"]) == ("overdue", 1)
    assert (found["A long time ago"]["group"], found["A long time ago"]["overdue_days"]) == ("overdue", 30)
    assert (found["Today"]["group"], found["Today"]["overdue_days"]) == ("today", 0)
    assert found["In seven days"]["group"] == "week"
    assert found["In eight days"]["group"] == "later" and found["No date"]["group"] == "later"
    # Overdue first, oldest first; a dated task before an undated one in the same group.
    titles = [task["title"] for task in _list(owner)["tasks"]]
    assert titles == ["A long time ago", "Yesterday", "Today", "In seven days", "In eight days", "No date"]


def test_a_generated_task_is_overdue_by_the_days_since_its_date(owner):
    oid = _new(owner)["id"]
    _ok(owner.patch(f"/api/prod/orders/{oid}/stages/sample", json={"expected_date": _day(-3)}))
    [task] = _for(_list(owner), oid)
    assert (task["group"], task["overdue_days"], task["due"]) == ("overdue", 3, _day(-3))
    assert _list(owner)["counts"]["overdue"] == 1


def test_inside_a_group_tasks_go_by_date_then_order_code_then_title(owner):
    first = _new(owner, colour="Black")
    second = _new(owner, colour="Off-white")
    for order in (first, second):
        _ok(owner.patch(f"/api/prod/orders/{order['id']}/stages/sample", json={"expected_date": _day(2)}))
    _add(owner, title="B task", due_on=_day(2), order_id=first["id"])
    _add(owner, title="A task", due_on=_day(2), order_id=first["id"])
    _add(owner, title="Earlier", due_on=_day(1), order_id=second["id"])
    ordered = [(task["due"], task["order"]["code"], task["title"]) for task in _list(owner)["tasks"]]
    assert ordered == [
        (_day(1), second["code"], "Earlier"),
        (_day(2), first["code"], "A task"),
        (_day(2), first["code"], "Approve the sample"),
        (_day(2), first["code"], "B task"),
        (_day(2), second["code"], "Approve the sample"),
    ]


def test_the_counts_the_filters_show(owner, staff):
    _new(owner)  # owner: approve the sample
    _all_the_way(owner)  # factory: fix pieces
    _add(owner, title="Overdue and the QC manager's", due_on=_day(-2))
    _add(owner, title="Plan the season", for_owner=True)
    finished = _add(owner, title="Already done")
    assert owner.patch(f"/api/prod/tasks/{finished['id']}", json={"done": True}).status_code == 200
    payload = _list(owner)
    assert payload["counts"] == {"all": 4, "overdue": 1, "qc": 1, "owner": 2, "factory": 1}
    assert {task["who"] for task in payload["tasks"]} == {"owner", "qc", "factory"}
    # Done ones are on request, in a group of their own, and are not counted.
    with_done = _list(owner, done=True)
    assert with_done["counts"] == payload["counts"]
    assert with_done["tasks"][-1]["title"] == "Already done" and with_done["tasks"][-1]["group"] == "done"
    assert with_done["tasks"][-1]["done"] is True and with_done["tasks"][-1]["overdue_days"] == 0


# ── Hand-added tasks ──────────────────────────────────────────────────────────


def test_a_hand_added_task_is_made_edited_done_reopened_and_deleted(owner, staff):
    order = _new(owner)
    made = _add(staff, title="  Visit   the new print house ", due_on=_day(3), note="Ask about\nminimums")
    tid = made["id"]
    assert made == {
        "kind": "manual",
        "key": f"task:{tid}",
        "id": tid,
        "title": "Visit the new print house",
        "who": "qc",
        "due": _day(3),
        "order": None,
        "stage": None,
        "waiting_on": None,
        "since": None,
        "open": None,
        "note": "Ask about\nminimums",
        "done": False,
        "done_at": None,
        "for_owner": False,
        "group": "week",
        "overdue_days": 0,
    }
    assert any(task.get("id") == tid for task in _list(owner)["tasks"])

    edited = staff.patch(
        f"/api/prod/tasks/{tid}",
        json={"title": "Visit the print house", "due_on": _day(-1), "order_id": order["id"], "for_owner": True},
    )
    assert edited.status_code == 200, edited.text
    task = edited.json()["task"]
    assert (task["title"], task["due"], task["who"], task["group"]) == ("Visit the print house", _day(-1), "owner", "overdue")
    assert task["order"] == {"id": order["id"], "code": order["code"], "style_name": "Oversized hoodie", "colour": "Black"}
    assert task["note"] == "Ask about\nminimums"

    cleared = staff.patch(f"/api/prod/tasks/{tid}", json={"due_on": None, "order_id": None, "note": None}).json()["task"]
    assert (cleared["due"], cleared["order"], cleared["note"], cleared["group"]) == (None, None, None, "later")

    finished = staff.patch(f"/api/prod/tasks/{tid}", json={"done": True}).json()["task"]
    assert finished["done"] is True and finished["done_at"].endswith("Z") and finished["group"] == "done"
    assert tid not in [t.get("id") for t in _list(staff)["tasks"]]
    assert tid in [t.get("id") for t in _list(staff, done=True)["tasks"]]

    reopened = staff.patch(f"/api/prod/tasks/{tid}", json={"done": False}).json()["task"]
    assert reopened["done"] is False and reopened["done_at"] is None and reopened["group"] == "later"

    assert staff.delete(f"/api/prod/tasks/{tid}").json() == {"deleted": tid}
    assert tid not in [t.get("id") for t in _list(staff, done=True)["tasks"]]
    assert staff.patch(f"/api/prod/tasks/{tid}", json={"done": True}).status_code == 404
    assert staff.delete(f"/api/prod/tasks/{tid}").status_code == 404
    with SessionLocal() as db:  # hidden, not removed
        assert db.get(ProdTask, tid).deleted_at is not None


def test_every_write_is_audited_in_words_with_no_money(owner, staff):
    order = _new(owner)
    tid = _add(staff, title="Visit the print house", order_id=order["id"], for_owner=True)["id"]
    staff.patch(f"/api/prod/tasks/{tid}", json={"title": "Visit the new print house", "due_on": _day(4)})
    staff.patch(f"/api/prod/tasks/{tid}", json={"done": True})
    staff.patch(f"/api/prod/tasks/{tid}", json={"done": True})  # nothing changed: nothing recorded
    staff.patch(f"/api/prod/tasks/{tid}", json={"done": False})
    staff.delete(f"/api/prod/tasks/{tid}")
    events = _events(tid)
    assert [event.action for event in events] == [
        "production.task_added", "production.task_changed", "production.task_done",
        "production.task_reopened", "production.task_deleted",
    ]
    assert [event.after_json["summary"] for event in events] == [
        f"Added the task “Visit the print house” on {order['code']} for the owner",
        "Changed the title and the date of the task “Visit the new print house”",
        "Marked the task “Visit the new print house” done",
        "Reopened the task “Visit the new print house”",
        "Deleted the task “Visit the new print house”",
    ]
    assert all(event.actor_email == "qc@example.com" for event in events)
    _no_money([event.after_json for event in events])


def test_the_activity_log_reads_a_task_in_the_production_department(owner, staff):
    tid = _add(staff, title="Visit the print house")["id"]
    with SessionLocal() as db:
        event = db.scalars(select(AuditEvent).where(AuditEvent.subject == f"production:task:{tid}")).one()
        assert event.department == "production"


@pytest.mark.parametrize(
    "body, words",
    [
        ({"title": "   "}, "Give the task's title."),
        ({"title": "x" * 201}, "200 characters"),
        ({"title": "ok", "note": "n" * 2001}, "2,000 characters"),
    ],
)
def test_a_task_is_refused_in_words(owner, staff, body, words):
    response = staff.post("/api/prod/tasks", json=body)
    assert response.status_code == 422 and words in response.json()["detail"]


def test_a_task_needs_a_real_open_order(owner, staff):
    assert staff.post("/api/prod/tasks", json={"title": "x", "order_id": 9999}).status_code == 422
    assert staff.post("/api/prod/tasks", json={"title": "x", "order_id": 0}).status_code == 422
    assert staff.post("/api/prod/tasks", json={"title": "x"}).status_code == 201
    gone = _new(owner)
    _ok(owner.post(f"/api/prod/orders/{gone['id']}/cancel", json={"reason": "Style dropped"}))
    refused = staff.post("/api/prod/tasks", json={"title": "x", "order_id": gone["id"]})
    assert refused.status_code == 422 and "still in production" in refused.json()["detail"]
    live = _new(owner, colour="Off-white")
    tid = _add(staff, order_id=live["id"])["id"]
    assert staff.patch(f"/api/prod/tasks/{tid}", json={"order_id": gone["id"]}).status_code == 422
    # A task already on an order keeps it when the order is cancelled later.
    _ok(owner.post(f"/api/prod/orders/{live['id']}/cancel", json={"reason": "Style dropped"}))
    kept = next(task for task in _list(staff)["tasks"] if task.get("id") == tid)
    assert kept["order"]["id"] == live["id"]
    assert staff.patch(f"/api/prod/tasks/{tid}", json={"title": "Renamed"}).status_code == 200


def test_a_refused_edit_changes_nothing(owner, staff):
    tid = _add(staff, title="Keep me", due_on=_day(2))["id"]
    refused = staff.patch(f"/api/prod/tasks/{tid}", json={"due_on": _day(5), "title": "   "})
    assert refused.status_code == 422
    kept = next(task for task in _list(staff)["tasks"] if task.get("id") == tid)
    assert (kept["title"], kept["due"]) == ("Keep me", _day(2))
    assert len(_events(tid)) == 1  # only the creation
    assert staff.patch(f"/api/prod/tasks/{tid}", json={"title": None}).status_code == 422
    assert staff.patch("/api/prod/tasks/99999", json={"title": "x"}).status_code == 404


def test_the_done_list_keeps_fourteen_days(owner, staff):
    old = _add(staff, title="Done long ago")["id"]
    recent = _add(staff, title="Done last week")["id"]
    for tid in (old, recent):
        staff.patch(f"/api/prod/tasks/{tid}", json={"done": True})
    with engine.begin() as connection:
        for tid, days in ((old, 20), (recent, 10)):
            connection.execute(
                text("UPDATE prod_task SET done_at = :at WHERE id = :id"),
                {"at": utcnow() - timedelta(days=days), "id": tid},
            )
    shown = [task["title"] for task in _list(staff, done=True)["tasks"]]
    assert shown == ["Done last week"]
    assert _list(staff)["tasks"] == []


# ── No task carries money ─────────────────────────────────────────────────────


@pytest.mark.parametrize("role", ["production_viewer", "production_staff", "production_manager"])
def test_no_task_carries_money_for_anybody_without_the_owner_permission(owner, role):
    settled = _all_the_way(owner)
    owner.patch(f"/api/prod/orders/{settled['id']}", json={"actual_fabric_piastres": 17200})
    _all_the_way(owner)
    _new(owner, colour="Off-white")
    _add(owner, title="Chase the fabric invoice")
    person = _person(f"{role}@example.com", role)
    for path in ("/api/prod/tasks", "/api/prod/tasks?done=1"):
        response = person.get(path)
        assert response.status_code == 200, (role, path)
        _no_money(response.json(), path)
        assert "piastres" not in response.text
    # The owner sees the very same tasks: there is nothing more to see.
    assert [task["key"] for task in owner.get("/api/prod/tasks").json()["tasks"]] == [
        task["key"] for task in person.get("/api/prod/tasks").json()["tasks"]
    ]


def test_no_write_answer_carries_money_either(owner, staff):
    made = staff.post("/api/prod/tasks", json={"title": "Pay attention"}).json()
    _no_money(made)
    _no_money(staff.patch(f"/api/prod/tasks/{made['task']['id']}", json={"done": True}).json())
    _no_money(staff.delete(f"/api/prod/tasks/{made['task']['id']}").json())


# ── The migration ─────────────────────────────────────────────────────────────


def test_the_downgrade_refuses_while_a_task_exists(owner):
    from alembic import command
    from alembic.config import Config

    task = _add(owner)
    with pytest.raises(RuntimeError, match="production task"):
        command.downgrade(Config("alembic.ini"), "f6b3d8e10033")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "d4a8f2c60037"
        assert connection.execute(text("SELECT count(*) FROM prod_task WHERE id = :id"), {"id": task["id"]}).scalar_one() == 1
