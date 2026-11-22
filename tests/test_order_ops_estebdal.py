"""The E-stebdal tab (ADR 0057; PRD E1).

The response shape is the one E-stebdal returned read-only on 6 October 2026,
with made-up values. E-stebdal itself is never called: a mock transport
stands in for it.
"""

import json
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, text

from app.core.businesstime import BUSINESS_TIMEZONE, utcnow
from app.db import SessionLocal, engine
from app.main import app
from app.modules.operations.models import OpsEstebdalReturn
from app.shared.services.jobs import JobKind
from app.modules.operations.services import estebdal
from app.modules.operations.services.freshness import record_success
from app.modules.operations.services.polling import KeyRefused, NotConnected, SourceUnavailable


def _request(number: str, date: str = "2026-10-06T09:01:25.120Z", status: str = "Needs Review"):
    """A request as E-stebdal sends it, customer details and all."""
    return {
        "id": f"id-{number}",
        "orderId": "gid://shopify/Order/1",
        "orderNumber": f"#{number}",
        "returnNumber": f"#{number}-R1",
        "date": date,
        "customerInfo": {
            "customerName": "A Customer",
            "phone": "+20 100 000 0000",
            "email": "customer@example.com",
            "address1": "1 Street",
        },
        "refundedItems": [{"productName": "Dress", "reason": "Too small", "totalValue": 1500}],
        "status": status,
        "notes": "call after 5",
        "createdAt": date,
    }


def _client(pages=None, status: int = 200, seen=None) -> estebdal.EstebdalClient:
    pages = list(pages or [])

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if status != 200:
            return httpx.Response(status, json={})
        items, has_next = pages.pop(0)
        return httpx.Response(
            200,
            json={
                "data": items,
                "meta": {"totalCount": len(items), "hasNextPage": has_next},
                "warnings": [],
            },
        )

    client = estebdal.EstebdalClient("test-key", transport=httpx.MockTransport(handler))
    client.retry_base_seconds = 0
    return client


# ── Reading E-stebdal ─────────────────────────────────────────────────────────


def test_every_page_is_read_with_the_needs_review_filter_and_the_key():
    seen: list[httpx.Request] = []
    client = _client([([_request("30830")], True), ([_request("30794")], False)], seen=seen)

    requests = client.needs_review()

    assert [r["return_number"] for r in requests] == ["#30830-R1", "#30794-R1"]
    first = seen[0]
    assert first.url.path == "/api/v1/public/returns"
    assert first.headers["x-api-key"] == "test-key"
    assert json.loads(first.url.params["filter"]) == [
        {"field": "status", "operator": "isAnyOf", "value": ["Needs Review"]}
    ]
    assert [r.url.params["page"] for r in seen] == ["1", "2"]


def test_only_the_four_fields_are_kept():
    requests = _client([([_request("30830")], False)]).needs_review()
    assert set(requests[0]) == {"id", "return_number", "order_number", "requested_at"}
    assert requests[0]["requested_at"] == datetime.fromisoformat("2026-10-06T09:01:25.120+00:00")


def test_a_page_where_nothing_has_the_status_asked_for_is_a_failure_not_a_zero():
    """E-stebdal filters by status itself; if every item says otherwise, the
    answer changed shape, and a 0 would hide requests that are waiting."""
    client = _client([([_request("1", status="needs_review"), _request("2", status="")], False)])
    with pytest.raises(SourceUnavailable, match="doesn't recognise"):
        client.needs_review()


def test_a_request_seen_on_two_pages_counts_once():
    client = _client([([_request("1"), _request("2")], True), ([_request("2")], False)])
    assert sorted(r["order_number"] for r in client.needs_review()) == ["#1", "#2"]


def test_a_request_in_another_status_never_counts():
    client = _client([([_request("1"), _request("2", status="Approved")], False)])
    assert [r["order_number"] for r in client.needs_review()] == ["#1"]


def test_the_table_has_no_customer_columns():
    columns = {column["name"] for column in inspect(engine).get_columns("ops_estebdal_return")}
    assert columns == {"estebdal_id", "return_number", "order_number", "requested_at", "seen_at"}


def test_no_key_is_not_connected():
    with pytest.raises(NotConnected):
        estebdal.EstebdalClient("")


