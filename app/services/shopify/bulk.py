"""Historical import via Shopify's Bulk Operations API.

Paginating a year of orders would be hundreds of requests against a cost-based
rate limit. A bulk operation runs server-side and produces one JSONL file,
which is faster and far gentler on the limit.

The file interleaves parent and child objects, so ingestion skips anything that
is not an order. **A malformed line is counted and skipped rather than
aborting** - one bad row must not discard thousands of good ones - but a
*database* rejection is never swallowed: in Postgres a failed statement poisons
the whole transaction, so continuing after one would silently fail every
remaining row.
"""

import json
import logging
from datetime import timedelta
from typing import Iterable, Iterator

import httpx
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.core.signals import Anomaly, report
from app.services.jobs import JobKind, PermanentFailure, enqueue
from app.services.shopify.client import (
    ShopifyClient,
    ShopifyError,
    ShopifyMissingScope,
    ShopifyNotConfigured,
)
from app.services.shopify.normalise import normalise_order, upsert_order_index
from app.services.shopify.queries import BULK_ORDER_FIELDS
from app.worker import register_handler

logger = logging.getLogger(__name__)

#: How long to wait before asking Shopify whether the export is ready. A year
#: of orders takes minutes, so polling faster would only burn rate limit.
POLL_INTERVAL_SECONDS = 30

#: A stop, so a stuck export cannot reschedule itself forever. At 30 seconds a
#: step this is roughly an hour - far longer than any real export.
MAX_POLLS = 120

DOWNLOAD_TIMEOUT_SECONDS = 300.0

BULK_RUN = """
mutation BulkImport($query: String!) {
  bulkOperationRunQuery(query: $query) {
    bulkOperation { id status }
    userErrors { field message }
  }
}
"""

BULK_STATUS = """
query {
  currentBulkOperation {
    id
    status
    objectCount
    url
    errorCode
  }
}
"""


def _orders_query(since: str) -> str:
    """The export document.

    `BULK_ORDER_FIELDS`, not `ORDER_FIELDS`: a bulk operation refuses a
    connection nested inside a list field, which is what `refundLineItems`
    inside `refunds` is. Shopify rejects the **whole document** for it, so the
    import failed outright every time it was started - queued, retried five
    times, and gave up, with the screen reporting only that it had begun.
    """
    return f"""
    {{
      orders(query: "created_at:>={since}") {{
        edges {{
          node {{
            {BULK_ORDER_FIELDS}
          }}
        }}
      }}
    }}
    """


def start_bulk_import(client: ShopifyClient, since: str) -> str:
    """Ask Shopify to start building the export. Returns the operation id."""
    data = client.execute(BULK_RUN, {"query": _orders_query(since)})
    result = data.get("bulkOperationRunQuery") or {}

    errors = result.get("userErrors") or []
    if errors:
        messages = "; ".join(str(item.get("message", "")) for item in errors)
        raise ShopifyError(f"Shopify refused the bulk operation: {messages}")

    operation_id = (result.get("bulkOperation") or {}).get("id")
    if not operation_id:
        raise ShopifyError("Shopify returned no bulk operation")
    return operation_id


def poll_bulk_operation(client: ShopifyClient) -> dict:
    """Current status of the running or most recent bulk operation."""
    data = client.execute(BULK_STATUS, {})
    return data.get("currentBulkOperation") or {}


def download_jsonl(url: str, timeout_seconds: float = DOWNLOAD_TIMEOUT_SECONDS) -> Iterator[str]:
    """Stream the export rather than loading it all into memory."""
    with httpx.stream("GET", url, timeout=timeout_seconds) as response:
        response.raise_for_status()
        yield from response.iter_lines()


def ingest_jsonl(db: Session, lines: Iterable[str]) -> int:
    """Write every order line to the index. Returns how many were written.

    Skips blank lines, child objects, non-orders, and lines this code cannot
    make sense of. **Does not skip database errors** - see the module docstring.
    """
    written = 0
    skipped = 0

    for line in lines:
        text_line = (line or "").strip()
        if not text_line:
            continue

        try:
            node = json.loads(text_line)
        except ValueError:
            skipped += 1
            continue

        # The export interleaves child objects; they carry __parentId.
        if not isinstance(node, dict) or node.get("__parentId"):
            continue
        if not str(node.get("id", "")).startswith("gid://shopify/Order/"):
            continue

        # Normalisation is guarded; the write is not. A row Postgres rejects
        # aborts the transaction, and carrying on would fail every row after it
        # while reporting success.
        try:
            values = normalise_order(node)
        except (ValueError, TypeError):
            skipped += 1
            continue

        upsert_order_index(db, values)
        written += 1

    if skipped:
        report(Anomaly.IMPORT_LINE_SKIPPED, skipped=skipped, written=written)

    return written


@register_handler(JobKind.BULK_IMPORT)
def _handle_bulk_import(db: Session, payload: dict) -> None:
    """Run one step of the import, rescheduling itself while Shopify works.

    A bulk export of a year of orders takes minutes. Holding a worker for that
    long would block every other job, so each run does one thing: start the
    operation, check on it, or ingest the finished file.

    **The reschedule deliberately carries no dedupe key.** The job doing the
    rescheduling is still `running`, so a key would collide with its own row,
    the next step would be silently absorbed, and the import would stall
    forever with nothing reporting a failure.

    It does not need one. The enqueue commits in the same transaction as the
    job's success, so a step either completes and schedules exactly one
    successor, or fails and is retried whole.
    """
    from app.services.shopify.sync import build_client

    since = str(payload.get("since") or "2026-01-01")
    polls = int(payload.get("polls") or 0)

    try:
        client = build_client()
    except (ShopifyNotConfigured, ShopifyMissingScope) as exc:
        raise PermanentFailure(f"Cannot import orders: {exc}") from exc

    def schedule_next(**extra) -> None:
        enqueue(
            db,
            JobKind.BULK_IMPORT,
            {"since": since, "started": True, **extra},
            run_after=utcnow() + timedelta(seconds=POLL_INTERVAL_SECONDS),
        )

    if not payload.get("started"):
        start_bulk_import(client, since)
        logger.info("bulk import started for orders created since %s", since)
        schedule_next(polls=0)
        return

    if polls >= MAX_POLLS:
        raise PermanentFailure(
            f"Bulk import for {since} never finished after {MAX_POLLS} checks. "
            "Look at the operation in the Shopify admin before starting another."
        )

    operation = poll_bulk_operation(client)
    status = str(operation.get("status") or "").upper()

    if status in {"CREATED", "RUNNING"}:
        schedule_next(polls=polls + 1)
        return

    if status != "COMPLETED":
        # CANCELED, FAILED, EXPIRED. Retrying the poll will not change it.
        raise PermanentFailure(
            f"Bulk operation ended as {status or 'UNKNOWN'}: "
            f"{operation.get('errorCode') or 'no error code'}"
        )

    url = operation.get("url")
    if not url:
        # COMPLETED with no url means the query matched nothing at all.
        report(Anomaly.IMPORT_EMPTY, since=since)
        return

    written = ingest_jsonl(db, download_jsonl(url))
    logger.info(
        "bulk import indexed %s orders created since %s (Shopify counted %s objects)",
        written,
        since,
        operation.get("objectCount"),
    )
