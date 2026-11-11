"""Operations → Returns: refunds owed, Khazenly's tracking, and who may
change them (ADR 0079).

Khazenly is never called: its answers are built here in the shape read from
``tracking-api.khazenly.com`` on 10 November 2026, with nothing personal in
them (it carries none). Shopify is never called either.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.businesstime import utcnow
from app.db import engine
from app.main import app
from app.modules.operations.models import OpsRefund
from app.modules.operations.services import khazenly_tracking as tracking
from app.modules.operations.services import returns
from app.shared.models.audit import AuditEvent
from app.shared.models.identity import UserAccount

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)

RETURN_STEPS = [
    "New Return",
    "Ready for Pickup",
    "Return Picked Up",
    "In-transit to Fulfilment Center",
    "Return Reached Fulfilment Center",
    "Return Receiving In Progress",
    "Return Completed",
]


def _answer(number: str, steps: list[str], start: datetime = NOW - timedelta(days=2), po: str = "#31876-RE") -> dict:
    """Khazenly's answer for ``steps`` in the order they happened, one hour
    apart, returned newest first as Khazenly returns them."""
    timeline = []
    for index, step in enumerate(steps):
        at = start + timedelta(hours=index)
        timeline.append(
            {
                "attributes": {"type": "Order_Status__c"},
                "Name": f"OS-{index}",
                "Order_Status__c": step,
                "Order_Status_Date__c": at.strftime("%Y-%m-%dT%H:%M:%S.000+0000"),
                "Note__c": "shipment Delivered-" if step == "Return Completed" else None,
                "Id": f"a0{index}",
            }
        )
    return {
        "data": {
            "showCourierDetails": False,
            "showSupportButton": False,
            "timeline": list(reversed(timeline)),
            "order": {"Name": number, "PO_Number__c": po, "Account__c": "001x"},
        }
    }


class FakeClient:
    """Stands in for ``tracking.Client``: answers from a dict."""

    def __init__(self, answers: dict[str, object]):
        self.answers = answers
        self.asked: list[str] = []

    def track(self, raw: str) -> tracking.Tracking:
        number = tracking.normalise(raw)
        self.asked.append(number)
        found = self.answers.get(number)
        if found is None:
            raise tracking.NotFound(tracking.NOT_FOUND)
        if isinstance(found, Exception):
            raise found
        return tracking.parse(number, found)

    def close(self) -> None:
        pass


def _no_shopify(_number):
    return None


def _actor(db, role: str = "operations_staff") -> UserAccount:
    user = UserAccount(email=f"{role}@example.com", password_hash="x", status="active", display_name="Mona")
    db.add(user)
    db.flush()
    return user


KH1 = "KH-HBA-08997921"
KH2 = "KH-HBA-09000182"


# ── Reading Khazenly ──────────────────────────────────────────────────────────


def test_an_answer_is_read_newest_first_with_its_shopify_number():
    found = tracking.parse(KH1, _answer(KH1, RETURN_STEPS[:3]))
    assert [step.step for step in found.timeline] == ["Return Picked Up", "Ready for Pickup", "New Return"]
    assert found.merchant_order == "#31876-RE"
    assert found.order_number == "#31876"
    assert not found.received


def test_received_only_once_khazenly_says_return_completed():
    almost = tracking.parse(KH1, _answer(KH1, RETURN_STEPS[:-1]))
    assert not almost.received and almost.received_at is None
    done = tracking.parse(KH1, _answer(KH1, RETURN_STEPS))
    assert done.received
    assert done.received_at == NOW - timedelta(days=2) + timedelta(hours=6)
    assert done.latest.note == "shipment Delivered"


def test_an_answer_about_another_order_is_not_trusted():
    with pytest.raises(tracking.TrackingError):
        tracking.parse(KH1, _answer(KH2, RETURN_STEPS[:2]))


def test_a_malformed_answer_is_refused_in_words():
    with pytest.raises(tracking.TrackingError, match="couldn't read"):
        tracking.parse(KH1, {"nothing": True})


def _client(handler) -> tracking.Client:
    return tracking.Client(transport=httpx.MockTransport(handler))


def test_the_client_asks_by_reference_number_and_reads_the_answer():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["agent"] = request.headers["user-agent"]
        return httpx.Response(200, json=_answer(KH1, RETURN_STEPS[:2]))

    with _client(handler) as client:
        found = client.track(" kh-hba-08997921 ")
    assert seen["url"] == f"{tracking.BASE_URL}?referenceNumber={KH1}"
    assert "HBA" in seen["agent"]
    assert found.khazenly_number == KH1


def test_an_unknown_number_is_khazenlys_500_saying_404():
    def handler(_request):
        return httpx.Response(500, json="Request failed with status code 404")

    with _client(handler) as client, pytest.raises(tracking.NotFound):
        client.track(KH1)


def test_khazenly_down_is_a_tracking_error_not_not_found():
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    with _client(handler) as client, pytest.raises(tracking.TrackingError) as caught:
        client.track(KH1)
    assert not isinstance(caught.value, tracking.NotFound)
    assert str(caught.value) == tracking.UNAVAILABLE


def test_a_number_that_is_not_khazenlys_is_never_sent():
    def handler(_request):  # pragma: no cover - must not be reached
        raise AssertionError("asked Khazenly about a Shopify number")

    with _client(handler) as client, pytest.raises(tracking.NotFound):
        client.track("31876")


# ── Words in ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "raw", "kept"),
    [
        ("instapay", "0100 852 8883", "01008528883"),
        ("instapay", "+201002334705", "01002334705"),
        ("instapay", "mo339@instapay", "mo339@instapay"),
        ("instapay", "Karim@InstaPay", "Karim@instapay"),
        ("instapay", "Pay me https://ipn.eg/S/karim/instapay/ABC123 now.", "https://ipn.eg/S/karim/instapay/ABC123"),
        ("vodafone_cash", "01002334705", "01002334705"),
        ("bank_transfer", "CIB 1000 2000 3000", "CIB 1000 2000 3000"),
    ],
)
def test_a_refund_id_is_checked_against_its_method(method, raw, kept):
    assert returns.refund_to_of(method, raw) == kept


@pytest.mark.parametrize(("method", "raw"), [("instapay", "hello"), ("vodafone_cash", "mo339@instapay"), ("vodafone_cash", "12345")])
def test_a_refund_id_that_does_not_fit_its_method_is_refused(method, raw):
    with pytest.raises(returns.Refused):
        returns.refund_to_of(method, raw)


@pytest.mark.parametrize("raw", ["0", "-5", "abc", "12.345", "1000000"])
def test_an_amount_must_be_a_positive_sum_of_pounds(raw):
    with pytest.raises(returns.Refused):
        returns.amount_of(raw)


def test_an_amount_is_kept_to_two_places():
    assert returns.amount_of("736.1") == Decimal("736.10")
    assert returns.amount_of("1,070") == Decimal("1070.00")


# ── Adding ────────────────────────────────────────────────────────────────────


def _add(db, actor, numbers, answers, kind="return", details=None, shopify=_no_shopify):
    return returns.add(db, numbers, kind, actor, details, client=FakeClient(answers), shopify=shopify)


def test_a_refund_is_added_with_khazenlys_step_and_the_customer_from_shopify(db):
    actor = _actor(db)
    result = _add(
        db,
        actor,
        [KH1],
        {KH1: _answer(KH1, RETURN_STEPS[:3])},
        details={"amount": "395", "method": "instapay", "refund_to": "01060910507"},
        shopify=lambda number: returns.Customer(name="Khaled Magdy", phone="01060910507") if number == "#31876" else None,
    )
    assert result["refused"] == []
    row = db.scalar(select(OpsRefund))
    assert (row.khazenly_number, row.order_number, row.step) == (KH1, "#31876", "Return Picked Up")
    assert (row.customer_name, row.customer_phone) == ("Khaled Magdy", "01060910507")
    assert row.amount == Decimal("395.00") and row.received_at is None
    assert result["added"][0]["group"] == "on_the_way"
    db.flush()
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "order_ops.refund_added"))
    # The activity log names the refund, never the customer.
    assert event.after_json == {"number": KH1, "amount": "395.00", "kind": "return"}
    assert event.department == "operations"


def test_typed_customer_details_win_over_shopifys(db):
    _add(
        db,
        _actor(db),
        [KH1],
        {KH1: _answer(KH1, RETURN_STEPS[:2])},
        details={"customer_name": "Jana Mohamed"},
        shopify=lambda _n: returns.Customer(name="Someone Else", phone="01011111111"),
    )
    row = db.scalar(select(OpsRefund))
    assert row.customer_name == "Jana Mohamed"
    assert row.customer_phone == "01011111111"


def test_pasted_numbers_are_added_and_the_wrong_ones_say_why(db):
    actor = _actor(db)
    _add(db, actor, [KH1], {KH1: _answer(KH1, RETURN_STEPS[:2])})
    result = _add(
        db,
        actor,
        [f"{KH1}\n{KH2}, KH-HBA-00000001 31876 {KH2}"],
        {KH1: _answer(KH1, RETURN_STEPS[:2]), KH2: _answer(KH2, RETURN_STEPS, po="#31900-RE")},
        details={"amount": "999"},
    )
    assert [row["khazenly_number"] for row in result["added"]] == [KH2]
    # Details go with a single number only.
    assert result["added"][0]["amount"] is None
    assert result["added"][0]["group"] == "ready"
    reasons = {item["number"]: item["reason"] for item in result["refused"]}
    assert reasons[KH1] == "Already listed."
    assert reasons["KH-HBA-00000001"] == tracking.NOT_FOUND
    assert "isn't a Khazenly number" in reasons["31876"]


def test_khazenly_down_adds_nothing_and_says_try_again(db):
    result = _add(db, _actor(db), [KH1], {KH1: tracking.TrackingError(tracking.UNAVAILABLE)})
    assert result["added"] == []
    assert "Try again" in result["refused"][0]["reason"]
    assert db.scalar(select(OpsRefund)) is None


def test_too_many_numbers_at_once_are_refused(db):
    numbers = [f"KH-HBA-{9_000_000 + n:08d}" for n in range(returns.MAX_PASTED + 1)]
    with pytest.raises(returns.Refused, match="at most"):
        _add(db, _actor(db), numbers, {})


# ── Paying ────────────────────────────────────────────────────────────────────


def _row(db, steps, **details) -> tuple[OpsRefund, UserAccount]:
    actor = _actor(db)
    _add(db, actor, [KH1], {KH1: _answer(KH1, steps)}, details=details or None)
    return db.scalar(select(OpsRefund)), actor


def test_a_row_cannot_be_paid_before_khazenly_says_completed(db):
    row, actor = _row(db, RETURN_STEPS[:-1], amount="395", method="instapay", refund_to="01060910507")
    with pytest.raises(returns.Refused, match="completed"):
        returns.mark_paid(db, row.id, {}, actor)


def test_a_row_needs_its_amount_method_and_id_to_be_paid(db):
    row, actor = _row(db, RETURN_STEPS, amount="395")
    with pytest.raises(returns.Refused, match="how it was sent and the refund ID"):
        returns.mark_paid(db, row.id, {}, actor)


def test_marking_paid_records_the_day_and_locks_the_row(db):
    row, actor = _row(db, RETURN_STEPS)
    returns.mark_paid(
        db,
        row.id,
        {"paid_on": "2026-11-09", "amount": "430", "method": "vodafone_cash", "refund_to": "01002334705"},
        actor,
        today=date(2026, 11, 10),
    )
    assert row.paid_on == date(2026, 11, 9) and row.paid_by == actor.id
    assert row.amount == Decimal("430.00") and row.method == "vodafone_cash"
    with pytest.raises(returns.Locked):
        returns.edit(db, row.id, {"amount": "1"}, actor)
    with pytest.raises(returns.Locked):
        returns.delete(db, row.id, actor)
    with pytest.raises(returns.Locked):
        returns.mark_paid(db, row.id, {}, actor)


def test_a_paid_day_in_the_future_is_refused(db):
    row, actor = _row(db, RETURN_STEPS, amount="395", method="instapay", refund_to="01060910507")
    with pytest.raises(returns.Refused, match="future"):
        returns.mark_paid(db, row.id, {"paid_on": "2026-11-11"}, actor, today=date(2026, 11, 10))


def test_undoing_paid_needs_a_reason_and_logs_it(db):
    row, actor = _row(db, RETURN_STEPS, amount="395", method="instapay", refund_to="01060910507")
    returns.mark_paid(db, row.id, {}, actor)
    with pytest.raises(returns.Refused, match="Say why"):
        returns.undo_paid(db, row.id, " ", actor)
    returns.undo_paid(db, row.id, "Transfer bounced", actor)
    assert row.paid_on is None and row.paid_by is None
    db.flush()
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "order_ops.refund_unpaid"))
    assert event.reason == "Transfer bounced"


def test_the_database_refuses_a_paid_row_that_was_not_received(db):
    row, _ = _row(db, RETURN_STEPS[:2], amount="395", method="instapay", refund_to="01060910507")
    row.paid_on = date(2026, 11, 10)
    row.paid_recorded_at = utcnow()
    with pytest.raises(Exception, match="ops_refund_paid_complete"):
        db.flush()


def test_changing_the_method_rechecks_the_refund_id(db):
    row, actor = _row(db, RETURN_STEPS, method="instapay", refund_to="mo339@instapay")
    with pytest.raises(returns.Refused, match="Vodafone Cash"):
        returns.edit(db, row.id, {"method": "vodafone_cash"}, actor)


# ── Attention and the tab ─────────────────────────────────────────────────────


def test_a_return_that_has_not_moved_for_three_days_needs_attention(db):
    row, _ = _row(db, RETURN_STEPS[:2])
    row.step_at = NOW - timedelta(days=3, minutes=1)
    assert "stuck" in returns.attention(row, NOW)
    assert returns.group_of(row, NOW) == "attention"


def test_contact_success_manager_needs_attention(db):
    row, _ = _row(db, ["New Return", tracking.CONTACT_SUCCESS_MANAGER], )
    assert "contact_success_manager" in returns.attention(row, utcnow())


def test_received_and_unpaid_for_two_days_is_late_but_still_ready(db):
    row, _ = _row(db, RETURN_STEPS, amount="395", method="instapay", refund_to="01060910507")
    row.received_at = NOW - timedelta(days=2, minutes=1)
    assert returns.attention(row, NOW) == ["unpaid_late"]
    assert returns.group_of(row, NOW) == "ready"


def test_missing_details_alone_do_not_move_a_row_to_attention(db):
    row, _ = _row(db, RETURN_STEPS[:2])
    assert returns.attention(row, utcnow()) == ["details_missing"]
    assert returns.group_of(row, utcnow()) == "on_the_way"


def test_the_tab_totals_what_is_owed_and_what_was_refunded_this_month(db):
    actor = _actor(db)
    third = "KH-HBA-09000213"
    _add(db, actor, [KH1], {KH1: _answer(KH1, RETURN_STEPS)}, details={"amount": "395", "method": "instapay", "refund_to": "01060910507"})
    _add(db, actor, [KH2], {KH2: _answer(KH2, RETURN_STEPS)}, details={"amount": "100.50", "method": "instapay", "refund_to": "01060910507"})
    _add(db, actor, [third], {third: _answer(third, RETURN_STEPS[:2])}, details={"amount": "70"})
    paid = db.scalar(select(OpsRefund).where(OpsRefund.khazenly_number == KH2))
    returns.mark_paid(db, paid.id, {}, actor)
    found = returns.tab(db)
    assert found["totals"]["owed_now"] == "395.00"
    assert found["totals"]["owed_count"] == 1
    assert found["totals"]["refunded_this_month"] == "100.50"
    groups = {row["khazenly_number"]: row["group"] for row in found["refunds"]}
    assert groups == {KH1: "ready", KH2: "paid", third: "on_the_way"}
    assert found["refunds"][-1]["paid_by"] == "Mona"


# ── The 30-minute read ────────────────────────────────────────────────────────


def test_the_read_moves_rows_on_and_leaves_received_ones_alone(db):
    actor = _actor(db)
    third = "KH-HBA-09000213"
    _add(db, actor, [KH1], {KH1: _answer(KH1, RETURN_STEPS[:2])})
    _add(db, actor, [KH2], {KH2: _answer(KH2, RETURN_STEPS)})
    _add(db, actor, [third], {third: _answer(third, RETURN_STEPS[:2])})
    client = FakeClient({KH1: _answer(KH1, RETURN_STEPS), third: tracking.TrackingError(tracking.UNAVAILABLE)})
    asked = returns.read_waiting(db, client=client, pause=0)
    assert asked == 2 and sorted(client.asked) == sorted([KH1, third])
    rows = {row.khazenly_number: row for row in db.scalars(select(OpsRefund))}
    assert rows[KH1].received_at is not None and rows[KH1].step == "Return Completed"
    # A failed read keeps the last step and says why.
    assert rows[third].step == "Ready for Pickup" and rows[third].check_error == tracking.UNAVAILABLE
    assert returns.tab(db)["tracking"]["khazenly_down"] is True


def test_the_read_stops_when_khazenly_keeps_failing(db):
    actor = _actor(db)
    numbers = [f"KH-HBA-{9_100_000 + n:08d}" for n in range(8)]
    for number in numbers:
        _add(db, actor, [number], {number: _answer(number, RETURN_STEPS[:2])})
    down = FakeClient({number: tracking.TrackingError(tracking.UNAVAILABLE) for number in numbers})
    assert returns.read_waiting(db, client=down, pause=0) == returns.GIVE_UP_AFTER


def test_the_read_stops_at_its_time_budget_and_the_next_starts_where_it_stopped(db):
    actor = _actor(db)
    numbers = [f"KH-HBA-{9_200_000 + n:08d}" for n in range(4)]
    for number in numbers:
        _add(db, actor, [number], {number: _answer(number, RETURN_STEPS[:2])})
    ticks = iter(range(0, 1000, 100))
    client = FakeClient({number: _answer(number, RETURN_STEPS[:3]) for number in numbers})
    # Every check "takes" 100 seconds against a 150-second budget: two fit.
    assert returns.read_waiting(db, client=client, pause=0, budget_seconds=150, clock=lambda: next(ticks)) == 2
    first = list(client.asked)
    client.asked.clear()
    returns.read_waiting(db, client=client, pause=0)
    assert set(client.asked[:2]) == set(numbers) - set(first)


def test_received_is_never_taken_back(db):
    row, _ = _row(db, RETURN_STEPS)
    received = row.received_at
    returns.apply_tracking(row, tracking.parse(KH1, _answer(KH1, RETURN_STEPS[:2])), utcnow())
    assert row.received_at == received


def test_a_paid_row_is_not_checked_again(db):
    row, actor = _row(db, RETURN_STEPS, amount="395", method="instapay", refund_to="01060910507")
    returns.mark_paid(db, row.id, {}, actor)
    with pytest.raises(returns.Locked):
        returns.recheck(db, row.id, client=FakeClient({}))


def test_a_paid_day_before_khazenly_received_it_is_refused(db):
    row, actor = _row(db, RETURN_STEPS, amount="395", method="instapay", refund_to="01060910507")
    with pytest.raises(returns.Refused, match="before Khazenly received"):
        returns.mark_paid(db, row.id, {"paid_on": "2026-11-01"}, actor)


def test_the_read_is_scheduled_every_thirty_minutes_in_operations_lane():
    from app.shared.services.jobs import OPERATIONS_READS, JobKind
    from app.shared.services.schedule import SCHEDULE
    from app.worker import HANDLERS

    assert SCHEDULE[JobKind.ORDER_OPS_RETURNS][0] == timedelta(minutes=30)
    assert JobKind.ORDER_OPS_RETURNS in OPERATIONS_READS
    assert JobKind.ORDER_OPS_RETURNS in HANDLERS


# ── Who may do what, over HTTP ────────────────────────────────────────────────

BOOTSTRAP = {"email": "owner@example.com", "display_name": "Owner", "password": "quiet-harbour-lantern"}


@pytest.fixture()
def client(fresh_database, monkeypatch):
    """Signed in as the admin; Khazenly and Shopify stood in for."""
    monkeypatch.setattr(
        returns.tracking,
        "Client",
        lambda *a, **k: FakeClient({KH1: _answer(KH1, RETURN_STEPS), KH2: _answer(KH2, RETURN_STEPS[:2])}),
    )
    monkeypatch.setattr(returns, "shopify_customer", _no_shopify)
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _become(role: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = :r"), {"r": role})


def test_staff_add_edit_pay_and_undo_over_http(client):
    _become("operations_staff")
    added = client.post("/api/order-ops/returns", json={"numbers": [KH1], "kind": "exchange", "amount": "316"})
    assert added.status_code == 200, added.text
    refund = added.json()["added"][0]
    assert refund["kind"] == "exchange" and refund["group"] == "ready"

    edited = client.patch(f"/api/order-ops/returns/{refund['id']}", json={"method": "instapay", "refund_to": "1000953578"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["refund"]["refund_to"] == "01000953578"

    paid = client.post(f"/api/order-ops/returns/{refund['id']}/paid", json={})
    assert paid.status_code == 200, paid.text
    assert paid.json()["refund"]["group"] == "paid"
    assert client.patch(f"/api/order-ops/returns/{refund['id']}", json={"amount": "1"}).status_code == 409

    undone = client.post(f"/api/order-ops/returns/{refund['id']}/unpaid", json={"reason": "Sent to the wrong number"})
    assert undone.status_code == 200 and undone.json()["refund"]["group"] == "ready"
    assert client.delete(f"/api/order-ops/returns/{refund['id']}").status_code == 200


def test_a_viewer_sees_returns_and_khazenly_and_changes_nothing(client):
    added = client.post("/api/order-ops/returns", json={"numbers": [KH1], "kind": "return"})
    refund_id = added.json()["added"][0]["id"]
    _become("operations_viewer")
    assert client.get("/api/order-ops/returns").status_code == 200
    assert client.get("/api/khazenly").status_code == 200
    assert client.post("/api/order-ops/returns", json={"numbers": [KH2], "kind": "return"}).status_code == 403
    assert client.patch(f"/api/order-ops/returns/{refund_id}", json={"amount": "5"}).status_code == 403
    assert client.post(f"/api/order-ops/returns/{refund_id}/paid", json={}).status_code == 403
    assert client.post(f"/api/order-ops/returns/{refund_id}/check").status_code == 403
    assert client.delete(f"/api/order-ops/returns/{refund_id}").status_code == 403
    assert client.post("/api/khazenly", files={"file": ("a.xlsx", b"x")}).status_code == 403


def test_customer_service_sees_neither_returns_nor_the_rest_of_operations(client):
    _become("customer_service")
    assert client.get("/api/order-ops/returns").status_code == 403
    assert client.get("/api/order-ops/shopify").status_code == 403
    assert client.get("/api/khazenly").status_code == 200


def test_an_amount_that_is_not_a_number_is_a_readable_422(client):
    _become("operations_manager")
    response = client.post("/api/order-ops/returns", json={"numbers": [KH1], "kind": "return", "amount": "abc"})
    assert response.status_code == 422
    assert "number of pounds" in response.json()["detail"]