@pytest.mark.parametrize(
    ("status", "raised", "reason"),
    [
        (401, KeyRefused, "E-stebdal refused the key."),
        (403, KeyRefused, "E-stebdal refused the key."),
        # E-stebdal answers a wrong key with a 500, so it reads as an outage.
        (500, SourceUnavailable, "E-stebdal didn't answer."),
        (429, SourceUnavailable, "E-stebdal didn't answer."),
        (404, SourceUnavailable, "E-stebdal didn't answer."),
    ],
)
def test_failures_are_named_in_plain_words(status, raised, reason):
    with pytest.raises(raised) as caught:
        _client(status=status).needs_review()
    assert str(caught.value) == reason


def test_a_busy_minute_is_tried_again():
    answers = [
        httpx.Response(429, json={}),
        httpx.Response(
            200,
            json={"data": [_request("30830")], "meta": {"totalCount": 1, "hasNextPage": False}},
        ),
    ]
    client = estebdal.EstebdalClient(
        "test-key", transport=httpx.MockTransport(lambda request: answers.pop(0))
    )
    client.retry_base_seconds = 0
    assert len(client.needs_review()) == 1


def test_an_answer_of_the_wrong_shape_is_a_failure_not_a_zero():
    client = estebdal.EstebdalClient(
        "test-key",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"items": []})),
    )
    with pytest.raises(SourceUnavailable, match="doesn't recognise"):
        client.needs_review()


def test_each_read_replaces_the_whole_set(db):
    estebdal.read(db, _client([([_request("1"), _request("2")], False)]))
    # #1 was approved since: the next read no longer has it.
    stored = estebdal.read(db, _client([([_request("2")], False)]))

    assert stored == 1
    assert db.scalars(select(OpsEstebdalReturn.order_number)).all() == ["#2"]


def test_a_failed_read_leaves_the_last_set_in_place(db):
    estebdal.read(db, _client([([_request("1")], False)]))
    with pytest.raises(SourceUnavailable):
        estebdal.read(db, _client(status=500))
    assert db.scalar(select(func.count()).select_from(OpsEstebdalReturn)) == 1


def test_the_read_is_scheduled_every_five_minutes_in_the_operations_lane():
    import app.main  # noqa: F401 - registers the handlers
    from app.shared.services.jobs import OPERATIONS_READS
    from app.shared.services.schedule import SCHEDULE
    from app.worker import HANDLERS

    assert SCHEDULE[JobKind.ORDER_OPS_ESTEBDAL][0] == timedelta(minutes=5)
    assert JobKind.ORDER_OPS_ESTEBDAL in HANDLERS
    assert JobKind.ORDER_OPS_ESTEBDAL in OPERATIONS_READS


# ── The tab ───────────────────────────────────────────────────────────────────


def _cairo(day: int, hour: int) -> datetime:
    return datetime(2026, 10, day, hour, tzinfo=BUSINESS_TIMEZONE)


def _store(db, number: str, requested: datetime) -> None:
    db.add(
        OpsEstebdalReturn(
            estebdal_id=f"id-{number}",
            return_number=f"#{number}-R1",
            order_number=f"#{number}",
            requested_at=requested,
            seen_at=utcnow(),
        )
    )
    db.flush()


def test_the_tab_lists_newest_first_with_how_long_each_has_waited(db):
    _store(db, "30751", _cairo(1, 11))
    _store(db, "30830", _cairo(3, 13))
    _store(db, "30794", _cairo(2, 19))

    body = estebdal.tab(db, "hbawear.myshopify.com", now=_cairo(3, 15))

    card = body["cards"][0]
    assert body["total"] == 3
    assert card["key"] == "needs_review" and card["count"] == 3
    assert [r["return_number"] for r in card["requests"]] == ["#30830-R1", "#30794-R1", "#30751-R1"]
    assert [r["waiting_days"] for r in card["requests"]] == [0, 1, 2]
    assert card["requests"][0]["url"] == "https://hbawear.myshopify.com/admin/apps/e-stebdal"
    assert set(card["requests"][0]) == {
        "return_number", "order_number", "requested_at", "waiting_days", "url",
    }


