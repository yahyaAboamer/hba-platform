"""The reconciliation sweep, and the schedule that actually runs it.

Webhooks are not guaranteed. A periodic pass over recently updated orders
catches anything missed or delivered out of order - but only if something
triggers it, which is the half that is easy to leave out and impossible to
notice missing.
"""

import logging

import httpx
import pytest
from sqlalchemy import text

from app.core.signals import Anomaly
from app.models.orders import OrderIndex
from app.services.jobs import JobKind, JobStatus, PermanentFailure, enqueue, lease_job
from app.services.reconcile import MAX_PAGES, PAGE_SIZE, reconcile_recent
from app.services.schedule import SCHEDULE, ensure_scheduled
from app.services.shopify.client import ShopifyClient


def _node(order_id: str) -> dict:
    return {
        "id": f"gid://shopify/Order/{order_id}",
        "legacyResourceId": order_id,
        "name": f"#{order_id}",
        "createdAt": "2026-08-18T16:36:00Z",
        "updatedAt": "2026-08-18T16:36:00Z",
        "cancelledAt": None,
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "FULFILLED",
        "discountCodes": ["HBA10"],
        "currentSubtotalPriceSet": {
            "shopMoney": {"amount": "100.00", "currencyCode": "EGP"}
        },
        "currentTotalPriceSet": {
            "shopMoney": {"amount": "110.00", "currencyCode": "EGP"}
        },
        "totalShippingPriceSet": {
            "shopMoney": {"amount": "10.00", "currencyCode": "EGP"}
        },
        "currentTotalTaxSet": {"shopMoney": {"amount": "0.00", "currencyCode": "EGP"}},
    }


def _paged_client(pages, capture: list | None = None):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request.read().decode())
        page = pages[min(calls["n"], len(pages) - 1)]
        calls["n"] += 1
        return httpx.Response(200, json={"data": {"orders": page}})

    return ShopifyClient(
        shop_domain="s.myshopify.com",
        access_token="t",
        api_version="2026-07",
        transport=httpx.MockTransport(handler),
    )


def _page(nodes, *, more=False, cursor=None):
    return {
        "pageInfo": {"hasNextPage": more, "endCursor": cursor},
        "nodes": nodes,
    }


# ── The sweep ──────────────────────────────────────────────────────────────────


def test_recent_orders_are_indexed(db):
    client = _paged_client([_page([_node("1"), _node("2")])])
    assert reconcile_recent(db, client) == 2
    db.flush()
    assert db.query(OrderIndex).count() == 2


def test_every_page_is_followed(db):
    client = _paged_client(
        [
            _page([_node("1")], more=True, cursor="cursor-1"),
            _page([_node("2")]),
        ]
    )
    assert reconcile_recent(db, client) == 2


def test_the_cursor_is_carried_to_the_next_page(db):
    """Without this the sweep re-reads page one until MAX_PAGES."""
    capture: list = []
    client = _paged_client(
        [_page([_node("1")], more=True, cursor="cursor-1"), _page([_node("2")])],
        capture,
    )
    reconcile_recent(db, client)
    assert "cursor-1" in capture[1]


def test_an_order_already_present_is_updated_not_duplicated(db):
    client = _paged_client([_page([_node("1")])])
    reconcile_recent(db, client)
    db.flush()
    reconcile_recent(db, client)
    db.flush()
    assert db.query(OrderIndex).count() == 1


def test_an_empty_result_is_not_an_error(db):
    assert reconcile_recent(db, _paged_client([_page([])])) == 0


def test_the_window_is_sent_to_shopify(db):
    capture: list = []
    reconcile_recent(db, _paged_client([_page([])], capture), since_hours=48)
    assert "updated_at:>=" in capture[0]


# ── Stopping short ─────────────────────────────────────────────────────────────


def test_running_out_of_pages_is_reported(db, caplog):
    """Reaching the limit means the tail of the window went unread, which is
    the opposite of what a sweep is for - so it must not pass in silence.
    """
    client = _paged_client([_page([_node("1")], more=True, cursor="c")])

    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        seen = reconcile_recent(db, client)

    assert seen == MAX_PAGES * 1
    assert Anomaly.RECONCILE_TRUNCATED in caplog.text
    assert "page limit" in caplog.text


def test_a_missing_cursor_is_reported(db, caplog):
    """Shopify claiming another page but naming no cursor is a contradiction."""
    client = _paged_client([_page([_node("1")], more=True, cursor=None)])

    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        reconcile_recent(db, client)

    assert Anomaly.RECONCILE_TRUNCATED in caplog.text
    assert "no cursor" in caplog.text


