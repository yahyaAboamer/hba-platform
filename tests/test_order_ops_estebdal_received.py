"""Marking a settled refund received in E-stebdal (ADR 0090).

E-stebdal is never called: ``FakeEstebdal`` answers as its public API does
(``openapi-public.json``, read 22 November 2026), with made-up requests.
"""

from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import settings
from app.core.businesstime import utcnow
from app.db import SessionLocal, engine
from app.main import app
from app.modules.operations.models import OpsRefund
from app.modules.operations.services import estebdal, estebdal_received, returns
from app.modules.operations.services.polling import KeyRefused, SourceUnavailable
from app.shared.models.audit import AuditEvent
from app.shared.models.identity import UserAccount
from app.shared.services.audit_words import _Names, sentence


class FakeEstebdal:
    """Stands in for ``EstebdalClient``: requests by order, and what was marked."""

    def __init__(self, requests: dict[str, list[dict]] | None = None, *, lists=None, marks=None):
        self.requests = requests or {}
        self.lists = lists  # an exception to raise when listing
        self.marks = marks  # an exception to raise when marking
        self.marked: list[tuple[str, bool]] = []

    def requests_for_order(self, order_number):
        if self.lists:
            raise self.lists
        return [dict(r) for r in self.requests.get(order_number, [])]

    def mark_received(self, request_id, notify):
        self.marked.append((request_id, notify))
        if self.marks:
            raise self.marks
        for items in self.requests.values():
            for item in items:
                if item["id"] == request_id:
                    item["status"] = "Processing"
        return {"status": "Processing", "cash_refund_recorded": False, "warnings": []}


def _req(rid, number, status="Approved", order="#32546"):
    return {"id": rid, "number": number, "order_number": order, "status": status}


def _actor(db) -> UserAccount:
    user = UserAccount(email="staff@example.com", password_hash="x", status="active", display_name="Mona")
    db.add(user)
    db.flush()
    return user


def _refund(db, *, paid=True, received=True, order="#32546", number="KH-HBA-09254008", notify=True) -> OpsRefund:
    now = utcnow()
    row = OpsRefund(
        khazenly_number=number,
        kind="return",
        order_number=order,
        customer_name="A Customer",
        customer_phone="01000000000",
        amount=Decimal("395.00"),
        method="instapay",
        refund_to="01060910507",
        received_at=now - timedelta(days=1) if received else None,
        paid_on=date.today() if paid else None,
        paid_recorded_at=now if paid else None,
        estebdal_notify=notify,
    )
    db.add(row)
    db.flush()
    return row


@contextmanager
def _same(db):
    """The test's own session in place of one per row; flushed, not committed."""
    yield db
    db.flush()


@pytest.fixture()
def auto(monkeypatch):
    monkeypatch.setattr(settings, "estebdal_mark_received", "auto")


# ── Which request, and what is kept ───────────────────────────────────────────


def test_the_one_approved_request_is_marked_with_the_rows_email_choice(db):
    row = _refund(db, notify=False)
    fake = FakeEstebdal({"#32546": [_req("r1", "#32546-R1")]})

    failed = estebdal_received.send(db, row, fake)

    assert failed is False
    assert fake.marked == [("r1", False)]
    assert row.estebdal_state == "done" and row.estebdal_request == "#32546-R1"
    assert row.estebdal_done_at is not None and row.estebdal_note is None


def test_two_approved_requests_wait_for_a_person_to_choose(db):
    row = _refund(db)
    fake = FakeEstebdal({"#32546": [_req("r2", "#32546-R2"), _req("r1", "#32546-R1")]})

    estebdal_received.send(db, row, fake)

    assert fake.marked == []
    assert row.estebdal_state == "choose"
    assert row.estebdal_choices == [{"id": "r1", "number": "#32546-R1"}, {"id": "r2", "number": "#32546-R2"}]

    estebdal_received.send(db, row, fake, choice="r2")
    assert fake.marked == [("r2", True)]
    assert row.estebdal_state == "done" and row.estebdal_request == "#32546-R2" and row.estebdal_choices == []


def test_a_choice_that_is_not_approved_is_refused(db):
    row = _refund(db)
    fake = FakeEstebdal({"#32546": [_req("r1", "#32546-R1"), _req("r9", "#32546-R2", "Closed")]})
    with pytest.raises(returns.Refused, match="isn't approved"):
        estebdal_received.send(db, row, fake, choice="r9")
    assert fake.marked == []


@pytest.mark.parametrize("status", ["Needs Review", "Pending Payment"])
def test_a_request_still_waiting_for_review_is_tried_again_later(db, status):
    row = _refund(db)
    fake = FakeEstebdal({"#32546": [_req("r1", "#32546-R1", status), _req("r0", "#32546-R0", "Closed")]})
    estebdal_received.send(db, row, fake)
    assert row.estebdal_state == "waiting"
    assert row.estebdal_note == "#32546-R1 is still waiting for review in E-stebdal."
    assert fake.marked == []


