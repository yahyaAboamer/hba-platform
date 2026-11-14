"""Production's Tasks (ADR 0084, decision 7; build plan
``docs/plans/2026-11-14-production-tasks-build.md``).

Two kinds of task, in one list:

* **generated**: worked out on each read from the open orders by
  ``orders.generated_tasks``. Never stored; a task goes when its work is done
  because the order's own state moved on.
* **manual**: a row in ``prod_task``, typed in by somebody. Done when somebody
  marks it done; can be reopened; deleting one only hides it.

Every write here only stages; the route commits on success and rolls back on
a refusal (the same pattern as ``orders``). **No task carries money**: the
server never writes a cost, rate or amount into a title or a note, and every
history sentence is built from words and counts only.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import business_date, utcnow
from app.modules.production.orders.models import ProdOrder, ProdTask
from app.modules.production.orders.services.orders import (
    NotFound,
    Refused,
    _day,
    _iso,
    _text,
    _words,
    generated_tasks,
    today,
)
from app.shared.models.identity import UserAccount
from app.shared.services.audit import record_audit

MAX_TITLE = 200
MAX_NOTE = 2000

#: How long a hand-added task stays in the list of done ones.
DONE_DAYS = 14

GROUPS = ("overdue", "today", "week", "later")


# ── Small helpers ─────────────────────────────────────────────────────────────


def group_of(due: str | None, on: date) -> tuple[str, int]:
    """Which group a task is in for ``on`` (Cairo's date), and how many days
    overdue it is. No date is ``later``."""
    if due is None:
        return "later", 0
    day = date.fromisoformat(due)
    if day < on:
        return "overdue", (on - day).days
    if day == on:
        return "today", 0
    if day <= on + timedelta(days=7):
        return "week", 0
    return "later", 0


def _note(value: str | None) -> str | None:
    """A note keeps its line breaks; blank is no note."""
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > MAX_NOTE:
        raise Refused(f"Keep the note to {MAX_NOTE:,} characters.")
    return cleaned


def _title(value: str | None) -> str:
    return _text(value, limit=MAX_TITLE, what="the task's title", required=True) or ""


def _order_ref(order: ProdOrder | None) -> dict | None:
    if order is None:
        return None
    return {"id": order.id, "code": order.code, "style_name": order.style_name, "colour": order.colour}


def _open_order(db: Session, order_id: int) -> ProdOrder:
    order = db.get(ProdOrder, order_id)
    if order is None or order.status != "open":
        raise Refused("Pick an order that is still in production.")
    return order


def _audit(db: Session, task: ProdTask, actor: UserAccount, what: str, summary: str) -> None:
    """One history entry for the task. Words only: never a figure of money."""
    record_audit(
        db,
        action=f"production.task_{what}",
        subject=f"production:task:{task.id}",
        actor_id=actor.id,
        actor_email=actor.email,
        after={"summary": summary[:500]},
    )


def _quoted(title: str) -> str:
    return f"“{title}”"


# ── The list ──────────────────────────────────────────────────────────────────


def _manual(row: ProdTask, order: ProdOrder | None, on: date) -> dict:
    due = _day(row.due_on)
    group, late = group_of(due, on)
    done = row.done_at is not None
    return {
        "kind": "manual",
        "key": f"task:{row.id}",
        "id": row.id,
        "title": row.title,
        "who": "owner" if row.for_owner else "qc",
        "due": due,
        "order": _order_ref(order),
        "stage": None,
        "waiting_on": None,
        "since": None,
        "open": None,
        "note": row.note,
        "done": done,
        "done_at": _iso(row.done_at),
        "for_owner": row.for_owner,
        # A done task is in a group of its own at the end of the list, and is never late.
        "group": "done" if done else group,
        "overdue_days": 0 if done else late,
    }


def _generated(task: dict, on: date) -> dict:
    group, late = group_of(task["due"], on)
    return {"kind": "generated", **task, "group": group, "overdue_days": late}


def _sort_key(task: dict) -> tuple:
    order = task["order"]
    return (
        GROUPS.index(task["group"]) if task["group"] in GROUPS else len(GROUPS),
        task["due"] is None,
        task["due"] or "",
        order["code"] if order else "",
        task["title"],
    )


def listing(db: Session, *, show_done: bool = False) -> dict:
    """Every open task, grouped and counted, for anybody who reads Production.

    ``show_done`` adds the hand-added tasks marked done in the last 14 days,
    in a ``done`` group at the end; they are not counted."""
    on = today()
    query = select(ProdTask).where(ProdTask.deleted_at.is_(None))
    if show_done:
        recently = utcnow() - timedelta(days=DONE_DAYS + 2)
        query = query.where(ProdTask.done_at.is_(None) | (ProdTask.done_at >= recently))
    else:
        query = query.where(ProdTask.done_at.is_(None))
    rows = list(db.scalars(query))
    if show_done:
        rows = [
            row for row in rows
            if row.done_at is None or business_date(row.done_at) >= on - timedelta(days=DONE_DAYS)
        ]
    ids = {row.order_id for row in rows if row.order_id}
    orders = {o.id: o for o in db.scalars(select(ProdOrder).where(ProdOrder.id.in_(ids)))} if ids else {}

    tasks = [_generated(task, on) for task in generated_tasks(db, on)]
    tasks += [_manual(row, orders.get(row.order_id), on) for row in rows]
    tasks.sort(key=_sort_key)

    open_tasks = [task for task in tasks if not task.get("done")]
    counts = {
        "all": len(open_tasks),
        "overdue": sum(1 for task in open_tasks if task["group"] == "overdue"),
        "qc": sum(1 for task in open_tasks if task["who"] == "qc"),
        "owner": sum(1 for task in open_tasks if task["who"] == "owner"),
        "factory": sum(1 for task in open_tasks if task["who"] == "factory"),
    }
    return {"today": on.isoformat(), "counts": counts, "tasks": tasks}


def view(db: Session, task: ProdTask) -> dict:
    """One hand-added task, as the list shows it."""
    order = db.get(ProdOrder, task.order_id) if task.order_id else None
    return _manual(task, order, today())


# ── Hand-added tasks ──────────────────────────────────────────────────────────


def _one(db: Session, task_id: int) -> ProdTask:
    task = db.get(ProdTask, task_id, with_for_update=True)
    if task is None or task.deleted_at is not None:
        raise NotFound("There is no such task.")
    return task


def create(db: Session, data: dict, actor: UserAccount) -> ProdTask:
    title = _title(data.get("title"))
    order = _open_order(db, data["order_id"]) if data.get("order_id") else None
    task = ProdTask(
        title=title,
        due_on=data.get("due_on"),
        order_id=order.id if order else None,
        note=_note(data.get("note")),
        for_owner=bool(data.get("for_owner")),
        created_by=actor.id,
    )
    db.add(task)
    db.flush()
    where = f" on {order.code}" if order else ""
    for_whom = " for the owner" if task.for_owner else ""
    _audit(db, task, actor, "added", f"Added the task {_quoted(task.title)}{where}{for_whom}")
    return task


def edit(db: Session, task_id: int, data: dict, actor: UserAccount) -> ProdTask:
    """Change what was sent: ``title``, ``due_on``, ``order_id``, ``note``,
    ``for_owner`` and ``done``. Marking an already-done task done, or an open
    one open, changes nothing."""
    task = _one(db, task_id)
    changed: list[str] = []

    if "title" in data:
        title = _title(data["title"])
        if title != task.title:
            task.title = title
            changed.append("the title")
    if "due_on" in data and data["due_on"] != task.due_on:
        task.due_on = data["due_on"]
        changed.append("the date")
    if "order_id" in data and data["order_id"] != task.order_id:
        task.order_id = _open_order(db, data["order_id"]).id if data["order_id"] else None
        changed.append("the order")
    if "note" in data:
        note = _note(data["note"])
        if note != task.note:
            task.note = note
            changed.append("the note")
    if data.get("for_owner") is not None and data["for_owner"] != task.for_owner:
        task.for_owner = data["for_owner"]
        changed.append("whose list it is on")

    name = _quoted(task.title)
    if changed:
        _audit(db, task, actor, "changed", f"Changed {_words(changed)} of the task {name}")
    if data.get("done") is True and task.done_at is None:
        task.done_at = utcnow()
        task.done_by = actor.id
        _audit(db, task, actor, "done", f"Marked the task {name} done")
    elif data.get("done") is False and task.done_at is not None:
        task.done_at = None
        task.done_by = None
        _audit(db, task, actor, "reopened", f"Reopened the task {name}")
    db.flush()
    return task


def delete(db: Session, task_id: int, actor: UserAccount) -> ProdTask:
    task = _one(db, task_id)
    task.deleted_at = utcnow()
    _audit(db, task, actor, "deleted", f"Deleted the task {_quoted(task.title)}")
    return task
