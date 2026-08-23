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
from app.services.jobs import JobKind, PermanentFailure, prune_succeeded_jobs
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


@register_handler(JobKind.PRUNE_JOBS)
def _handle_prune_jobs(db: Session, payload: dict) -> None:
    """Keep background_job from growing forever (docs/limits.md).

    Succeeded jobs only. A failed job is the record that work did not happen,
    and deleting it on a timer would erase exactly the evidence someone needs.
    """
    days = int(payload.get("older_than_days") or 30)
    removed = prune_succeeded_jobs(db, older_than_days=days)
    logger.info("pruned %s succeeded jobs older than %s days", removed, days)
