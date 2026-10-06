"""The Bosta tab (ADR 0057; PRD B1-B6).

Bosta is never called. ``FakeBosta`` answers the way Bosta answered read-only
from staging on 6 October 2026: state codes filtered as strings, pages of a
limit, creation-day bounds, ``updatedAt`` as JavaScript prints a date, an
unknown tracking number as a 400 - and every order full of customer details,
so the tests can show none of them is kept.
"""

import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

from app.core.businesstime import BUSINESS_TIMEZONE, utcnow
from app.db import SessionLocal, engine
from app.main import app
from app.models.order_ops import OpsBostaDelivery, OpsBostaSync
from app.services.jobs import OPERATIONS_READS, JobKind
from app.services.order_ops import bosta
from app.services.order_ops.freshness import record_success
from app.services.order_ops.polling import KeyRefused, NotConnected, SourceUnavailable

UTC = timezone.utc


def _cairo(month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=BUSINESS_TIMEZONE)


def _js(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(
        "%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)"
    )


def _z(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _item(
    tracking: str,
    type_value: str = "Send",
    code: int = 10,
    created: datetime | None = None,
    updated: datetime | None = None,
    collected: datetime | None = None,
    printed: datetime | None = None,
    waiting: bool | None = None,
    order: str = "#31038",
) -> dict:
    created = created or _cairo(10, 5)
    item = {
        "_id": f"id-{tracking}",
        "trackingNumber": tracking,
        "type": {"code": 10, "value": type_value},
        "state": {"code": code, "value": f"state {code}", "pickedUpTime": "2026-10-09T10:00:00Z"},
        "creationTimestamp": int(created.timestamp() * 1000),
        "createdAt": _js(created),
        "updatedAt": _js(updated or created),
        "businessReference": f"kjevfa-qz:{order}",
        "receiver": {"firstName": "A", "phone": "+20 100 000 0000"},
        "dropOffAddress": {"firstLine": "1 Street", "city": {"name": "Cairo"}},
        "notes": "call first",
        "cod": 1500,
        "holder": {"name": "Courier", "phone": "+20 111"},
        "star": {"name": "Star", "phone": "+20 122"},
    }
    if collected:
        item["collectedFromBusiness"] = _z(collected)
    if printed:
        item["latestAWBPrintDate"] = _z(printed)
    if waiting is not None:
        item["state"]["waitingForBusinessAction"] = waiting
    return item


class FakeBosta:
    """Bosta's two read endpoints over a list of orders."""

    def __init__(self, items=(), status: int = 200):
        self.items = {item["trackingNumber"]: item for item in items}
        self.status = status
        self.calls: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.status != 200:
            return httpx.Response(self.status, json={})
        if request.method == "GET":
            tracking = request.url.path.rsplit("/", 1)[-1]
            self.calls.append({"get": tracking})
            item = self.items.get(tracking)
            if item is None:
                return httpx.Response(400, json={"success": False, "message": "not found"})
            return httpx.Response(200, json={"success": True, "data": item})

        body = json.loads(request.content)
        self.calls.append(body)
        codes = body.get("stateCodes")
        if codes is not None and not all(isinstance(code, str) for code in codes):
            return httpx.Response(400, json={"message": "stateCodes[0] must be a string"})
        found = list(self.items.values())
        if codes is not None:
            found = [i for i in found if str(i["state"]["code"]) in codes]
        if "createdAtStart" in body:
            start = date.fromisoformat(body["createdAtStart"])
            end = date.fromisoformat(body["createdAtEnd"])
            found = [
                i
                for i in found
                if start <= datetime.fromtimestamp(i["creationTimestamp"] / 1000, UTC).date() <= end
            ]
        if body.get("sortBy") == "-updatedAt":
            found.sort(key=lambda i: bosta._js_time(i["updatedAt"]), reverse=True)
        limit, page = body["limit"], body["page"]
        chunk = found[(page - 1) * limit : page * limit]
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {"deliveries": chunk, "count": 0, "page": page, "limit": limit},
            },
        )

    def client(self) -> bosta.BostaClient:
        client = bosta.BostaClient("test-key", transport=httpx.MockTransport(self.handler))
        client.retry_base_seconds = 0
        return client


# ── Bosta's answer, reduced ───────────────────────────────────────────────────


