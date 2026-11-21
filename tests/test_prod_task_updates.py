"""Task follow-up (build plan 2026-11-19, section 2): the next action, update
lines, the Done view and the date filter. Every name here is invented."""

from datetime import timedelta

import pytest
from sqlalchemy import select, text

from app.core.businesstime import utcnow
from app.db import SessionLocal, engine
from app.shared.models.audit import AuditEvent
from tests.conftest import alembic_head
from tests.test_prod_orders import (  # noqa: F401  (fixtures)
    TODAY,
    _day,
    _no_money,
    owner,
    staff,
    viewer,
)


def _add(client, **over) -> dict:
    response = client.post("/api/prod/tasks", json={"title": "Chase the zips", **over})
    assert response.status_code == 201, response.text
    return response.json()["task"]


def _list(client, query: str = "") -> dict:
    response = client.get("/api/prod/tasks" + query)
    assert response.status_code == 200, response.text
    return response.json()


def _ids(payload: dict) -> list[int]:
    return [task["id"] for task in payload["tasks"] if task["kind"] == "manual"]


def _summaries(task_id: int) -> list[str]:
    with SessionLocal() as db:
        return [
            (e.after_json or {}).get("summary")
            for e in db.scalars(
                select(AuditEvent).where(AuditEvent.subject == f"production:task:{task_id}").order_by(AuditEvent.id)
            )
        ]


def _update(client, task_id: int, **body):
    return client.post(f"/api/prod/tasks/{task_id}/updates", json=body)


# ── The next action ───────────────────────────────────────────────────────────


def test_the_next_action_is_set_changed_and_cleared_in_the_history(owner, staff):
    task = _add(staff, next_action="  Call the supplier  ")
    assert task["next_action"] == "Call the supplier" and task["updates"] == [] and task["updated_at"] is None
    tid = task["id"]
    changed = staff.patch(f"/api/prod/tasks/{tid}", json={"next_action": "Send the sample back"}).json()["task"]
    assert changed["next_action"] == "Send the sample back"
    assert "Changed the next action of the task" in _summaries(tid)[-1]
    cleared = staff.patch(f"/api/prod/tasks/{tid}", json={"next_action": "  "}).json()["task"]
    assert cleared["next_action"] is None
    refused = staff.patch(f"/api/prod/tasks/{tid}", json={"next_action": "x" * 501})
    assert refused.status_code == 422 and "500" in refused.json()["detail"]


# ── Updates ───────────────────────────────────────────────────────────────────


def test_an_update_is_added_newest_first_and_may_change_the_next_action(owner, staff, viewer):
    tid = _add(staff, next_action="Call the supplier")["id"]
    assert _update(viewer, tid, text="Called").status_code == 403

    first = _update(staff, tid, text="  Called, no answer  ")
    assert first.status_code == 201, first.text
    task = first.json()["task"]
    assert task["next_action"] == "Call the supplier"  # left out: stays
    assert task["updates"][0]["text"] == "Called, no answer" and task["updates"][0]["next_action"] is None
    assert task["updates"][0]["created_by"] == "QC Manager"

    second = _update(owner, tid, text="They answered", next_action="Collect on Sunday").json()["task"]
    assert second["next_action"] == "Collect on Sunday"
    assert [u["text"] for u in second["updates"]] == ["They answered", "Called, no answer"]
    assert second["updates"][0]["next_action"] == "Collect on Sunday" and second["updates"][0]["created_by"] == "Owner"
    assert second["updated_at"] == second["updates"][0]["created_at"]

    cleared = _update(staff, tid, text="Collected", next_action=None).json()["task"]
    assert cleared["next_action"] is None and len(cleared["updates"]) == 3

    listed = next(t for t in _list(viewer)["tasks"] if t.get("id") == tid)
    assert [u["text"] for u in listed["updates"]] == ["Collected", "They answered", "Called, no answer"]
    summaries = _summaries(tid)
    assert "Added an update to the task “Chase the zips” and changed its next action" in summaries
    assert "Added an update to the task “Chase the zips”" in summaries
    _no_money(listed)


def test_an_update_is_refused_in_words_or_on_a_deleted_task_and_allowed_on_a_done_one(owner, staff):
    tid = _add(staff)["id"]
    blank = _update(staff, tid, text="   ")
    assert blank.status_code == 422 and blank.json()["detail"] == "Say what happened."
    assert _update(staff, tid, text="x" * 2001).status_code == 422
    assert _update(staff, tid, text="ok", next_action="y" * 501).status_code == 422
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM prod_task_update")).scalar_one() == 0

    assert staff.patch(f"/api/prod/tasks/{tid}", json={"done": True}).status_code == 200
    assert _update(staff, tid, text="Paid in cash after all").status_code == 201
    assert staff.delete(f"/api/prod/tasks/{tid}").status_code == 200
    assert _update(staff, tid, text="Too late").status_code == 404
    assert _update(staff, 99999, text="Nobody").status_code == 404


