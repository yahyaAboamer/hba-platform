"""Reconciliation sweep.

Webhook delivery is best-effort. Shopify can drop one, deliver two out of
order, or deliver during a deploy when nothing is listening. A periodic pass
over recently updated orders closes that gap.

**This is what makes order data complete; webhooks only make it prompt.** If
deliveries stopped entirely and nobody noticed, orders would still arrive -
late, in batches, rather than never. Building on the assumption that every
webhook arrives is how one missed delivery becomes a missing month of
commission.

Re-reading an order the platform already has costs one write and nothing else,
because indexing is idempotent.
"""

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.core.signals import Anomaly, report
from app.services.jobs import JobKind, PermanentFailure, enqueue, prune_succeeded_jobs
from app.services.shopify.client import (
    ShopifyClient,
    ShopifyMissingScope,
    ShopifyNotConfigured,
)
from app.services.shopify.normalise import normalise_order, upsert_order_index
from app.services.shopify.queries import ORDERS_PAGE
from app.worker import register_handler

logger = logging.getLogger(__name__)

PAGE_SIZE = 50

#: A stop, so a pagination bug cannot loop forever. 200 pages of 50 is 10,000
#: orders - far more than a 48-hour window can hold at this shop's volume, so
#: reaching it means something is wrong rather than busy.
MAX_PAGES = 200

DEFAULT_WINDOW_HOURS = 48


def reconcile_recent(
    db: Session, client: ShopifyClient, since_hours: int = DEFAULT_WINDOW_HOURS
) -> int:
    """Re-index every order updated in the window. Returns how many."""
    since = (utcnow() - timedelta(hours=since_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    query = f"updated_at:>={since}"

    cursor: str | None = None
    seen = 0

    for _page in range(MAX_PAGES):
        data = client.execute(
            ORDERS_PAGE, {"first": PAGE_SIZE, "after": cursor, "query": query}
        )
        orders = data.get("orders") or {}

        for node in orders.get("nodes") or []:
            upsert_order_index(db, normalise_order(node))
            seen += 1

        page_info = orders.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            # hasNextPage without a cursor is Shopify contradicting itself.
            # Stopping is safe - the next sweep covers the same window - but it
            # means the tail of this window went unread.
            report(Anomaly.RECONCILE_TRUNCATED, reason="no cursor", seen=seen)
            break
    else:
        # Ran out of pages rather than out of orders.
        report(Anomaly.RECONCILE_TRUNCATED, reason="page limit", seen=seen)

    return seen


@register_handler(JobKind.RECONCILE)
def _handle_reconcile(db: Session, payload: dict) -> None:
    from app.services.shopify.sync import build_client

    hours = int(payload.get("since_hours") or DEFAULT_WINDOW_HOURS)
    try:
        client = build_client()
    except (ShopifyNotConfigured, ShopifyMissingScope) as exc:
        raise PermanentFailure(f"Cannot reconcile orders: {exc}") from exc

    count = reconcile_recent(db, client, since_hours=hours)
    logger.info("reconciliation re-indexed %s orders from the last %sh", count, hours)

    # The index is kept before anything else is tried: what follows reads a
    # protected field, and its refusal must cost the parcels, never the orders.
    db.commit()
    _match_recent(db, client, hours)


def _match_recent(db: Session, client: ShopifyClient, hours: int) -> None:
    """Match the window's parcels to models, the way the webhook does live.

    **The sweep never matched.** Only a webhook queued a match, and staging
    receives no webhooks - so on staging nothing had been matched since the
    one manual scan on 10 September, and a parcel that reaches production
    through the sweep rather than a webhook was never attached either.

    Its own query (`ORDERS_RECIPIENT_PAGE`), not fields added to the sweep's,
    for the reason 03A set: the shipping phone is protected customer data, and
    a refusal of it must not stop orders being indexed. Hence also the guard -
    a failure here is reported and the sweep still succeeds.
    """
    from app.services.recipients import scan_recipients

    since = (utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        result = scan_recipients(
            db, client, since=since, field="updated_at", pages_per_run=MAX_PAGES
        )
    except Exception as exc:  # noqa: BLE001 - the parcels, never the orders
        db.rollback()
        report(Anomaly.RECIPIENT_SCAN_FAILED, reason=type(exc).__name__)
        logger.warning("recipient matching after the sweep failed: %s", exc)
        return
    logger.info(
        "recipient matching after the sweep: %s seen, %s matched",
        result["seen"],
        result["matched"],
    )


#: How many undelivered orders one resync run queues. Each is one ordinary
#: per-order read; a thousand stuck orders clear in a single run.
RESYNC_BATCH = 2000


def orders_to_resync(db: Session, *, limit: int = RESYNC_BATCH) -> list[str]:
    """Orders the platform holds as undelivered, oldest sync first.

    The sweep re-reads only what Shopify changed in the last two days, so an
    order stuck in flight - by a rule since corrected (ADR 0051), or by a
    courier that stopped reporting - is never read again. Everything not yet
    delivered or failed is re-read on this slower schedule, which is also what
    fills `fulfilments` and `paid_by_delivery_piastres` on orders indexed
    before they were asked for.
    """
    from sqlalchemy import select

    from app.models.orders import OrderIndex

    return list(
        db.scalars(
            select(OrderIndex.shopify_order_id)
            .where(OrderIndex.fulfillment_status.is_not(None))
            .where(
                OrderIndex.delivery_state.is_(None)
                | OrderIndex.delivery_state.not_in(["delivered", "failed"])
            )
            .order_by(OrderIndex.last_synced_at.asc().nulls_first())
            .limit(limit)
        )
    )


@register_handler(JobKind.RESYNC_IN_FLIGHT)
def _handle_resync_in_flight(db: Session, payload: dict) -> None:
    """Queue a fresh read of every undelivered order. ADR 0051.

    Only queues: each read is an ordinary `SYNC_ORDER`, deduped on the key the
    webhook uses, so an order a webhook already queued is not read twice. That
    read re-derives delivery under the current rules, re-attributes, and
    re-matches the parcel - the whole path, not a special one.
    """
    limit = int(payload.get("limit") or RESYNC_BATCH)
    for order_id in orders_to_resync(db, limit=limit):
        enqueue(
            db,
            JobKind.SYNC_ORDER,
            {"order_id": order_id},
            dedupe_key=f"{JobKind.SYNC_ORDER}:{order_id}",
        )


@register_handler(JobKind.PRUNE_JOBS)
def _handle_prune_jobs(db: Session, payload: dict) -> None:
    """Keep background_job from growing forever (docs/limits.md).

    Succeeded jobs only. A failed job is the record that work did not happen,
    and deleting it on a timer would erase exactly the evidence someone needs.
    """
    days = int(payload.get("older_than_days") or 30)
    removed = prune_succeeded_jobs(db, older_than_days=days)
    logger.info("pruned %s succeeded jobs older than %s days", removed, days)