@pytest.mark.parametrize("status", ["Processing", "Closed"])
def test_a_request_already_received_counts_as_done_without_a_call(db, status):
    row = _refund(db)
    fake = FakeEstebdal({"#32546": [_req("r1", "#32546-R1", status)]})
    estebdal_received.send(db, row, fake)
    assert row.estebdal_state == "done" and row.estebdal_note == "Already received in E-stebdal."
    assert fake.marked == []


def test_rejected_or_cancelled_or_no_request_say_so(db):
    row = _refund(db)
    estebdal_received.send(db, row, FakeEstebdal({"#32546": [_req("r1", "#32546-R1", "Rejected"), _req("r2", "#32546-R2", "Cancelled")]}))
    assert row.estebdal_state == "missing" and "rejected or cancelled" in row.estebdal_note

    estebdal_received.send(db, row, FakeEstebdal({}))
    assert row.estebdal_state == "missing"
    assert row.estebdal_note == "There is no E-stebdal request for order #32546."


def test_a_row_with_no_order_number_asks_nothing(db):
    row = _refund(db, order=None)
    fake = FakeEstebdal(lists=AssertionError("asked E-stebdal"))
    assert estebdal_received.send(db, row, fake) is False
    assert row.estebdal_state == "missing" and "no Shopify order number" in row.estebdal_note


def test_a_refusal_keeps_estebdals_words_and_waits_for_a_person(db, auto):
    row = _refund(db)
    fake = FakeEstebdal({"#32546": [_req("r1", "#32546-R1")]}, marks=estebdal.Rejected("Return must be Approved"))
    assert estebdal_received.send(db, row, fake) is False
    assert row.estebdal_state == "refused"
    assert row.estebdal_note == "E-stebdal refused it: Return must be Approved"

    # The run never sends it again on its own; a person's Try again does.
    row.estebdal_tried_at = utcnow() - timedelta(hours=1)
    db.flush()
    assert estebdal_received.send_due(db, fake, transaction=_same) == 0
    fake.marks = None
    estebdal_received.by_hand(db, row.id, _actor(db), client=fake)
    assert row.estebdal_state == "done" and len(fake.marked) == 2


@pytest.mark.parametrize(
    "failure, words",
    [
        (SourceUnavailable("E-stebdal didn't answer."), "E-stebdal didn't answer. It will be tried again."),
        (KeyRefused("E-stebdal refused the key."), "E-stebdal refused the key. It may not be allowed to write: use an all-access key."),
    ],
)
def test_estebdal_failing_is_kept_on_the_row_and_reported(db, failure, words):
    row = _refund(db)
    fake = FakeEstebdal({"#32546": [_req("r1", "#32546-R1")]}, marks=failure)
    assert estebdal_received.send(db, row, fake) is True
    assert row.estebdal_state == "waiting" and row.estebdal_note == words


def test_a_lost_answer_is_found_done_on_the_next_try_without_a_second_mark(db):
    row = _refund(db)
    request = _req("r1", "#32546-R1")
    fake = FakeEstebdal({"#32546": [request]}, marks=SourceUnavailable("E-stebdal didn't answer."))
    estebdal_received.send(db, row, fake)
    assert row.estebdal_state == "waiting"

    # E-stebdal did receive it; only the answer was lost.
    request["status"] = "Processing"
    fake.marks = None
    estebdal_received.send(db, row, fake)
    assert row.estebdal_state == "done"
    assert fake.marked == [("r1", True)]


def test_the_activity_log_names_the_request_never_the_customer(db):
    row = _refund(db)
    actor = _actor(db)
    estebdal_received.send(db, row, FakeEstebdal({"#32546": [_req("r1", "#32546-R1")]}), actor=actor)
    db.flush()
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "order_ops.refund_estebdal_received"))
    assert event.after_json == {"number": "KH-HBA-09254008", "amount": "395.00", "request": "#32546-R1", "emailed": True, "by_hand": True}
    assert event.actor_id == actor.id
    assert "A Customer" not in str(event.after_json) and "0106" not in str(event.after_json)
    assert sentence(event, _Names(db, [event])) == "Marked #32546-R1 received in E-stebdal for the refund KH-HBA-09254008, customer emailed"


# ── The background run and the switch ────────────────────────────────────────