# ── The Done view and the date filter ─────────────────────────────────────────


def _done(client, task_id: int, days_ago: int = 0) -> None:
    assert client.patch(f"/api/prod/tasks/{task_id}", json={"done": True}).status_code == 200
    if days_ago:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE prod_task SET done_at = :at WHERE id = :id"),
                {"at": utcnow() - timedelta(days=days_ago), "id": task_id},
            )


def test_the_done_view_is_every_task_done_newest_first_with_counts(owner, staff):
    still_open = _add(staff, title="Still open")["id"]
    recent = _add(staff, title="Done today")["id"]
    old = _add(staff, title="Done long ago", for_owner=True)["id"]
    _done(staff, recent)
    _done(staff, old, days_ago=40)

    done = _list(staff, "?view=done")
    assert done["view"] == "done"
    assert _ids(done) == [recent, old]  # all of them, not only 14 days, newest first
    assert {t["group"] for t in done["tasks"]} == {"done"}
    assert done["counts"] == {"all": 2, "overdue": 0, "qc": 1, "owner": 1, "factory": 0}

    opened = _list(staff, "?view=open")
    assert opened["view"] == "open" and _ids(opened) == [still_open]
    assert _ids(_list(staff)) == [still_open]  # open is the default
    # The old switch still works as before: the last 14 days only.
    assert set(_ids(_list(staff, "?done=1"))) == {still_open, recent}

    # By the Cairo day it was marked done.
    assert _ids(_list(staff, f"?view=done&from={TODAY.isoformat()}")) == [recent]
    assert _ids(_list(staff, f"?view=done&to={_day(-1)}")) == [old]
    assert _list(staff, f"?view=done&from={_day(-1)}&to={_day(-1)}")["counts"]["all"] == 0


def test_the_open_view_keeps_tasks_with_a_deadline_in_the_range(owner, staff):
    past = _add(staff, title="Was due", due_on=_day(-3))["id"]
    today = _add(staff, title="Due today", due_on=_day(0))["id"]
    later = _add(staff, title="Due later", due_on=_day(10))["id"]
    none = _add(staff, title="No deadline")["id"]

    assert set(_ids(_list(staff))) == {past, today, later, none}
    ranged = _list(staff, f"?from={_day(-3)}&to={_day(0)}")
    assert set(_ids(ranged)) == {past, today}  # no deadline: left out once a bound is given
    assert ranged["counts"]["all"] == len(ranged["tasks"]) and ranged["counts"]["overdue"] == 1
    assert set(_ids(_list(staff, f"?from={_day(1)}"))) == {later}
    assert set(_ids(_list(staff, f"?to={_day(-1)}"))) == {past}
    assert set(_ids(_list(staff, f"?from={_day(0)}&to={_day(0)}"))) == {today}


def test_from_after_to_is_refused_in_words(owner, viewer):
    for query in (f"?from={_day(2)}&to={_day(1)}", f"?view=done&from={_day(2)}&to={_day(1)}"):
        refused = viewer.get("/api/prod/tasks" + query)
        assert refused.status_code == 422 and "after the To date" in refused.json()["detail"]
    assert viewer.get("/api/prod/tasks?view=later").status_code == 422
    assert viewer.get("/api/prod/tasks?from=not-a-date").status_code == 422


@pytest.mark.parametrize("role", ["production_viewer", "production_staff"])
def test_no_view_carries_money(owner, staff, role):
    from tests.test_prod_orders import _person

    tid = _add(staff, next_action="Ask the price")["id"]
    _update(staff, tid, text="Asked")
    _done(staff, _add(staff, title="Finished")["id"])
    person = _person(f"{role}@example.com", role)
    for query in ("", "?view=done", f"?from={_day(-5)}&to={_day(5)}"):
        response = person.get("/api/prod/tasks" + query)
        assert response.status_code == 200
        _no_money(response.json(), query)
        assert "piastres" not in response.text


# ── The migration ─────────────────────────────────────────────────────────────


def test_the_downgrade_refuses_while_a_task_update_exists(owner, staff):
    from alembic import command
    from alembic.config import Config

    tid = _add(staff)["id"]
    _update(staff, tid, text="Noted")
    with pytest.raises(RuntimeError, match="task update"):
        command.downgrade(Config("alembic.ini"), "e5b9a3d70038")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == alembic_head()
        assert connection.execute(text("SELECT count(*) FROM prod_task_update")).scalar_one() == 1