def test_only_the_named_fields_are_kept():
    created = _cairo(10, 5)
    parsed = bosta._parse(
        _item("5041829317", collected=_cairo(10, 6, 9), printed=_cairo(10, 5, 14), waiting=True),
        utcnow(),
    )
    assert parsed["tracking_number"] == "5041829317"
    assert parsed["created_at"] == created.astimezone(UTC)
    assert parsed["updated_at_bosta"] == created.astimezone(UTC)
    assert parsed["collected_at"] == _cairo(10, 6, 9).astimezone(UTC)
    assert parsed["awb_printed_at"] == _cairo(10, 5, 14).astimezone(UTC)
    assert parsed["waiting_for_action"] is True
    assert parsed["shopify_order_number"] == "#31038"
    assert parsed["unfinished"] is True
    kept = json.dumps(parsed, default=str)
    for secret in ("+20", "Street", "call first", "Courier", "1500"):
        assert secret not in kept


def test_a_missing_flag_is_false_and_a_reference_without_an_order_is_none():
    item = _item("1")
    item["businessReference"] = "kjevfa-qz:internal"
    parsed = bosta._parse(item, utcnow())
    assert parsed["waiting_for_action"] is False
    assert parsed["shopify_order_number"] is None


def test_the_table_has_no_customer_columns():
    columns = {column["name"] for column in inspect(engine).get_columns("ops_bosta_delivery")}
    assert columns == {
        "bosta_id", "tracking_number", "type_value", "state_code", "state_value",
        "created_at", "updated_at_bosta", "collected_at", "awb_printed_at",
        "waiting_for_action", "shopify_order_number", "unfinished", "deleted_at", "synced_at",
    }


def test_a_page_where_no_order_reads_is_a_failure_not_a_zero(db):
    broken = [_item(str(n)) for n in range(3)]
    for item in broken:
        del item["state"]
    with pytest.raises(SourceUnavailable, match="doesn't recognise"):
        bosta._upsert(db, broken, utcnow())


def test_one_order_that_does_not_read_is_skipped(db):
    odd = _item("odd")
    del odd["type"]
    assert [r["tracking_number"] for r in bosta._upsert(db, [odd, _item("ok")], utcnow())] == ["ok"]
    assert bosta._upsert(db, [odd], utcnow()) == []


def test_an_answer_of_the_wrong_shape_is_a_failure():
    with pytest.raises(SourceUnavailable, match="doesn't recognise"):
        bosta._parse({"_id": "x"}, utcnow())


# ── Talking to Bosta ──────────────────────────────────────────────────────────


def test_state_codes_go_as_strings_and_pages_run_until_one_is_short():
    fake = FakeBosta([_item(str(n)) for n in range(250)])
    found = fake.client().search_all(stateCodes=[str(c) for c in sorted(bosta.UNFINISHED)])
    assert len(found) == 250
    assert [call["page"] for call in fake.calls] == [1, 2]


def test_no_key_is_not_connected():
    with pytest.raises(NotConnected):
        bosta.BostaClient("")


@pytest.mark.parametrize(
    ("status", "raised", "reason"),
    [
        (401, KeyRefused, "Bosta refused the key."),
        (503, SourceUnavailable, "Bosta didn't answer."),
        (429, SourceUnavailable, "Bosta didn't answer."),
        (400, SourceUnavailable, "Bosta didn't accept Operations' search."),
    ],
)
def test_failures_are_named_in_plain_words(status, raised, reason):
    with pytest.raises(raised) as caught:
        FakeBosta(status=status).client().search(1)
    assert str(caught.value) == reason


# ── The read ──────────────────────────────────────────────────────────────────

NOW = _cairo(10, 6, 15)


def test_the_first_read_takes_the_unfinished_set_and_the_last_ten_days(db):
    fake = FakeBosta(
        [
            _item("new", code=10, created=_cairo(10, 6, 9)),
            _item("delivered-recent", code=45, created=_cairo(10, 1)),
            _item("delivered-old", code=45, created=_cairo(9, 1)),
        ]
    )
    held = bosta.read(db, fake.client(), now=NOW)

    stored = set(db.scalars(select(OpsBostaDelivery.tracking_number)))
    sync = db.get(OpsBostaSync, 1)
    assert stored == {"new", "delivered-recent"}
    assert held == 2
    assert sync.backfill_next == date(2026, 9, 26)  # 6 Oct back ten days
    assert sync.high_water == NOW
    # The last day read (27 Sep) may lack its first Cairo hours: a day's margin.
    assert bosta.read_back_to(db) == date(2026, 9, 28)


