"""Effective-dated periods.

Almost everything about an affiliate is true *for some months and not others*.
A code belongs to Nour from March, moves to nobody in July, and comes back in
September. A rate was 8% until June and 10% after. Ask who owned ``NOUR10`` in
April and the answer has to be a fact, because in Phase 4 that answer becomes
money.

So nothing here stores a value. It stores a value **and the months it applies
to** - and the database refuses to hold two that overlap.

## Why a generated daterange

Months are ``YYYY-MM`` strings everywhere in this codebase (ADR 0005), and
Postgres cannot exclude overlapping *strings*. Each period table therefore
carries a ``daterange`` derived from its months, and the exclusion constraint
works on that.

**Generated, not written by the application.** A generated column cannot drift
from the months it comes from. If the application wrote both, a bug could store
a row whose range says one thing and whose months say another - and the
constraint would then happily permit an overlap nobody reading the table could
see.

## Why the bounds are half-open

March to June inclusive is ``[2026-03-01, 2026-07-01)``: from the first of
March, up to but not including the first of July.

With inclusive upper bounds a period ending in June and one starting in July
would share an instant, and **every adjacent pair would be rejected as
overlapping** - which would make an ordinary rate change impossible to record.

## Why the arithmetic looks laborious

A generated column must be **immutable**, and `text::date` is not: parsing a
date from a string depends on the session's DateStyle. Postgres refuses the
column outright rather than storing something whose meaning could change with a
setting.

So the date is built from integers instead - `make_date` and integer division,
which are immutable. The upper bound is "the month after", with December
rolling into January of the next year:

    year  = month / 12 + year      (12 / 12 = 1, everything else 0)
    month = month % 12 + 1         (12 -> 1, 6 -> 7)

## Backwards periods, and the empty-range trap that is not one

A period ending before it starts is refused, but **not** by the check
constraint - verified rather than assumed:

- Inverted bounds make ``daterange()`` itself raise, during column generation,
  before any constraint is evaluated.
- *Equal* bounds produce an ``empty`` range, and an empty range overlaps
  nothing, not even another empty range. That would slip past the exclusion
  constraint entirely.

The second is the real trap, and this expression cannot produce it: the upper
bound is always the month *after* the last included, so it is never equal to
the lower bound. It is written down because a future change to the expression
could reintroduce it, and nothing would complain.

Period tables still carry ``CHECK (end_month IS NULL OR end_month >=
start_month)``. It is **currently unreachable** - the range error fires first -
and is kept as schema-level intent and as cover if the expression ever changes.
The readable message comes from the service layer instead, because
"range lower bound must be less than or equal to range upper bound" tells a
person nothing about months.
"""

from app.core.businesstime import month_add, parse_month

#: What an absent ``end_month`` means: from the start month, until further
#: notice. Spelled rather than left as a bare None at every call site.
OPEN_ENDED = None

#: The canonical generated-column expression.
#:
#: Migrations write this out **literally** rather than importing it - a
#: migration is frozen in time and must not change meaning because this module
#: later did. It lives here as the single definition to copy, and
#: `tests/test_periods.py` builds a real table from it and proves the semantics,
#: so the copies have something to be right against.
EFFECTIVE_RANGE_SQL = """daterange(
        make_date(left(start_month, 4)::int, right(start_month, 2)::int, 1),
        CASE WHEN end_month IS NULL THEN NULL
             ELSE make_date(
                 right(end_month, 2)::int / 12 + left(end_month, 4)::int,
                 right(end_month, 2)::int % 12 + 1,
                 1
             )
        END,
        '[)'
    )"""

#: The check that refuses a backwards period. Copied literally too.
MONTHS_ORDERED_SQL = "end_month IS NULL OR end_month >= start_month"


def month_bounds(start_month: str, end_month: str | None) -> tuple[str, str | None]:
    """The half-open date bounds of a month period, as ISO dates.

    The upper bound is the first day of the month **after** the last month
    included, or None when the period is open-ended.
    """
    parse_month(start_month)
    lower = f"{start_month}-01"

    if end_month is OPEN_ENDED:
        return lower, None

    parse_month(end_month)
    return lower, f"{month_add(end_month, 1)}-01"


def covers(start_month: str, end_month: str | None, month: str) -> bool:
    """Whether a period applies to a month.

    Must agree with the stored ``daterange`` in every case. This decides
    attribution; the exclusion constraint decides what can be stored. If they
    disagreed, a period could be stored that attribution never applies, or
    applied for a month the constraint believes belongs to somebody else -
    which is how the wrong person gets paid.
    """
    parse_month(start_month)
    parse_month(month)

    if month < start_month:
        return False
    if end_month is OPEN_ENDED:
        return True

    parse_month(end_month)
    return month <= end_month


def validate_period(start_month: str, end_month: str | None) -> tuple[str, str | None]:
    """Check a period and return it, raising something a person can read.

    The database refuses a backwards period too, but its message -
    "range lower bound must be less than or equal to range upper bound" -
    comes from deep inside a generated column and mentions nothing about
    months. This is what the caller should hit first.
    """
    parse_month(start_month)
    if end_month is OPEN_ENDED:
        return start_month, OPEN_ENDED

    parse_month(end_month)
    if end_month < start_month:
        raise ValueError(
            f"A period cannot end before it starts: {start_month} to {end_month}"
        )
    return start_month, end_month


def is_open_ended(end_month: str | None) -> bool:
    """Whether a period runs until further notice."""
    return end_month is OPEN_ENDED
