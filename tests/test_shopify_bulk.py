"""Historical import via Shopify's Bulk Operations API.

Paginating a year of orders would be hundreds of throttled requests. A bulk
operation runs server-side and returns one JSONL file.
"""

import json
import logging

import httpx
import pytest
from sqlalchemy import text

from app.core.signals import Anomaly
from app.models.orders import OrderIndex
from app.services.jobs import JobKind, PermanentFailure
from app.services.shopify.bulk import (
    MAX_POLLS,
    ingest_jsonl,
    poll_bulk_operation,
    start_bulk_import,
)
from app.services.shopify.client import ShopifyClient, ShopifyError


def _client(responses):
    """responses: dicts returned in order; the last repeats."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return httpx.Response(200, json=payload)

    return ShopifyClient(
        shop_domain="s.myshopify.com",
        access_token="t",
        api_version="2026-07",
        transport=httpx.MockTransport(handler),
    )


def _order_line(order_id: str, codes=("HBA10",), created="2026-03-04T10:00:00Z") -> str:
    return json.dumps(
        {
            "id": f"gid://shopify/Order/{order_id}",
            "legacyResourceId": order_id,
            "name": f"#{order_id}",
            "createdAt": created,
            "updatedAt": created,
            "cancelledAt": None,
            "displayFinancialStatus": "PAID",
            "displayFulfillmentStatus": "FULFILLED",
            "discountCodes": list(codes),
            "currentSubtotalPriceSet": {
                "shopMoney": {"amount": "100.00", "currencyCode": "EGP"}
            },
            "currentTotalPriceSet": {
                "shopMoney": {"amount": "110.00", "currencyCode": "EGP"}
            },
            "totalShippingPriceSet": {
                "shopMoney": {"amount": "10.00", "currencyCode": "EGP"}
            },
            "currentTotalTaxSet": {
                "shopMoney": {"amount": "0.00", "currencyCode": "EGP"}
            },
        }
    )


# ── Starting and polling ───────────────────────────────────────────────────────


def test_starting_an_import_returns_the_operation_id():
    client = _client(
        [
            {
                "data": {
                    "bulkOperationRunQuery": {
                        "bulkOperation": {
                            "id": "gid://shopify/BulkOperation/1",
                            "status": "CREATED",
                        },
                        "userErrors": [],
                    }
                }
            }
        ]
    )
    assert start_bulk_import(client, since="2026-01-01") == (
        "gid://shopify/BulkOperation/1"
    )


def test_a_user_error_from_shopify_is_raised():
    """Shopify allows one bulk operation per shop at a time."""
    client = _client(
        [
            {
                "data": {
                    "bulkOperationRunQuery": {
                        "bulkOperation": None,
                        "userErrors": [
                            {"field": "query", "message": "already running"}
                        ],
                    }
                }
            }
        ]
    )
    with pytest.raises(ShopifyError, match="already running"):
        start_bulk_import(client, since="2026-01-01")


def test_a_response_with_no_operation_is_raised():
    client = _client(
        [{"data": {"bulkOperationRunQuery": {"bulkOperation": {}, "userErrors": []}}}]
    )
    with pytest.raises(ShopifyError):
        start_bulk_import(client, since="2026-01-01")


def test_polling_reports_status_and_url():
    client = _client(
        [
            {
                "data": {
                    "currentBulkOperation": {
                        "id": "gid://shopify/BulkOperation/1",
                        "status": "COMPLETED",
                        "objectCount": "412",
                        "url": "https://storage.example/bulk.jsonl",
                        "errorCode": None,
                    }
                }
            }
        ]
    )
    result = poll_bulk_operation(client)
    assert result["status"] == "COMPLETED"
    assert result["url"].endswith("bulk.jsonl")


def test_polling_when_nothing_has_ever_run_is_not_an_error():
    client = _client([{"data": {"currentBulkOperation": None}}])
    assert poll_bulk_operation(client) == {}


# ── Ingestion ──────────────────────────────────────────────────────────────────


def test_ingesting_jsonl_writes_every_order(db):
    lines = [_order_line("1"), _order_line("2"), _order_line("3")]
    assert ingest_jsonl(db, lines) == 3
    db.flush()
    assert db.query(OrderIndex).count() == 3


def test_blank_lines_are_skipped(db):
    assert ingest_jsonl(db, [_order_line("1"), "", "   ", _order_line("2")]) == 2


def test_non_order_lines_are_skipped(db):
    """A bulk file interleaves child objects; only orders belong here."""
    child = json.dumps(
        {"id": "gid://shopify/LineItem/9", "__parentId": "gid://shopify/Order/1"}
    )
    assert ingest_jsonl(db, [_order_line("1"), child]) == 1


def test_a_malformed_line_does_not_abort_the_whole_import(db):
    """One bad row must not discard thousands of good ones."""
    written = ingest_jsonl(db, [_order_line("1"), "{not json", _order_line("2")])
    db.flush()
    assert written == 2
    assert db.query(OrderIndex).count() == 2


def test_an_order_missing_required_fields_is_skipped_not_fatal(db):
    """Normalisation is guarded because it happens before any database write."""
    incomplete = json.dumps({"id": "gid://shopify/Order/5", "name": "#5"})
    assert ingest_jsonl(db, [_order_line("1"), incomplete]) == 1


def test_skipped_lines_are_reported(db, caplog):
    """Orders silently absent from an import is the failure being guarded."""
    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        ingest_jsonl(db, [_order_line("1"), "{not json"])

    assert Anomaly.IMPORT_LINE_SKIPPED in caplog.text
    assert "skipped=1" in caplog.text


def test_a_clean_import_reports_nothing(db, caplog):
    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        ingest_jsonl(db, [_order_line("1"), _order_line("2")])
    assert Anomaly.IMPORT_LINE_SKIPPED not in caplog.text


def test_re_ingesting_the_same_file_is_safe(db):
    """A retried import must not double anything."""
    lines = [_order_line("1"), _order_line("2")]
    ingest_jsonl(db, lines)
    db.flush()
    ingest_jsonl(db, lines)
    db.flush()
    assert db.query(OrderIndex).count() == 2


def test_business_months_are_assigned_during_import(db):
    """Two orders 90 minutes apart, either side of Cairo midnight."""
    ingest_jsonl(
        db,
        [
            _order_line("1", created="2026-08-31T20:00:00Z"),
            _order_line("2", created="2026-08-31T21:30:00Z"),
        ],
    )
    db.flush()
    months = sorted(row.business_month for row in db.query(OrderIndex).all())
    assert months == ["2026-08", "2026-09"]


# ── The handler that drives it ─────────────────────────────────────────────────


def _run_handler(db, payload, monkeypatch, *, client=None, operation=None, lines=None):
    from app.services.shopify import bulk
    from app.worker import HANDLERS

    monkeypatch.setattr(bulk, "build_client", lambda: client, raising=False)
    monkeypatch.setattr(
        "app.services.shopify.sync.build_client", lambda: client, raising=True
    )
    if operation is not None:
        monkeypatch.setattr(bulk, "poll_bulk_operation", lambda _c: operation)
    if lines is not None:
        monkeypatch.setattr(bulk, "download_jsonl", lambda url, **kw: iter(lines))
    monkeypatch.setattr(bulk, "start_bulk_import", lambda _c, since: "op-1")

    HANDLERS[JobKind.BULK_IMPORT](db, payload)


def _queued(db) -> list[tuple]:
    return db.execute(
        text("SELECT kind, payload FROM background_job ORDER BY id")
    ).all()


def test_the_first_step_starts_the_import_and_schedules_a_check(db, monkeypatch):
    _run_handler(db, {"since": "2026-01-01"}, monkeypatch, client=object())
    db.flush()

    queued = _queued(db)
    assert len(queued) == 1
    assert queued[0][0] == JobKind.BULK_IMPORT
    assert queued[0][1]["started"] is True


def test_a_running_operation_schedules_another_check(db, monkeypatch):
    _run_handler(
        db,
        {"since": "2026-01-01", "started": True, "polls": 3},
        monkeypatch,
        client=object(),
        operation={"status": "RUNNING"},
    )
    db.flush()

    queued = _queued(db)
    assert len(queued) == 1
    assert queued[0][1]["polls"] == 4, "the poll count must advance, or MAX_POLLS never bites"


def test_the_reschedule_is_not_absorbed_by_its_own_running_job(db, monkeypatch):
    """The trap this design exists to avoid.

    The job doing the rescheduling is itself `running`. Had the reschedule
    carried the kind as a dedupe key, it would collide with that row, be
    absorbed, and the import would stall forever - with every job succeeding
    and nothing reporting a failure.
    """
    from app.services.jobs import enqueue, lease_job

    enqueue(db, JobKind.BULK_IMPORT, {"since": "2026-01-01"}, dedupe_key=JobKind.BULK_IMPORT)
    db.flush()
    running = lease_job(db, worker_id="w")
    assert running is not None

    _run_handler(
        db,
        {"since": "2026-01-01", "started": True, "polls": 0},
        monkeypatch,
        client=object(),
        operation={"status": "RUNNING"},
    )
    db.flush()

    pending = db.execute(
        text("SELECT count(*) FROM background_job WHERE status = 'pending'")
    ).scalar()
    assert pending == 1, "the next step was swallowed; the import would stall silently"


def test_a_completed_operation_ingests_the_file(db, monkeypatch):
    _run_handler(
        db,
        {"since": "2026-01-01", "started": True},
        monkeypatch,
        client=object(),
        operation={"status": "COMPLETED", "url": "https://x/bulk.jsonl", "objectCount": "2"},
        lines=[_order_line("1"), _order_line("2")],
    )
    db.flush()

    assert db.query(OrderIndex).count() == 2
    assert _queued(db) == [], "ingestion is the last step; nothing more to schedule"


def test_a_completed_operation_with_no_file_matched_nothing(db, monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        _run_handler(
            db,
            {"since": "2026-01-01", "started": True},
            monkeypatch,
            client=object(),
            operation={"status": "COMPLETED", "url": None},
        )

    assert Anomaly.IMPORT_EMPTY in caplog.text
    assert db.query(OrderIndex).count() == 0


def test_a_failed_operation_gives_up_rather_than_retrying(db, monkeypatch):
    """CANCELED, FAILED and EXPIRED do not improve on a retry."""
    with pytest.raises(PermanentFailure, match="FAILED"):
        _run_handler(
            db,
            {"since": "2026-01-01", "started": True},
            monkeypatch,
            client=object(),
            operation={"status": "FAILED", "errorCode": "ACCESS_DENIED"},
        )


def test_an_operation_that_never_finishes_gives_up(db, monkeypatch):
    """Otherwise a stuck export reschedules itself for ever, quietly."""
    with pytest.raises(PermanentFailure, match="never finished"):
        _run_handler(
            db,
            {"since": "2026-01-01", "started": True, "polls": MAX_POLLS},
            monkeypatch,
            client=object(),
            operation={"status": "RUNNING"},
        )
