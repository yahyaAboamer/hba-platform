"""How Production's old server read and wrote values, kept exactly.

Its screens were built against a JavaScript server, and they show what it
answered without reformatting: "05 Sept 2026", "1 days", a progress of 0
when a field was left out. ADR 0076 decision 2 keeps those answers, so the
handful of JavaScript behaviours they depend on are reproduced here, each
named after what it copies.
"""

import math
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo

CAIRO = ZoneInfo("Africa/Cairo")

#: `toLocaleDateString("en-GB", {month: "short"})` as the old server's
#: runtime wrote it (current ICU spells September "Sept").
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec")

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def clean_text(value: object, fallback: str = "", max_length: int = 180) -> str:
    """`cleanText`: a string, trimmed and cut, or the fallback when empty."""
    if not isinstance(value, str):
        return fallback
    return value.strip()[:max_length] or fallback


def js_number(value: object) -> float:
    """`Number(value)`: NaN where JavaScript would give NaN."""
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return 0.0
        try:
            return float(text)
        except ValueError:
            return math.nan
    return math.nan


def as_number(value: object, fallback: float = 0.0, *, absent: bool = False) -> float:
    """`asNumber(value, fallback)`. `absent` is JavaScript's `undefined`."""
    if absent:
        return fallback
    number = js_number(value)
    return number if math.isfinite(number) else fallback


def js_round(number: float) -> int:
    """`Math.round`: halves go up."""
    return math.floor(number + 0.5)


def out_number(value: object) -> int | float:
    """A number as JSON shows it: 50, not 50.0."""
    number = float(value) if value is not None else 0.0
    return int(number) if number.is_integer() else number


def number_words(number: float) -> str:
    """A number inside a sentence, as JavaScript prints it."""
    return str(int(number)) if float(number).is_integer() else repr(float(number))


def valid_date(value: str) -> bool:
    """`validDate`: a real YYYY-MM-DD day."""
    if not _DATE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def to_date(value: str) -> date | None:
    """A checked YYYY-MM-DD string as a date; blank as None."""
    return date.fromisoformat(value) if value else None


def iso(value: date | None) -> str:
    return value.isoformat() if value else ""


def display_date(value: date | None) -> str:
    """`displayDate`: "05 Sept 2026", or "—"."""
    if value is None:
        return "—"
    return f"{value.day:02d} {MONTHS[value.month - 1]} {value.year}"


def activity_time(moment: datetime) -> str:
    """The activity list's time: "05 Sept, 20:00", Cairo."""
    local = moment.astimezone(CAIRO)
    return f"{local.day:02d} {MONTHS[local.month - 1]}, {local.hour:02d}:{local.minute:02d}"


def sqlite_time(moment: datetime | None) -> str:
    """A time as the old database wrote it: "2026-10-08 12:56:17", UTC."""
    if moment is None:
        return ""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def utc_today() -> date:
    """`new Date().toISOString().slice(0, 10)`: today in UTC, as the old server dated things."""
    return datetime.now(timezone.utc).date()


def days_after(days: int) -> date:
    return utc_today() + timedelta(days=days)


def pounds_to_piastres(pounds: float) -> int:
    """Pounds typed into a screen, as integer piastres (ADR 0002), half-up."""
    try:
        exact = Decimal(repr(float(pounds))) * 100
    except InvalidOperation:
        return 0
    return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def piastres_to_pounds(piastres: int) -> int | float:
    """Integer piastres as the pounds the screens expect."""
    return out_number(Decimal(piastres) / 100)


def phase_slug(name: str) -> str:
    """`createDropPhase`'s id: lower case, NFKC, runs of non-letters as one dash."""
    text = unicodedata.normalize("NFKC", name.lower())
    slug = re.sub(r"[^\w]+|_+", "-", text, flags=re.UNICODE)
    return slug.strip("-")