def test_the_run_sends_only_rows_that_are_paid_and_back(db, auto):
    done = _refund(db, number="KH-HBA-1", order="#1")
    unpaid = _refund(db, number="KH-HBA-2", order="#2", paid=False)
    on_the_way = _refund(db, number="KH-HBA-3", order="#3", received=False)
    fake = FakeEstebdal({f"#{n}": [_req(f"r{n}", f"#{n}-R1", order=f"#{n}")] for n in (1, 2, 3)})

    assert estebdal_received.send_due(db, fake, transaction=_same) == 1
    assert fake.marked == [("r1", True)]
    assert done.estebdal_state == "done"
    assert unpaid.estebdal_state is None and on_the_way.estebdal_state is None

    # Done is never sent again; a row tried a moment ago waits its turn.
    assert estebdal_received.send_due(db, fake, transaction=_same) == 0


def test_a_row_not_done_is_tried_again_after_fifteen_minutes(db, auto):
    row = _refund(db)
    fake = FakeEstebdal({"#32546": [_req("r1", "#32546-R1", "Needs Review")]})
    assert estebdal_received.send_due(db, fake, transaction=_same) == 1
    assert estebdal_received.send_due(db, fake, transaction=_same) == 0
    row.estebdal_tried_at = utcnow() - timedelta(minutes=16)
    db.flush()
    assert estebdal_received.send_due(db, fake, transaction=_same) == 1


def test_the_run_stops_after_three_failures_in_a_row(db, auto):
    for n in range(5):
        _refund(db, number=f"KH-HBA-{n}", order=f"#{n}")
    fake = FakeEstebdal(lists=SourceUnavailable("E-stebdal didn't answer."))
    assert estebdal_received.send_due(db, fake, transaction=_same) == 3


@pytest.mark.parametrize("mode", ["off", "manual"])
def test_the_run_sends_nothing_unless_the_switch_is_auto(db, monkeypatch, mode):
    monkeypatch.setattr(settings, "estebdal_mark_received", mode)
    row = _refund(db)
    fake = FakeEstebdal({"#32546": [_req("r1", "#32546-R1")]})
    assert estebdal_received.send_due(db, fake, transaction=_same) == 0
    assert fake.marked == [] and row.estebdal_state is None


def test_by_hand_is_refused_when_off_and_for_a_row_not_due(db, monkeypatch):
    actor = _actor(db)
    row = _refund(db)
    on_the_way = _refund(db, number="KH-HBA-OTW", received=False)
    fake = FakeEstebdal({"#32546": [_req("r1", "#32546-R1")]})

    monkeypatch.setattr(settings, "estebdal_mark_received", "off")
    with pytest.raises(returns.Refused, match="off on this server"):
        estebdal_received.by_hand(db, row.id, actor, client=fake)

    monkeypatch.setattr(settings, "estebdal_mark_received", "manual")
    with pytest.raises(returns.Refused, match="paid and back"):
        estebdal_received.by_hand(db, on_the_way.id, actor, client=fake)
    estebdal_received.by_hand(db, row.id, actor, client=fake)
    assert row.estebdal_state == "done"
    with pytest.raises(returns.Refused, match="paid and back"):
        estebdal_received.by_hand(db, row.id, actor, client=fake)


def test_undoing_paid_leaves_estebdal_done(db):
    row = _refund(db)
    actor = _actor(db)
    estebdal_received.send(db, row, FakeEstebdal({"#32546": [_req("r1", "#32546-R1")]}))
    returns.undo_paid(db, row.id, "Sent to the wrong number", actor)
    assert row.paid_on is None
    assert row.estebdal_state == "done" and row.estebdal_request == "#32546-R1"


def test_the_row_says_where_estebdal_stands(db):
    row = _refund(db)
    shown = returns.serialise(row)["estebdal"]
    assert shown["due"] is True and shown["state"] is None
    estebdal_received.send(db, row, FakeEstebdal({"#32546": [_req("r1", "#32546-R1")]}))
    shown = returns.serialise(row)["estebdal"]
    assert shown["due"] is False and shown["state"] == "done" and shown["request"] == "#32546-R1"


def test_the_send_is_scheduled_every_fifteen_minutes_in_the_operations_lane():
    from app.shared.services.jobs import OPERATIONS_READS, JobKind
    from app.shared.services.schedule import SCHEDULE
    from app.worker import HANDLERS

    assert SCHEDULE[JobKind.ORDER_OPS_ESTEBDAL_RECEIVED][0] == timedelta(minutes=15)
    assert JobKind.ORDER_OPS_ESTEBDAL_RECEIVED in OPERATIONS_READS
    assert JobKind.ORDER_OPS_ESTEBDAL_RECEIVED in HANDLERS


# ── Over HTTP ─────────────────────────────────────────────────────────────────

BOOTSTRAP = {"email": "owner@example.com", "display_name": "Owner", "password": "quiet-harbour-lantern"}