def test_without_a_shop_domain_there_is_no_link():
    assert estebdal.home_url(None) is None
    assert estebdal.home_url("") is None


# ── Through the API ───────────────────────────────────────────────────────────

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "quiet-harbour-lantern",
}


@pytest.fixture()
def client(fresh_database):
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def test_before_the_first_read_there_are_no_numbers(client):
    body = client.get("/api/order-ops/estebdal").json()
    assert body["freshness"]["state"] == "never"
    assert body["cards"] is None


def test_after_a_read_the_card_comes_with_its_time(client):
    with SessionLocal() as session:
        _store(session, "30830", _cairo(3, 13))
        record_success(session, "estebdal", 1)
        session.commit()

    body = client.get("/api/order-ops/estebdal").json()

    assert body["freshness"]["state"] == "fresh"
    assert body["cards"][0]["count"] == 1


@pytest.mark.parametrize(
    ("role", "expected"),
    [("operations_manager", 200), ("affiliate_manager", 403), ("content_manager", 403)],
)
def test_the_estebdal_tab_is_for_operations_only(client, role, expected):
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = :r"), {"r": role})
    assert client.get("/api/order-ops/estebdal").status_code == expected


# ── Marking a request received (ADR 0090) ─────────────────────────────────────


def _write_client(handler) -> estebdal.EstebdalClient:
    client = estebdal.EstebdalClient("all-access-key", transport=httpx.MockTransport(handler))
    client.retry_base_seconds = 0
    return client


def _listing(*items, has_next=False):
    return httpx.Response(200, json={"data": list(items), "meta": {"hasNextPage": has_next}, "warnings": []})


def test_requests_for_an_order_keep_only_that_exact_order():
    seen = []

    def handler(request):
        seen.append(request)
        return _listing(
            _request("32546", status="Approved"),
            _request("132546", status="Approved"),
            {**_request("32546", status="Closed"), "id": "id-32546-b", "returnNumber": "#32546-R2"},
        )

    found = _write_client(handler).requests_for_order("#32546")

    assert sorted((r["number"], r["status"]) for r in found) == [("#32546-R1", "Approved"), ("#32546-R2", "Closed")]
    assert set(found[0]) == {"id", "number", "order_number", "status"}
    sent = json.loads(seen[0].url.params["filter"])
    assert sent == [{"field": "returnNumber", "operator": "contains", "value": "32546-R"}]
    assert seen[0].headers["x-api-key"] == "all-access-key"


def test_an_order_with_no_number_asks_nothing():
    def handler(request):  # pragma: no cover - must not be called
        raise AssertionError("asked E-stebdal")

    assert _write_client(handler).requests_for_order(None) == []


def test_mark_received_posts_once_with_the_email_choice():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "data": {"status": "Processing", "cashRefundRecorded": True},
                "warnings": [{"message": "Settlement note", "code": "W"}],
            },
        )

    answer = _write_client(handler).mark_received("507f1f77bcf86cd799439011", notify=False)

    assert answer == {"status": "Processing", "cash_refund_recorded": True, "warnings": ["Settlement note"]}
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/api/v1/public/returns/507f1f77bcf86cd799439011/received"
    assert json.loads(seen[0].content) == {"notifyCustomer": False}
    assert seen[0].headers["x-api-key"] == "all-access-key"


def test_a_refusal_carries_estebdals_own_words():
    def handler(request):
        return httpx.Response(400, json={"error": {"message": "Return must be Approved", "code": "BAD"}})

    with pytest.raises(estebdal.Rejected, match="Return must be Approved"):
        _write_client(handler).mark_received("r1", notify=True)


@pytest.mark.parametrize("status, raised", [(500, SourceUnavailable), (429, SourceUnavailable), (403, KeyRefused), (401, KeyRefused)])
def test_a_failed_write_is_tried_once_only(status, raised):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, json={})

    with pytest.raises(raised):
        _write_client(handler).mark_received("r1", notify=True)
    assert len(seen) == 1


def test_a_write_that_never_answers_is_unavailable_not_repeated():
    seen = []

    def handler(request):
        seen.append(request)
        raise httpx.ReadTimeout("slow")

    with pytest.raises(SourceUnavailable):
        _write_client(handler).mark_received("r1", notify=True)
    assert len(seen) == 1
