"""Khazenly's public tracking, read for Operations → Returns (ADR 0079).

``track.khazenly.com`` reads one JSON endpoint with no login::

    GET https://tracking-api.khazenly.com/api/v1/tracking/?referenceNumber=KH-HBA-08997921

Checked by hand on 10 November 2026 with 11 real orders. The answer is
``{"data": {"order": {...}, "timeline": [...]}}``: ``order.Name`` is the KH
number and ``order.PO_Number__c`` the merchant order number (``#31876-RE``);
each timeline entry has ``Order_Status__c``, ``Order_Status_Date__c`` (UTC,
``2026-11-10T08:58:16.000+0000``) and sometimes a courier ``Note__c``,
newest first. **No customer details** are in it. An unknown number is an
HTTP 500 whose body is ``"Request failed with status code 404"``.

**It is unofficial**: the endpoint behind their public page, not an API
they promised. Every failure here is a sentence a person can read, and
nothing in it echoes the response.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime

import httpx

BASE_URL = "https://tracking-api.khazenly.com/api/v1/tracking/"
TIMEOUT_SECONDS = 10.0
#: Says who is asking, and nothing about anyone.
USER_AGENT = "HBA-platform/1.0 (returns tracking)"

#: A Khazenly order number, e.g. ``KH-HBA-08997921``.
KH_NUMBER = re.compile(r"KH-[A-Z0-9]+-\d{4,12}")

#: The step that means the parcel is back and counted (ADR 0079, decision 3).
RETURN_COMPLETED = "Return Completed"
#: The step Khazenly's own page hides as "Order In Progress".
CONTACT_SUCCESS_MANAGER = "Contact Success Manager"

NOT_FOUND = "Khazenly has no order with this number."
UNAVAILABLE = "Khazenly's tracking didn't answer."
UNREADABLE = "Khazenly's tracking answered in a way the platform couldn't read."

#: Kept short: a step's name, a courier note.
_STEP_LIMIT = 80
_NOTE_LIMIT = 120


class TrackingError(Exception):
    """Khazenly could not say where an order is. ``str()`` is safe to show."""


class NotFound(TrackingError):
    """Khazenly does not know this number."""


@dataclass(frozen=True)
class Step:
    step: str
    at: datetime | None
    note: str | None = None

    def as_json(self) -> dict:
        return {
            "step": self.step,
            "at": self.at.isoformat() if self.at else None,
            "note": self.note,
        }


@dataclass(frozen=True)
class Tracking:
    khazenly_number: str
    merchant_order: str | None
    #: Newest first.
    timeline: list[Step] = field(default_factory=list)

    @property
    def latest(self) -> Step | None:
        return self.timeline[0] if self.timeline else None

    @property
    def received_at(self) -> datetime | None:
        """When Khazenly said *Return Completed*, if it has."""
        done = [entry.at for entry in self.timeline if entry.step == RETURN_COMPLETED and entry.at]
        return min(done) if done else None

    @property
    def received(self) -> bool:
        return any(entry.step == RETURN_COMPLETED for entry in self.timeline)

    @property
    def order_number(self) -> str | None:
        return shopify_number(self.merchant_order)


def normalise(raw: str) -> str:
    """``kh-hba-08997921 `` as ``KH-HBA-08997921``; anything else as typed,
    upper-cased, so the refusal can say what it was."""
    return re.sub(r"\s+", "", str(raw or "")).upper()


def is_kh_number(value: str) -> bool:
    return KH_NUMBER.fullmatch(value) is not None


def shopify_number(merchant_order: str | None) -> str | None:
    """``#31876-RE`` → ``#31876``. None when it does not start with a number."""
    found = re.match(r"\s*#?\s*(\d{3,10})", merchant_order or "")
    return f"#{found.group(1)}" if found else None


def _when(raw) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    for pattern in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(raw, pattern)
        except ValueError:
            continue
    return None


def _note(raw) -> str | None:
    # Khazenly's notes end in a dash: "shipment Delivered-".
    text = str(raw or "").strip().rstrip("-").strip()
    return text[:_NOTE_LIMIT] or None


def parse(number: str, body) -> Tracking:
    """Read one answer. Only the fields above are taken out of it."""
    try:
        data = body["data"]
        order = data["order"] or {}
        entries = data.get("timeline") or []
    except (KeyError, TypeError):
        raise TrackingError(UNREADABLE) from None
    if not isinstance(entries, list):
        raise TrackingError(UNREADABLE)
    name = normalise(order.get("Name") or "")
    if name and name != number:
        # Asked for one order, told about another: trust neither.
        raise TrackingError(UNREADABLE)
    timeline = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        step = str(entry.get("Order_Status__c") or "").strip()[:_STEP_LIMIT]
        if not step:
            continue
        timeline.append(
            Step(step=step, at=_when(entry.get("Order_Status_Date__c")), note=_note(entry.get("Note__c")))
        )
    # Newest first, whatever order they came in; undated steps last.
    timeline.sort(key=lambda entry: entry.at.timestamp() if entry.at else float("-inf"), reverse=True)
    merchant = str(order.get("PO_Number__c") or "").strip()[:60] or None
    return Tracking(khazenly_number=number, merchant_order=merchant, timeline=timeline)


class Client:
    """One connection, for one request or one 30-minute read."""

    def __init__(self, transport: httpx.BaseTransport | None = None, timeout: float = TIMEOUT_SECONDS):
        self._http = httpx.Client(
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def track(self, raw_number: str) -> Tracking:
        number = normalise(raw_number)
        if not is_kh_number(number):
            raise NotFound(NOT_FOUND)
        try:
            response = self._http.get(BASE_URL, params={"referenceNumber": number})
        except httpx.HTTPError:
            raise TrackingError(UNAVAILABLE) from None
        if response.status_code in (404, 500) and "404" in response.text[:200]:
            raise NotFound(NOT_FOUND)
        if response.status_code != 200:
            raise TrackingError(UNAVAILABLE)
        try:
            body = response.json()
        except ValueError:
            raise TrackingError(UNREADABLE) from None
        return parse(number, body)