def test_history_carries_on_where_the_last_read_stopped_and_ends_in_january(db):
    db.add(OpsBostaSync(id=1, backfill_next=date(2026, 1, 5), high_water=NOW))
    db.flush()
    fake = FakeBosta([_item("jan", code=45, created=_cairo(1, 3))])

    bosta.read(db, fake.client(), now=NOW)

    assert db.get(OpsBostaSync, 1).backfill_next is None
    assert bosta.read_back_to(db) == bosta.HISTORY_START
    assert db.scalar(select(OpsBostaDelivery.tracking_number)) == "jan"


def test_an_order_that_finished_is_read_again_and_leaves_the_cards(db):
    fake = FakeBosta([_item("t1", code=10, created=_cairo(9, 20))])
    bosta.read(db, fake.client(), now=NOW)
    fake.items["t1"] = _item("t1", code=45, created=_cairo(9, 20))

    bosta.read(db, fake.client(), now=NOW + timedelta(minutes=5))

    row = db.scalar(select(OpsBostaDelivery))
    assert (row.state_code, row.unfinished, row.deleted_at) == (45, False, None)
    assert {"get": "t1"} in fake.calls


def test_an_order_deleted_on_bosta_is_marked_gone_and_counts_nowhere(db):
    fake = FakeBosta([_item("gone", code=10, created=_cairo(9, 20))])
    bosta.read(db, fake.client(), now=NOW)
    del fake.items["gone"]

    bosta.read(db, fake.client(), now=NOW + timedelta(minutes=5))

    assert db.scalar(select(OpsBostaDelivery.deleted_at)) is not None
    cards = {c["key"]: c["count"] for c in bosta.tab(db, now=NOW)["cards"]}
    assert cards["new_not_shipped"] == 0


def test_changes_are_read_down_to_the_last_newest_and_no_further(db):
    db.add(OpsBostaSync(id=1, backfill_next=None, high_water=_cairo(10, 6, 14)))
    db.flush()
    fake = FakeBosta(
        [
            _item("changed", code=45, created=_cairo(9, 1), updated=_cairo(10, 6, 14, 30)),
            _item("old", code=45, created=_cairo(8, 1), updated=_cairo(9, 2)),
        ]
    )

    bosta.read(db, fake.client(), now=NOW)

    assert db.get(OpsBostaSync, 1).high_water == _cairo(10, 6, 14, 30)
    assert "changed" in set(db.scalars(select(OpsBostaDelivery.tracking_number)))
    assert [c["page"] for c in fake.calls if c.get("sortBy") == "-updatedAt"] == [1]


def test_one_order_bosta_will_not_give_back_does_not_stop_the_read(db):
    fake = FakeBosta(
        [_item("odd", code=10, created=_cairo(9, 20)), _item("ok", code=10), _item("fine", code=10)]
    )
    bosta.read(db, fake.client(), now=NOW)
    del fake.items["ok"]  # finished and gone: read again, then marked gone
    fake.items["odd"]["state"]["code"] = 45  # finished, and now unreadable:
    del fake.items["odd"]["type"]

    later = NOW + timedelta(minutes=5)
    bosta.read(db, fake.client(), now=later)

    rows = {r.tracking_number: r for r in db.scalars(select(OpsBostaDelivery))}
    assert rows["ok"].deleted_at == later
    assert rows["odd"].unfinished is True and rows["odd"].synced_at == later


def test_more_changes_than_one_read_takes_reads_history_again(db, monkeypatch):
    monkeypatch.setattr(bosta, "PAGE_SIZE", 1)
    monkeypatch.setattr(bosta, "MAX_CHANGED_PAGES", 2)
    db.add(OpsBostaSync(id=1, backfill_next=None, high_water=_cairo(9, 1)))
    db.flush()
    fake = FakeBosta(
        [_item(f"c{n}", code=45, created=_cairo(9, 1), updated=_cairo(10, 6, n)) for n in range(4)]
    )
    monkeypatch.setattr(bosta, "MAX_PAGES", 50)

    bosta.read(db, fake.client(), now=NOW)

    sync = db.get(OpsBostaSync, 1)
    assert sync.backfill_next is not None  # history is being read again
    assert bosta.read_back_to(db) > date(2026, 9, 1)


def test_the_read_is_scheduled_every_five_minutes_in_the_operations_lane():
    import app.main  # noqa: F401 - registers the handlers
    from app.services.schedule import SCHEDULE
    from app.worker import HANDLERS

    assert SCHEDULE[JobKind.ORDER_OPS_BOSTA][0] == timedelta(minutes=5)
    assert JobKind.ORDER_OPS_BOSTA in HANDLERS
    assert JobKind.ORDER_OPS_BOSTA in OPERATIONS_READS


