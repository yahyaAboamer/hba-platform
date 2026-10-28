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
from app.shared.services.jobs import JobKind, PermanentFailure, enqueue, prune_succeeded_jobs
from app.shared.services.shopify.client import (
    ShopifyClient,
    ShopifyMissingScope,
    ShopifyNotConfigured,
)
from app.shared.services.shopify.normalise import normalise_order, upsert_order_index
from app.shared.services.shopify.queries import ORDERS_PAGE
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
    from app.shared.services.shopify.sync import build_client

    hours = int(payload.get("since_hours") or DEFAULT_WINDOW_HOURS)
    try:
        client = build_client()
    except (ShopifyNotConfigured, ShopifyMissingScope) as exc:
        raise PermanentFailure(f"Cannot reconcile orders: {exc}") from exc

    count = reconcile_recent(db, client, since_hours=hours)
    logger.info("reconciliation re-indexed %s orders from the last %sh", count, hours)

    _queue_matching(db, hours)
    _queue_confirmations(db)


def _queue_confirmations(db: Session) -> None:
    """Find recent orders with no WhatsApp confirmation on record (ADR 0059).

    A webhook queues an order's confirmation when it arrives. An order whose
    webhook was missed reaches the index only through this sweep, which never
    went through that path - and staging receives no webhooks at all. Queued,
    not run here, and deduped on one key like the matching above.

    Nothing is queued on a server that does not decide confirmations.
    """
    from app.modules.inbox.services.confirmations import enabled

    if not enabled():
        return
    enqueue(
        db,
        JobKind.INBOX_CONFIRM_SWEEP,
        {},
        dedupe_key=f"{JobKind.INBOX_CONFIRM_SWEEP}:sweep",
    )


def _queue_matching(db: Session, hours: int) -> None:
    """Match the window's parcels to models, the way the webhook does live.

    **The sweep never matched.** Only a webhook queued a match, and staging
    receives no webhooks - so on staging nothing had been matched since the
    one manual scan on 10 September, and a parcel that reaches production
    through the sweep rather than a webhook was never attached either.

    **Queued, not run here.** Matching reads the shipping phone, which is
    protected customer data, through its own query (`ORDERS_RECIPIENT_PAGE`);
    as its own job a refusal fails *that* job - visibly, under failed jobs,
    and retried - while the sweep's orders commit with the sweep, whole. Run
    inline it would need a commit half-way through this handler, which the
    worker's contract forbids.

    Deduped on one key, so a sweep that finds the previous window's match
    still queued joins it rather than stacking another.
    """
    since = (utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    enqueue(
        db,
        JobKind.SCAN_RECIPIENTS,
        {"since": since, "field": "updated_at"},
        dedupe_key=f"{JobKind.SCAN_RECIPIENTS}:sweep",
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

    from app.shared.models.orders import OrderIndex

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