def test_a_normal_sweep_reports_nothing(db, caplog):
    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        reconcile_recent(db, _paged_client([_page([_node("1")])]))
    assert Anomaly.RECONCILE_TRUNCATED not in caplog.text


def test_the_page_size_is_not_absurd():
    """A guard on the constants rather than the code: 200 pages of 50 bounds a
    sweep at 10,000 orders, which is far more than a 48-hour window holds.
    """
    assert PAGE_SIZE * MAX_PAGES >= 10_000


# ── Handlers ───────────────────────────────────────────────────────────────────


def test_reconciliation_without_credentials_fails_permanently(db, monkeypatch):
    from app.services.shopify.client import ShopifyNotConfigured
    from app.worker import HANDLERS

    def unconfigured():
        raise ShopifyNotConfigured("SHOPIFY_SHOP_DOMAIN is not set")

    monkeypatch.setattr("app.services.shopify.sync.build_client", unconfigured)

    with pytest.raises(PermanentFailure):
        HANDLERS[JobKind.RECONCILE](db, {})


def test_the_prune_handler_removes_old_succeeded_jobs(db):
    from app.services.jobs import complete_job
    from app.worker import HANDLERS

    enqueue(db, JobKind.SYNC_ORDER, {})
    db.flush()
    complete_job(db, lease_job(db, worker_id="w"))
    db.flush()
    db.execute(text("UPDATE background_job SET finished_at = now() - interval '40 days'"))

    HANDLERS[JobKind.PRUNE_JOBS](db, {"older_than_days": 30})
    db.flush()

    assert db.execute(text("SELECT count(*) FROM background_job")).scalar() == 0


# ── The schedule ───────────────────────────────────────────────────────────────


def test_recurring_work_is_queued_when_nothing_is_outstanding(db):
    """Without this, reconciliation never runs - and never running is silent."""
    assert ensure_scheduled(db) == len(SCHEDULE)
    db.flush()

    kinds = {
        row[0]
        for row in db.execute(text("SELECT kind FROM background_job")).all()
    }
    assert kinds == set(SCHEDULE)


def test_the_sweep_is_among_the_scheduled_work(db):
    """Names the one that matters, so a refactor cannot quietly drop it."""
    assert JobKind.RECONCILE in SCHEDULE
    assert JobKind.PRUNE_JOBS in SCHEDULE


def test_calling_it_again_queues_nothing(db):
    ensure_scheduled(db)
    db.flush()
    assert ensure_scheduled(db) == 0
    db.flush()
    assert db.execute(text("SELECT count(*) FROM background_job")).scalar() == len(
        SCHEDULE
    )


def test_a_running_job_still_counts_as_outstanding(db):
    """Otherwise every check queues another sweep while one is in progress."""
    ensure_scheduled(db)
    db.flush()
    db.execute(
        text("UPDATE background_job SET run_after = now() - interval '1 hour'")
    )
    assert lease_job(db, worker_id="w") is not None
    db.flush()

    assert ensure_scheduled(db) == 0


def test_a_finished_job_frees_the_slot_for_the_next_one(db):
    """The recurrence itself: one finishes, the next is queued."""
    from app.services.jobs import complete_job

    ensure_scheduled(db)
    db.flush()
    db.execute(
        text("UPDATE background_job SET run_after = now() - interval '1 hour'")
    )
    while (job := lease_job(db, worker_id="w")) is not None:
        complete_job(db, job)
        db.flush()

    assert ensure_scheduled(db) == len(SCHEDULE)


def test_scheduled_work_is_not_due_immediately(db):
    """A restart must not trigger a sweep, or a crash-loop becomes a storm."""
    ensure_scheduled(db)
    db.flush()
    assert lease_job(db, worker_id="w") is None


def test_scheduling_is_quiet_when_there_is_nothing_to_do(db, caplog):
    """Called on a timer for ever. If the absorbed path reported an anomaly,
    the log would fill with a signal that means nothing here.
    """
    ensure_scheduled(db)
    db.flush()

    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        ensure_scheduled(db)
        db.flush()

    assert Anomaly.WORK_DEDUPLICATED not in caplog.text


def test_every_scheduled_kind_has_a_handler():
    """A scheduled kind nothing can run fails every time, for ever."""
    import app.main  # noqa: F401 - registers the handlers
    from app.worker import HANDLERS

    assert set(SCHEDULE) <= set(HANDLERS)


def test_the_worker_tops_up_the_schedule(db):
    """The wiring: the schedule exists, and the worker is what consults it."""
    from app.worker import top_up_schedule

    assert top_up_schedule(db) == len(SCHEDULE)
    assert db.execute(
        text("SELECT count(*) FROM background_job WHERE status = :s"),
        {"s": JobStatus.PENDING},
    ).scalar() == len(SCHEDULE)