# ── The cards ─────────────────────────────────────────────────────────────────


def _store(db, tracking: str, **fields) -> None:
    bosta._upsert(db, [_item(tracking, **fields)], utcnow())
    db.flush()


def _cards(db, now):
    return {card["key"]: card for card in bosta.tab(db, now=now)["cards"]}


def test_new_not_shipped_is_more_than_two_working_days_with_friday_off(db):
    # Thursday 1 Oct. By Monday 5 Oct: Saturday, Sunday, Monday - 3 (Friday off).
    _store(db, "thu", code=10, created=_cairo(10, 1))
    # Saturday 3 Oct. By Monday: Sunday, Monday - 2, not more than 2.
    _store(db, "sat", code=10, created=_cairo(10, 3))
    _store(db, "picked", code=21, created=_cairo(9, 1))

    card = _cards(db, _cairo(10, 5, 15))["new_not_shipped"]

    assert [o["tracking_number"] for o in card["orders"]] == ["thu"]
    assert card["orders"][0]["waiting_working_days"] == 3
    assert card["orders"][0]["url"] == "https://business.bosta.co/orders/thu"


def test_not_printed_is_a_send_or_exchange_not_collected_with_no_print_date(db):
    _store(db, "send", type_value="Send", code=10)
    _store(db, "exchange", type_value="Exchange", code=10)
    _store(db, "printed", type_value="Send", code=10, printed=_cairo(10, 5, 13))
    _store(db, "return-pickup", type_value="Customer Return Pickup", code=10)
    _store(db, "collected", type_value="Send", code=24, collected=_cairo(10, 5, 16))

    card = _cards(db, NOW)["not_printed"]

    assert sorted(o["tracking_number"] for o in card["orders"]) == ["exchange", "send"]


def test_awaiting_your_action_is_bostas_own_flag(db):
    _store(db, "flagged", code=47, waiting=True)
    _store(db, "not", code=47, waiting=False)
    _store(db, "finished", code=45, waiting=True)

    card = _cards(db, NOW)["awaiting_action"]

    assert [o["tracking_number"] for o in card["orders"]] == ["flagged"]


def test_shipped_not_delivered_counts_working_days_from_collection(db):
    _store(db, "late", code=41, collected=_cairo(9, 30, 10))  # Thu, Sat, Sun, Mon: 4
    _store(db, "recent", code=41, collected=_cairo(10, 1, 10))  # Sat, Sun, Mon: 3
    _store(db, "delivered", code=45, collected=_cairo(9, 20))

    card = _cards(db, _cairo(10, 5, 15))["shipped_not_delivered"]

    assert [o["tracking_number"] for o in card["orders"]] == ["late"]
    assert card["orders"][0]["waiting_working_days"] == 4


def test_the_pickups_are_the_last_seven_cairo_days_by_collection(db):
    _store(db, "today", code=45, collected=_cairo(10, 6, 9))
    # 22:30 UTC on 4 Oct is 5 Oct in Cairo.
    _store(db, "late-night", code=45, collected=datetime(2026, 10, 4, 22, 30, tzinfo=UTC))
    _store(db, "too-old", code=45, collected=_cairo(9, 29, 12))
    db.add(OpsBostaSync(id=1, backfill_next=None, high_water=NOW))
    db.flush()

    pickups = bosta.tab(db, now=NOW)["pickups"]

    days = {day["date"]: day["count"] for day in pickups["days"]}
    assert list(days) == [f"2026-10-0{n}" for n in range(6, 0, -1)] + ["2026-09-30"]
    assert days["2026-10-06"] == 1 and days["2026-10-05"] == 1
    assert sum(days.values()) == 2
    assert pickups["complete"] is True


def test_the_pickups_say_when_history_is_not_whole_yet(db):
    db.add(OpsBostaSync(id=1, backfill_next=date(2026, 9, 26), high_water=NOW))
    db.flush()
    pickups = bosta.tab(db, now=NOW)["pickups"]
    assert pickups["complete"] is False
    assert pickups["read_back_to"] == "2026-09-28"


# ── B4 ────────────────────────────────────────────────────────────────────────