@pytest.fixture()
def client(fresh_database, monkeypatch):
    fake = FakeEstebdal({"#32546": [_req("r1", "#32546-R1")]})
    monkeypatch.setattr(estebdal_received, "_client_for", lambda db: fake)
    monkeypatch.setattr(settings, "estebdal_mark_received", "manual")
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        test_client.fake = fake
        yield test_client


def _become(role: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = :r"), {"r": role})


def _committed_refund() -> int:
    with SessionLocal() as db:
        row = _refund(db)
        db.commit()
        return row.id


def test_staff_mark_it_received_over_http_and_a_viewer_cannot(client):
    refund_id = _committed_refund()
    _become("operations_viewer")
    assert client.post(f"/api/order-ops/returns/{refund_id}/estebdal", json={}).status_code == 403

    _become("operations_staff")
    tab = client.get("/api/order-ops/returns").json()
    assert tab["estebdal_mode"] == "manual"
    sent = client.post(f"/api/order-ops/returns/{refund_id}/estebdal", json={})
    assert sent.status_code == 200, sent.text
    assert sent.json()["refund"]["estebdal"]["state"] == "done"
    assert client.fake.marked == [("r1", True)]

    again = client.post(f"/api/order-ops/returns/{refund_id}/estebdal", json={})
    assert again.status_code == 422 and "paid and back" in again.json()["detail"]


def test_each_row_of_the_run_is_committed_on_its_own(fresh_database, monkeypatch):
    """A send cannot be taken back, so a later row failing must not undo the
    record of one already sent."""
    monkeypatch.setattr(settings, "estebdal_mark_received", "auto")
    with SessionLocal() as setup:
        first = _refund(setup, number="KH-HBA-A", order="#1").id
        second = _refund(setup, number="KH-HBA-B", order="#2").id
        setup.commit()

    class Breaks(FakeEstebdal):
        def requests_for_order(self, order_number):
            if order_number == "#2":
                raise RuntimeError("a bug")
            return super().requests_for_order(order_number)

    fake = Breaks({"#1": [_req("r1", "#1-R1", order="#1")]})
    with SessionLocal() as job, pytest.raises(RuntimeError):
        estebdal_received.send_due(job, fake)

    with SessionLocal() as check:
        assert check.get(OpsRefund, first).estebdal_state == "done"
        assert check.get(OpsRefund, second).estebdal_state is None
        assert check.scalar(select(AuditEvent).where(AuditEvent.action == "order_ops.refund_estebdal_received")) is not None


# ── Typing a missing Shopify order number ─────────────────────────────────────


def test_a_missing_order_number_can_be_typed_on_a_paid_row_and_is_looked_up_again(db, auto):
    row = _refund(db, order=None)
    actor = _actor(db)
    fake = FakeEstebdal({"#32546": [_req("r1", "#32546-R1")]})
    estebdal_received.send(db, row, fake)
    assert row.estebdal_state == "missing"

    returns.set_order_number(db, row.id, " 32546 ", actor)
    assert row.order_number == "#32546"
    assert row.estebdal_state is None and row.estebdal_tried_at is None
    assert estebdal_received.send_due(db, fake, transaction=_same) == 1
    assert row.estebdal_state == "done" and fake.marked == [("r1", True)]

    db.flush()
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "order_ops.refund_order_number_added"))
    assert event.after_json == {"number": "KH-HBA-09254008", "amount": "395.00", "order": "#32546"}
    assert sentence(event, _Names(db, [event])) == "Added the Shopify order #32546 to the refund KH-HBA-09254008"


@pytest.mark.parametrize("raw", ["", "abc", "#12", "32546-RE", "#32546 #32547"])
def test_a_typed_order_number_must_be_a_shopify_number(db, raw):
    row = _refund(db, order=None)
    with pytest.raises(returns.Refused, match="for example #32546"):
        returns.set_order_number(db, row.id, raw, _actor(db))
    assert row.order_number is None


def test_an_order_number_khazenly_gave_is_never_replaced(db):
    row = _refund(db)
    with pytest.raises(returns.Refused, match="already has"):
        returns.set_order_number(db, row.id, "#11111", _actor(db))
    assert row.order_number == "#32546"


def test_typing_the_order_number_over_http_is_for_staff_only(client):
    with SessionLocal() as setup:
        refund_id = _refund(setup, order=None).id
        setup.commit()
    _become("operations_viewer")
    assert client.post(f"/api/order-ops/returns/{refund_id}/order-number", json={"order_number": "#32546"}).status_code == 403
    _become("operations_staff")
    bad = client.post(f"/api/order-ops/returns/{refund_id}/order-number", json={"order_number": "abc"})
    assert bad.status_code == 422 and "for example #32546" in bad.json()["detail"]
    added = client.post(f"/api/order-ops/returns/{refund_id}/order-number", json={"order_number": "#32546"})
    assert added.status_code == 200, added.text
    assert added.json()["refund"]["order_number"] == "#32546"
