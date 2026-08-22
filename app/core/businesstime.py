"""Business time rules.

Timestamps are stored in UTC. The business month — which decides which payroll
period an order belongs to, and therefore who is paid what — is derived in
Africa/Cairo. That makes this a financial rule, not a formatting preference.

A fixed offset is never used. Egypt abolished seasonal clock changes in 2015
and reinstated them in 2023; verified against the timezone database, 2026 runs
UTC+3 from 24 April to 29 October and UTC+2 otherwise. An order placed at
21:30 UTC on 31 August is already 1 September in Cairo, while the same clock
time on 31 December is still December. Hardcoding either offset misfiles
orders into the wrong payroll month.

Converting UTC to local is always unambiguous. The missing hour in spring and
the repeated hour in autumn only create ambiguity in the other direction, and
this system never goes that way: it stores the instant and derives the month.
"""

import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

BUSINESS_TIMEZONE = ZoneInfo("Africa/Cairo")
_MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def utcnow() -> datetime:
    """Current instant, timezone-aware, in UTC."""
    return datetime.now(timezone.utc)


def _require_aware(moment: datetime) -> datetime:
    """Refuse naive datetimes.

    A naive timestamp names no instant. Assuming one would silently move
    orders between payroll months, so it is rejected rather than guessed.
    """
    if not isinstance(moment, datetime):
        raise ValueError("Business time requires a datetime")
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("Business time requires a timezone-aware datetime")
    return moment


def business_date(moment_utc: datetime) -> date:
    """The calendar date in Cairo for a given instant."""
    return _require_aware(moment_utc).astimezone(BUSINESS_TIMEZONE).date()


def business_month(moment_utc: datetime) -> str:
    """The YYYY-MM business month in Cairo for a given instant."""
    return business_date(moment_utc).strftime("%Y-%m")


def parse_month(value: str) -> str:
    """Validate a YYYY-MM month string, returning it unchanged."""
    if not isinstance(value, str) or not _MONTH_PATTERN.match(value):
        raise ValueError("Month must use YYYY-MM format")
    return value


def month_add(month: str, delta: int) -> str:
    """Shift a YYYY-MM month by a number of months, crossing years correctly."""
    parse_month(month)
    year, mon = (int(part) for part in month.split("-"))
    index = year * 12 + (mon - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"