def _september(db):
    db.add(OpsBostaSync(id=1, backfill_next=None, high_water=NOW))
    for n in range(3):
        _store(db, f"send-{n}", type_value="Send", code=45, created=_cairo(9, 10))
    _store(db, "exchange", type_value="Exchange", code=46, created=_cairo(9, 11))
    _store(db, "pickup", type_value="Customer Return Pickup", code=46, created=_cairo(9, 12))
    _store(db, "rto-46", type_value="Return to Origin", code=46, created=_cairo(9, 13))
    _store(db, "rto-60", type_value="Return to Origin", code=60, created=_cairo(9, 14))
    _store(db, "unfinished", type_value="Send", code=24, created=_cairo(9, 15))
    # 21:30 UTC on 30 Sep is already 1 Oct in Cairo: outside September.
    _store(db, "october", type_value="Send", code=45, created=datetime(2026, 9, 30, 21, 30, tzinfo=UTC))
    # 22:30 UTC on 31 Aug is 1 Sep in Cairo: inside.
    _store(db, "first", type_value="Send", code=45, created=datetime(2026, 8, 31, 22, 30, tzinfo=UTC))


def test_the_success_rate_counts_the_way_bostas_dashboard_does(db):
    _september(db)
    rate = bosta.success_rate(db, date(2026, 9, 1), date(2026, 9, 30), now=NOW)
    assert rate == {
        "from": "2026-09-01",
        "to": "2026-09-30",
        "available": True,
        "successful": 6,  # 4 sends delivered, an exchange, a return collected
        "unsuccessful": 2,  # both returned to origin
        "finished": 8,
        "rate": 0.75,
    }


def test_a_range_with_nothing_finished_has_no_rate_rather_than_zero(db):
    db.add(OpsBostaSync(id=1, backfill_next=None, high_water=NOW))
    db.flush()
    rate = bosta.success_rate(db, date(2026, 6, 1), date(2026, 6, 2), now=NOW)
    assert rate["finished"] == 0 and rate["rate"] is None


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (date(2025, 12, 31), date(2026, 1, 5), "Not available before 1 Jan 2026."),
        (date(2026, 9, 5), date(2026, 9, 1), "The range starts after it ends."),
        (date(2026, 10, 1), date(2026, 10, 9), "The range ends after today."),
    ],
)
def test_a_range_that_cannot_be_asked_says_why(db, start, end, message):
    with pytest.raises(ValueError, match=message):
        bosta.success_rate(db, start, end, now=NOW)


def test_a_range_before_what_history_has_read_is_not_available_yet(db):
    db.add(OpsBostaSync(id=1, backfill_next=date(2026, 9, 26), high_water=NOW))
    db.flush()
    rate = bosta.success_rate(db, date(2026, 9, 1), date(2026, 9, 30), now=NOW)
    assert rate == {
        "from": "2026-09-01",
        "to": "2026-09-30",
        "available": False,
        "read_back_to": "2026-09-28",
    }


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
    body = client.get("/api/order-ops/bosta").json()
    assert body["freshness"]["state"] == "never"
    assert body["cards"] is None and body["pickups"] is None
    rate = client.get("/api/order-ops/bosta/success-rate?from=2026-09-01&to=2026-09-30").json()
    assert rate["available"] is False


def test_after_a_read_the_cards_and_the_rate_come_with_their_time(client):
    with SessionLocal() as session:
        _september(session)
        record_success(session, "bosta", 10)
        session.commit()

    body = client.get("/api/order-ops/bosta").json()
    rate = client.get("/api/order-ops/bosta/success-rate?from=2026-09-01&to=2026-09-30").json()

    assert body["freshness"]["state"] == "fresh"
    assert [card["key"] for card in body["cards"]] == [
        "new_not_shipped",
        "not_printed",
        "awaiting_action",
        "shipped_not_delivered",
    ]
    assert len(body["pickups"]["days"]) == 7
    assert rate["available"] is True and rate["rate"] == 0.75


def test_an_impossible_range_is_refused_in_words(client):
    response = client.get("/api/order-ops/bosta/success-rate?from=2025-12-01&to=2026-01-05")
    assert response.status_code == 422
    assert response.json()["detail"] == "Not available before 1 Jan 2026."


@pytest.mark.parametrize(
    ("role", "expected"),
    [("operations_manager", 200), ("affiliate_manager", 403), ("content_manager", 403)],
)
def test_the_bosta_tab_is_for_operations_only(client, role, expected):
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = :r"), {"r": role})
    assert client.get("/api/order-ops/bosta").status_code == expected
    rate = client.get("/api/order-ops/bosta/success-rate?from=2026-09-01&to=2026-09-02")
    assert rate.status_code == expected
