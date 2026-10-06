"""The Bosta tab: what is stuck between HBA and its customers (ADR 0057).

**Bosta is a source for operations only.** Nothing here decides whether an
order counts as delivered for pay; that stays Shopify's answer (ADR 0023).

Bosta holds every order HBA ever sent it, and the success rate needs months
of them, so this keeps a mirror (``ops_bosta_delivery``) rather than a
snapshot. Each read, every 5 minutes, in the operations lane:

1. **The unfinished set**, whole - about 165 orders, one page. A mirrored
   order still marked unfinished that is no longer in it has finished or
   been deleted on Bosta: it is read again by its tracking number, which
   records its last state, or marks it gone. That is also what keeps an
   order deleted on Bosta from lingering on "New, not shipped".
2. **What changed**, newest first, down to just below the last read's
   newest change.
3. **History**, a few days per read, backwards from the first day the
   mirror ran to 1 January 2026, so the most recent ranges are whole first.
   Until it is done, the pickups and the success rate say how far back the
   mirror has read rather than showing a number that may be short.

Checked read-only from staging on 6 October 2026: a bare ``Authorization``
header; ``POST /deliveries/search`` takes ``stateCodes`` as **strings**,
``limit`` up to 200, ``page``, ``sortBy`` and creation-date bounds, and its
``count`` is always 0, so pages are read until one comes back short; a wrong
key is a 401; an unknown tracking number is a 400.

**No customer details.** Bosta's answer carries the receiver's name, phone
and address, notes, the cash to collect and more. Only the fields in
``_parse`` are read out of it, and nothing else is kept or logged.
"""

import logging
import time
from datetime import date, datetime, time as clock, timedelta, timezone

import httpx
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.core.businesstime import BUSINESS_TIMEZONE, business_date, utcnow, working_days_since
from app.models.order_ops import OpsBostaDelivery, OpsBostaSync
from app.services.jobs import JobKind
from app.services.order_ops.polling import KeyRefused, NotConnected, SourceUnavailable, run_poll
from app.worker import register_handler

logger = logging.getLogger(__name__)

BASE_URL = "https://app.bosta.co/api/v2"

#: Where a person opens one order. Bosta publishes no such address; this is
#: its business dashboard's own (owner to confirm).
ORDER_URL = "https://business.bosta.co/orders/{tracking}"

#: The mirror reads back to here; the success rate is not offered before it.
HISTORY_START = date(2026, 1, 1)

#: Bosta's states for an order still on its way somewhere (PRD appendix B):
#: everything but delivered, returned, terminated, cancelled, returned to
#: stock, lost, damaged and archived.
UNFINISHED = frozenset({10, 11, 20, 21, 22, 23, 24, 25, 30, 40, 41, 47, 102, 103, 105})
PICKUP_REQUESTED = 10

PAGE_SIZE = 200
#: Bounds on trusting another system's paging. Each is far above what one
#: read sees (the unfinished set is one page; a day of orders is one).
MAX_PAGES = 10
MAX_CHANGED_PAGES = 10
#: Orders read again by tracking number in one read.
MAX_REREAD = 100
#: Days of history per read: about 28 reads, 2.5 hours, to reach January.
HISTORY_DAYS_PER_READ = 10
#: Changes are read down to this far below the last newest, so an order
#: updated twice in one instant is not missed.
OVERLAP = timedelta(minutes=15)
MAX_ATTEMPTS = 3
#: A batch this size with not one order readable is Bosta changing shape,
#: not one odd order.
SHAPE_CHANGED_AT = 3

DIDNT_ANSWER = "Bosta didn't answer."
UNRECOGNISED = "Bosta answered in a way Operations doesn't recognise."


