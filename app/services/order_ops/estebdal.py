"""The E-stebdal tab: return and exchange requests waiting for review (ADR 0057).

E-stebdal gives a request the status "Needs Review" when the customer
submits it, and it keeps that status until somebody approves or rejects it.
Every 5 minutes those requests are read and replace ``ops_estebdal_return``.

**What is kept is four fields.** E-stebdal's answer carries the customer's
name, phone and address, the items, photos and money; Operations stores the
request's id, its number, the order's number and when it was requested, and
reads nothing else out of the response.

Checked read-only from staging on 6 October 2026: the key goes in an
``x-api-key`` header; the list pages by ``page`` with ``meta.hasNextPage``;
the limit is 200 requests a minute. A wrong key is answered with a 500, not
a 401, so a refused key and an outage look the same from here.
"""

import json
import logging
import time
from datetime import datetime

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.businesstime import utcnow
from app.models.order_ops import OpsEstebdalReturn
from app.services.jobs import JobKind
from app.services.order_ops.polling import KeyRefused, NotConnected, SourceUnavailable, run_poll
from app.services.order_ops.shopify import waiting_days
from app.worker import register_handler

logger = logging.getLogger(__name__)

BASE_URL = "https://api.e-stebdal.com/api/v1/public"

NEEDS_REVIEW = "Needs Review"

#: E-stebdal's own filter syntax, as its dashboard sends it.
FILTER = json.dumps([{"field": "status", "operator": "isAnyOf", "value": [NEEDS_REVIEW]}])

PAGE_SIZE = 250
#: Far more pages than requests ever wait; a bound on trusting a cursor.
MAX_PAGES = 20
MAX_ATTEMPTS = 3

DIDNT_ANSWER = "E-stebdal didn't answer."


class EstebdalClient:
    """Reads E-stebdal's returns list. Never writes."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not api_key:
            raise NotConnected
        self._api_key = api_key
        self._transport = transport
        self._timeout = timeout_seconds
        self.retry_base_seconds = 1.0

    def __repr__(self) -> str:
        return "<EstebdalClient>"  # never the key

    def _get(self, path: str, params: dict) -> dict:
        with httpx.Client(transport=self._transport, timeout=self._timeout) as http:
            for attempt in range(MAX_ATTEMPTS):
                if attempt:
                    time.sleep(self.retry_base_seconds * (2 ** (attempt - 1)))
                try:
                    response = http.get(
                        f"{BASE_URL}{path}", params=params, headers={"x-api-key": self._api_key}
                    )
                except httpx.HTTPError:
                    continue
                if response.status_code in (401, 403):
                    raise KeyRefused("E-stebdal refused the key.")
                # 429 is the 200-a-minute limit; 5xx includes a wrong key.
                if response.status_code == 429 or response.status_code >= 500:
                    continue
                if response.status_code >= 400:
                    raise SourceUnavailable(DIDNT_ANSWER)
                try:
                    return response.json()
                except ValueError:
                    raise SourceUnavailable(DIDNT_ANSWER) from None
        raise SourceUnavailable(DIDNT_ANSWER)

    def needs_review(self) -> list[dict]:
        """Every request waiting for review, reduced to the fields kept."""
        kept: dict[str, dict] = {}
        for page in range(1, MAX_PAGES + 1):
            body = self._get("/returns", {"filter": FILTER, "limit": PAGE_SIZE, "page": page})
            try:
                meta = body["meta"]
                items = body["data"]
                # Its own filter already chose these. A page whose every item
                # says otherwise means the answer changed shape, and dropping
                # them all would show a 0 for requests that are waiting.
                if items and not any(item.get("status") == NEEDS_REVIEW for item in items):
                    raise ValueError("no item carries the status asked for")
                for item in items:
                    if item.get("status") != NEEDS_REVIEW:
                        continue
                    # By id: a request that moves between pages mid-read is one.
                    kept[str(item["id"])] = {
                        "id": str(item["id"]),
                        "return_number": str(item["returnNumber"]),
                        "order_number": item.get("orderNumber"),
                        "requested_at": _parse_time(item.get("date") or item["createdAt"]),
                    }
                more = bool(meta["hasNextPage"])
            except (KeyError, TypeError, ValueError):
                raise SourceUnavailable(
                    "E-stebdal answered in a way Operations doesn't recognise."
                ) from None
            if not more:
                return list(kept.values())
        raise SourceUnavailable("E-stebdal returned more requests than Operations reads.")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def read(db: Session, client: EstebdalClient | None = None) -> int:
    """Replace the snapshot with what waits for review now. Returns how many."""
    client = client or EstebdalClient(settings.estebdal_api_key)
    requests = client.needs_review()

    seen = utcnow()
    db.execute(delete(OpsEstebdalReturn))
    db.add_all(
        OpsEstebdalReturn(
            estebdal_id=request["id"],
            return_number=request["return_number"],
            order_number=request["order_number"],
            requested_at=request["requested_at"],
            seen_at=seen,
        )
        for request in requests
    )
    db.flush()
    logger.info("order-ops estebdal: %d requests need review", len(requests))
    return len(requests)


@register_handler(JobKind.ORDER_OPS_ESTEBDAL)
def _handle_read(db: Session, payload: dict) -> None:
    run_poll(db, "estebdal", read)


# ── The tab ───────────────────────────────────────────────────────────────────


def home_url(shop_domain: str | None) -> str | None:
    """E-stebdal's dashboard, which lives inside Shopify admin as an app.

    E-stebdal publishes no address for a single request, so every request
    opens the dashboard, where its number finds it.
    """
    domain = (shop_domain or "").strip().removeprefix("https://").rstrip("/")
    return f"https://{domain}/admin/apps/e-stebdal" if domain else None


def tab(db: Session, shop_domain: str | None, now: datetime | None = None) -> dict:
    """E1, Needs review, and the requests behind it, newest first."""
    now = now or utcnow()
    rows = db.scalars(
        select(OpsEstebdalReturn).order_by(OpsEstebdalReturn.requested_at.desc())
    ).all()
    url = home_url(shop_domain)
    requests = [
        {
            "return_number": row.return_number,
            "order_number": row.order_number,
            "requested_at": row.requested_at.isoformat(),
            "waiting_days": waiting_days(row.requested_at, now),
            "url": url,
        }
        for row in rows
    ]
    return {
        "total": len(rows),
        "cards": [{"key": "needs_review", "count": len(rows), "requests": requests}],
    }
