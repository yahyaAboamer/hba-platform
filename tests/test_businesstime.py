"""Business time.

Spec section 7. The business month decides which payroll period an order
belongs to, and therefore who is paid what. That makes timezone handling a
financial rule, not a formatting preference.

Egypt reinstated seasonal clock changes in 2023. Verified against the
timezone database, 2026 runs UTC+3 from 24 April to 29 October and UTC+2
otherwise, so an order placed late in the evening can fall on either side of
a month boundary depending on the date.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.businesstime import (
    BUSINESS_TIMEZONE,
    business_date,
    business_month,
    month_add,
    parse_month,
    utcnow,
)


# ── Aware instants only ────────────────────────────────────────────────────────


def test_utcnow_is_timezone_aware():
    now = utcnow()
    assert now.tzinfo is not None
    assert now.utcoffset() is not None


def test_naive_datetime_is_rejected():
    # A naive timestamp has no defined instant. Guessing one would silently
    # move orders between payroll months.
    with pytest.raises(ValueError):
        business_month(datetime(2026, 8, 31, 21, 30))
    with pytest.raises(ValueError):
        business_date(datetime(2026, 8, 31, 21, 30))


def test_non_utc_aware_input_is_accepted_and_converted():
    """Any aware instant is unambiguous, wherever it was recorded.

    06:30 on 1 Sep in Tokyo (UTC+9) is 21:30 on 31 Aug UTC, which is 00:30 on
    1 Sep in Cairo (UTC+3 in August). September, by way of three timezones.
    """
    tokyo = datetime(2026, 9, 1, 6, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert tokyo.astimezone(timezone.utc).isoformat() == "2026-08-31T21:30:00+00:00"
    assert business_month(tokyo) == "2026-09"


# ── Month boundaries during summer time (UTC+3) ────────────────────────────────


def test_summer_order_late_at_night_belongs_to_the_next_month():
    # 21:30 UTC on 31 Aug is 00:30 on 1 Sep in Cairo.
    moment = datetime(2026, 8, 31, 21, 30, tzinfo=timezone.utc)
    assert business_month(moment) == "2026-09"


def test_summer_order_earlier_the_same_evening_stays_in_august():
    # 20:00 UTC is 23:00 Cairo on 31 Aug.
    moment = datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc)
    assert business_month(moment) == "2026-08"


def test_summer_boundary_is_exactly_21_00_utc():
    # The last instant of August in Cairo is 20:59:59 UTC.
    assert business_month(datetime(2026, 8, 31, 20, 59, 59, tzinfo=timezone.utc)) == "2026-08"
    assert business_month(datetime(2026, 8, 31, 21, 0, 0, tzinfo=timezone.utc)) == "2026-09"


# ── Month boundaries during standard time (UTC+2) ──────────────────────────────


def test_winter_order_uses_the_standard_offset():
    # 22:30 UTC on 31 Dec is 00:30 on 1 Jan in Cairo.
    moment = datetime(2026, 12, 31, 22, 30, tzinfo=timezone.utc)
    assert business_month(moment) == "2027-01"


def test_winter_order_before_the_boundary_stays_in_december():
    moment = datetime(2026, 12, 31, 21, 0, tzinfo=timezone.utc)
    assert business_month(moment) == "2026-12"


def test_winter_boundary_is_exactly_22_00_utc():
    assert business_month(datetime(2026, 12, 31, 21, 59, 59, tzinfo=timezone.utc)) == "2026-12"
    assert business_month(datetime(2026, 12, 31, 22, 0, 0, tzinfo=timezone.utc)) == "2027-01"


def test_the_boundary_moves_with_the_season():
    """The whole point: the same clock time means different months by season.

    21:30 UTC is already the next month in summer but not in winter. A fixed
    offset cannot express this.
    """
    summer = datetime(2026, 8, 31, 21, 30, tzinfo=timezone.utc)
    winter = datetime(2026, 12, 31, 21, 30, tzinfo=timezone.utc)
    assert business_month(summer) == "2026-09"  # already September
    assert business_month(winter) == "2026-12"  # still December


# ── Why a fixed offset is unacceptable ─────────────────────────────────────────


def test_a_hardcoded_offset_would_misfile_orders():
    """Proof, in the suite, of why UTC+2 is never hardcoded.

    A naive +2 puts a 31 August order in August. Cairo was on +3 that day, so
    it genuinely belongs to September, and the affiliate's August payroll
    would be wrong.
    """
    moment = datetime(2026, 8, 31, 21, 30, tzinfo=timezone.utc)
    hardcoded_plus_two = (moment + timedelta(hours=2)).strftime("%Y-%m")
    assert hardcoded_plus_two == "2026-08"       # wrong
    assert business_month(moment) == "2026-09"   # correct


def test_a_hardcoded_plus_three_would_misfile_winter_orders():
    """The opposite mistake, for completeness."""
    moment = datetime(2026, 12, 31, 21, 30, tzinfo=timezone.utc)
    hardcoded_plus_three = (moment + timedelta(hours=3)).strftime("%Y-%m")
    assert hardcoded_plus_three == "2027-01"     # wrong
    assert business_month(moment) == "2026-12"   # correct


# ── The timezone database itself ───────────────────────────────────────────────


def test_egypt_still_observes_summer_time():
    """A deliberate canary on a third-party dataset.

    Egypt abolished DST in 2015 and reinstated it in 2023. If the rules change
    again, every month boundary in this system moves and the business needs to
    know. This test failing is a signal to review, not a bug to silence.
    """
    cairo = BUSINESS_TIMEZONE
    january = datetime(2026, 1, 15, 12, tzinfo=timezone.utc).astimezone(cairo)
    july = datetime(2026, 7, 15, 12, tzinfo=timezone.utc).astimezone(cairo)
    assert january.utcoffset() == timedelta(hours=2)
    assert july.utcoffset() == timedelta(hours=3)


def test_converting_from_utc_is_never_ambiguous():
    """Clock changes create a missing hour and a repeated hour in local time.

    That ambiguity only bites when converting local -> UTC. This system always
    stores UTC and derives local, so every instant maps to exactly one month.
    The repeated hour after the October change is the sharpest case.
    """
    # 2026-10-29T21:00Z is the instant Cairo falls back from +3 to +2.
    before = datetime(2026, 10, 29, 20, 30, tzinfo=timezone.utc)
    after = datetime(2026, 10, 29, 21, 30, tzinfo=timezone.utc)
    # Both resolve, and both land in October.
    assert business_month(before) == "2026-10"
    assert business_month(after) == "2026-10"
    # Local clock reads 23:30 both times; the UTC instants differ.
    assert before.astimezone(BUSINESS_TIMEZONE).hour == 23
    assert after.astimezone(BUSINESS_TIMEZONE).hour == 23


# ── Dates ──────────────────────────────────────────────────────────────────────


def test_business_date_matches_the_month():
    moment = datetime(2026, 8, 31, 21, 30, tzinfo=timezone.utc)
    assert business_date(moment).isoformat() == "2026-09-01"


def test_business_date_on_an_ordinary_afternoon():
    moment = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
    assert business_date(moment).isoformat() == "2026-08-15"


# ── Month strings ──────────────────────────────────────────────────────────────


def test_parse_month_accepts_valid_values():
    assert parse_month("2026-08") == "2026-08"
    assert parse_month("2026-01") == "2026-01"
    assert parse_month("2026-12") == "2026-12"


def test_parse_month_rejects_invalid_values():
    for bad in ["2026-13", "2026-00", "26-08", "2026-8", "", "2026-08-01", "abcd-ef"]:
        with pytest.raises(ValueError):
            parse_month(bad)


def test_parse_month_rejects_non_strings():
    for bad in [None, 202608, ["2026-08"]]:
        with pytest.raises(ValueError):
            parse_month(bad)


def test_month_add_crosses_year_boundaries():
    assert month_add("2026-08", 1) == "2026-09"
    assert month_add("2026-12", 1) == "2027-01"
    assert month_add("2026-01", -1) == "2025-12"
    assert month_add("2026-08", 0) == "2026-08"


def test_month_add_handles_multiple_years():
    assert month_add("2026-08", 12) == "2027-08"
    assert month_add("2026-08", -24) == "2024-08"
    assert month_add("2026-03", -14) == "2025-01"


def test_month_add_validates_its_input():
    with pytest.raises(ValueError):
        month_add("2026-13", 1)