class BostaClient:
    """Reads Bosta's orders. Never writes. Wants a read-only key."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key:
            raise NotConnected
        self._api_key = api_key
        self._http = httpx.Client(transport=transport, timeout=timeout_seconds)
        self.retry_base_seconds = 1.0

    def __repr__(self) -> str:
        return "<BostaClient>"  # never the key

    def close(self) -> None:
        self._http.close()

    def _send(self, method: str, path: str, body: dict | None = None) -> httpx.Response:
        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                time.sleep(self.retry_base_seconds * (2 ** (attempt - 1)))
            try:
                response = self._http.request(
                    method,
                    f"{BASE_URL}{path}",
                    json=body,
                    headers={"Authorization": self._api_key},
                )
            except httpx.HTTPError:
                continue
            if response.status_code in (401, 403):
                raise KeyRefused("Bosta refused the key.")
            if response.status_code == 429 or response.status_code >= 500:
                continue
            return response
        raise SourceUnavailable(DIDNT_ANSWER)

    def search(self, page: int, **filters) -> list[dict]:
        body = {"limit": PAGE_SIZE, "page": page, **filters}
        response = self._send("POST", "/deliveries/search", body)
        if response.status_code != 200:
            raise SourceUnavailable("Bosta didn't accept Operations' search.")
        try:
            return list(response.json()["data"]["deliveries"])
        except (KeyError, TypeError, ValueError):
            raise SourceUnavailable(UNRECOGNISED) from None

    def search_all(self, **filters) -> list[dict]:
        """Every page of a search. Bosta's ``count`` is always 0, so pages are
        read until one comes back short."""
        found: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            items = self.search(page, **filters)
            found.extend(items)
            if len(items) < PAGE_SIZE:
                return found
        raise SourceUnavailable("Bosta returned more orders than Operations reads.")

    def delivery(self, tracking_number: str) -> dict | None:
        """One order, or None if Bosta no longer has it (it answers 400)."""
        response = self._send("GET", f"/deliveries/business/{tracking_number}")
        if response.status_code in (400, 404):
            return None
        if response.status_code != 200:
            raise SourceUnavailable(DIDNT_ANSWER)
        try:
            return response.json()["data"]
        except (KeyError, TypeError, ValueError):
            raise SourceUnavailable(UNRECOGNISED) from None


# ── Bosta's answer, reduced to what is kept ───────────────────────────────────


def _iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _js_time(value: str | None) -> datetime | None:
    """``updatedAt`` comes as JavaScript prints a date:
    "Tue Oct 06 2026 19:30:24 GMT+0000 (Coordinated Universal Time)"."""
    if not value:
        return None
    try:
        return datetime.strptime(value.split(" (")[0], "%a %b %d %Y %H:%M:%S GMT%z")
    except ValueError:
        return _iso(value)


def _order_number(reference: str | None) -> str | None:
    """"<store>:#31038" -> "#31038"."""
    if not reference:
        return None
    tail = reference.rsplit(":", 1)[-1].strip()
    return tail[:60] if tail.startswith("#") else None


def _parse(item: dict, now: datetime) -> dict:
    """The fields kept, and only those."""
    try:
        state = item["state"]
        code = int(state["code"])
        status = state.get("value")
        return {
            "bosta_id": str(item["_id"]),
            "tracking_number": str(item["trackingNumber"]),
            "type_value": str(item["type"]["value"])[:60],
            "state_code": code,
            "state_value": str(status)[:80] if status else None,
            "created_at": datetime.fromtimestamp(
                int(item["creationTimestamp"]) / 1000, timezone.utc
            ),
            "updated_at_bosta": _js_time(item.get("updatedAt")),
            "collected_at": _iso(item.get("collectedFromBusiness")),
            "awb_printed_at": _iso(item.get("latestAWBPrintDate")),
            "waiting_for_action": bool(state.get("waitingForBusinessAction")),
            "shopify_order_number": _order_number(item.get("businessReference")),
            "unfinished": code in UNFINISHED,
            "deleted_at": None,
            "synced_at": now,
        }
    except (KeyError, TypeError, ValueError):
        raise SourceUnavailable(UNRECOGNISED) from None


def _upsert(db: Session, items: list[dict], now: datetime) -> list[dict]:
    """Insert or rewrite these orders. One order twice in a batch (it moved
    between pages mid-read) is written once.

    One order that does not read is skipped, so it cannot stop every read;
    a batch of several where none does means Bosta's answer changed shape,
    and that is a failure, never a quiet 0.
    """
    parsed: dict[str, dict] = {}
    skipped = 0
    for item in items:
        try:
            row = _parse(item, now)
        except SourceUnavailable:
            skipped += 1
            continue
        parsed[row["bosta_id"]] = row
    if len(items) >= SHAPE_CHANGED_AT and not parsed:
        raise SourceUnavailable(UNRECOGNISED)
    if skipped:
        logger.warning("order-ops bosta: %d orders could not be read and were skipped", skipped)
    rows = list(parsed.values())
    if rows:
        statement = insert(OpsBostaDelivery).values(rows)
        db.execute(
            statement.on_conflict_do_update(
                index_elements=[OpsBostaDelivery.bosta_id],
                set_={column: statement.excluded[column] for column in rows[0] if column != "bosta_id"},
            )
        )
    return rows


def _held(db: Session) -> int:
    return db.scalar(
        select(func.count())
        .select_from(OpsBostaDelivery)
        .where(OpsBostaDelivery.deleted_at.is_(None))
    )


# ── The read ──────────────────────────────────────────────────────────────────


def read(db: Session, client: BostaClient | None = None, now: datetime | None = None) -> int:
    """Bring the mirror up to date. Returns how many orders it holds."""
    owned = client is None
    client = client or BostaClient(settings.bosta_api_key)
    now = now or utcnow()
    try:
        sync = db.get(OpsBostaSync, 1)
        if sync is None:
            sync = OpsBostaSync(id=1, backfill_next=business_date(now), high_water=None)
            db.add(sync)

        # 1. The unfinished set, and whatever has left it since.
        current = _upsert(
            db, client.search_all(stateCodes=[str(code) for code in sorted(UNFINISHED)]), now
        )
        still = {row["bosta_id"] for row in current}
        left = db.scalars(
            select(OpsBostaDelivery)
            .where(
                OpsBostaDelivery.unfinished.is_(True),
                OpsBostaDelivery.deleted_at.is_(None),
                OpsBostaDelivery.bosta_id.not_in(still) if still else true(),
            )
            .order_by(OpsBostaDelivery.synced_at)
            .limit(MAX_REREAD)
        ).all()
        for row in left:
            try:
                found = client.delivery(row.tracking_number)
            except KeyRefused:
                raise
            except SourceUnavailable:
                found = False
            if found is None:
                row.deleted_at = now
            elif found is False or not _upsert(db, [found], now):
                # One order Bosta will not give back must not stop every read:
                # it goes to the back of the queue and is asked again later.
                row.synced_at = now
                logger.warning("order-ops bosta: one order could not be read again")

        # 2. What changed since the last read.
        if sync.high_water is None:
            sync.high_water = now  # history (3) covers everything before
        else:
            floor = sync.high_water - OVERLAP
            newest = sync.high_water
            for page in range(1, MAX_CHANGED_PAGES + 1):
                rows = _upsert(db, client.search(page, sortBy="-updatedAt"), now)
                stamps = [row["updated_at_bosta"] for row in rows if row["updated_at_bosta"]]
                newest = max([newest, *stamps])
                if len(rows) < PAGE_SIZE or (stamps and min(stamps) < floor):
                    break
            else:
                # More changed than one read takes (a long outage). What lies
                # deeper cannot be reached by this walk, so history is read
                # again from today: every order's state is refreshed, and until
                # then the tab says how far back it has read.
                logger.warning("order-ops bosta: more changes than one read takes; rereading history")
                sync.backfill_next = business_date(now)
            sync.high_water = newest

        # 3. History, backwards, a few days at a time.
        for _ in range(HISTORY_DAYS_PER_READ):
            day = sync.backfill_next
            if day is None:
                break
            _upsert(
                db,
                client.search_all(createdAtStart=day.isoformat(), createdAtEnd=day.isoformat()),
                now,
            )
            before = day - timedelta(days=1)
            sync.backfill_next = before if before >= HISTORY_START else None
    finally:
        if owned:
            client.close()

    db.flush()
    held = _held(db)
    logger.info("order-ops bosta: %d orders mirrored", held)
    return held


@register_handler(JobKind.ORDER_OPS_BOSTA)
def _handle_read(db: Session, payload: dict) -> None:
    run_poll(db, "bosta", read)


# ── History: how far back the mirror is whole ─────────────────────────────────


def read_back_to(db: Session) -> date | None:
    """The earliest creation day the mirror holds whole, or None if it has
    not read yet. Every day from then to now is held.

    One day after the last day read, not the day itself: Bosta's day bounds
    may be UTC days, which start three hours after Cairo's, so the last day
    read may be missing its first hours.
    """
    sync = db.get(OpsBostaSync, 1)
    if sync is None:
        return None
    if sync.backfill_next is None:
        return HISTORY_START
    return sync.backfill_next + timedelta(days=2)


def _cairo_midnight(day: date) -> datetime:
    return datetime.combine(day, clock(0), tzinfo=BUSINESS_TIMEZONE)


# ── The tab ───────────────────────────────────────────────────────────────────

#: An order can be collected long after it was created, so the pickups are
#: whole only once history reaches this far before the first day shown.
PICKUP_LOOKBACK = timedelta(days=60)

#: The types with an airway bill HBA prints.
PRINTABLE = frozenset({"Send", "Exchange"})


def _order(row: OpsBostaDelivery, waiting: int | None) -> dict:
    return {
        "tracking_number": row.tracking_number,
        "shopify_order_number": row.shopify_order_number,
        "type": row.type_value,
        "status": row.state_value,
        "created_at": row.created_at.isoformat(),
        "collected_at": row.collected_at.isoformat() if row.collected_at else None,
        "awb_printed_at": row.awb_printed_at.isoformat() if row.awb_printed_at else None,
        "waiting_working_days": waiting,
        "url": ORDER_URL.format(tracking=row.tracking_number),
    }


def tab(db: Session, now: datetime | None = None) -> dict:
    """B1, B2, B5 and B6 with their orders, and B3, the last 7 days of pickups."""
    now = now or utcnow()
    today = business_date(now)
    first_day = today - timedelta(days=6)

    unfinished = db.scalars(
        select(OpsBostaDelivery).where(
            OpsBostaDelivery.unfinished.is_(True), OpsBostaDelivery.deleted_at.is_(None)
        )
    ).all()

    def since_created(row: OpsBostaDelivery) -> int:
        return working_days_since(row.created_at, now)

    def since_collected(row: OpsBostaDelivery) -> int:
        return working_days_since(row.collected_at, now)

    new = sorted(
        (r for r in unfinished if r.state_code == PICKUP_REQUESTED and since_created(r) > 2),
        key=lambda r: r.created_at,
    )
    not_printed = sorted(
        (
            r
            for r in unfinished
            if r.collected_at is None and r.type_value in PRINTABLE and r.awb_printed_at is None
        ),
        key=lambda r: r.created_at,
    )
    awaiting = sorted((r for r in unfinished if r.waiting_for_action), key=lambda r: r.created_at)
    late = sorted(
        (r for r in unfinished if r.collected_at is not None and since_collected(r) > 3),
        key=lambda r: r.collected_at,
    )

    cards = [
        {"key": "new_not_shipped", "orders": [_order(r, since_created(r)) for r in new]},
        {"key": "not_printed", "orders": [_order(r, since_created(r)) for r in not_printed]},
        {"key": "awaiting_action", "orders": [_order(r, since_created(r)) for r in awaiting]},
        {"key": "shipped_not_delivered", "orders": [_order(r, since_collected(r)) for r in late]},
    ]
    for card in cards:
        card["count"] = len(card["orders"])

    collected = db.scalars(
        select(OpsBostaDelivery)
        .where(
            OpsBostaDelivery.deleted_at.is_(None),
            OpsBostaDelivery.collected_at >= _cairo_midnight(first_day),
        )
        .order_by(OpsBostaDelivery.collected_at.desc())
    ).all()
    by_day: dict[date, list[dict]] = {first_day + timedelta(days=n): [] for n in range(7)}
    for row in collected:
        day = business_date(row.collected_at)
        if day in by_day:
            by_day[day].append(_order(row, None))

    back_to = read_back_to(db)
    whole = back_to is not None and (
        back_to == HISTORY_START or back_to <= first_day - PICKUP_LOOKBACK
    )
    return {
        "cards": cards,
        "pickups": {
            "complete": whole,
            "read_back_to": back_to.isoformat() if back_to else None,
            "days": [
                {"date": day.isoformat(), "count": len(orders), "orders": orders}
                for day, orders in sorted(by_day.items(), reverse=True)
            ],
        },
    }


# ── B4, the success rate ──────────────────────────────────────────────────────

#: Bosta's dashboard's definition (ADR 0057 §9).
SUCCESSFUL = or_(
    and_(OpsBostaDelivery.type_value == "Send", OpsBostaDelivery.state_code == 45),
    and_(
        OpsBostaDelivery.type_value.in_(("Exchange", "Customer Return Pickup")),
        OpsBostaDelivery.state_code == 46,
    ),
)
UNSUCCESSFUL = and_(
    OpsBostaDelivery.type_value == "Return to Origin", OpsBostaDelivery.state_code.in_((46, 60))
)


def success_rate(db: Session, start: date, end: date, now: datetime | None = None) -> dict:
    """Orders created on Bosta from ``start`` to ``end`` (Cairo dates, both
    included): how many succeeded, how many came back, and the rate.

    Raises ValueError, in plain words, for a range that cannot be asked.
    """
    today = business_date(now or utcnow())
    if start > end:
        raise ValueError("The range starts after it ends.")
    if end > today:
        raise ValueError("The range ends after today.")
    if start < HISTORY_START:
        raise ValueError("Not available before 1 Jan 2026.")

    body = {"from": start.isoformat(), "to": end.isoformat()}
    back_to = read_back_to(db)
    if back_to is None or start < back_to:
        return {
            **body,
            "available": False,
            "read_back_to": back_to.isoformat() if back_to else None,
        }

    window = and_(
        OpsBostaDelivery.deleted_at.is_(None),
        OpsBostaDelivery.created_at >= _cairo_midnight(start),
        OpsBostaDelivery.created_at < _cairo_midnight(end + timedelta(days=1)),
    )
    successful = db.scalar(select(func.count()).where(window, SUCCESSFUL))
    unsuccessful = db.scalar(select(func.count()).where(window, UNSUCCESSFUL))
    finished = successful + unsuccessful
    return {
        **body,
        "available": True,
        "successful": successful,
        "unsuccessful": unsuccessful,
        "finished": finished,
        "rate": round(successful / finished, 4) if finished else None,
    }
