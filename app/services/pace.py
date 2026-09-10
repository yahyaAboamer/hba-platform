"""Whether a model is keeping up with her month, week by week.

Phase 07A, and D08 answered on 11 September 2026.

## A quarter of the month's targets a week

Videos and stories are **added together first, then divided**. Sixteen targets —
twelve stories and four videos — is four a week in any mix: two videos and two
stories is four, three videos and one story is four. Rounded up, so five
targets is two by the end of week one rather than one and a quarter.

## Weeks start on the day the month starts

Not Monday, and not the ISO calendar. A month beginning on a Thursday runs
Thursday to Wednesday. Cairo days, like every other date here (ADR 0005).

## The fourth check is the end of the month

A month is not four weeks. August 2026 begins on a Saturday, so its fourth week
ends on the 28th with three days still to go — and a model who finishes on the
31st was never behind. Asked directly, the owner chose the final checkpoint to
be the end of the month rather than the end of week four.

## Two things this refuses to call "behind"

**Stale counts.** The platform keeps one cumulative pair of actuals per month
and no weekly history, so comparing a figure last recorded in week one against
a week-three threshold does not measure her — **it measures how recently
somebody typed.** If nothing has been recorded since the current week began,
that is what it says.

**No target.** There is nothing to be behind on.

Both are the distinction §11.3 draws everywhere else: *unrecorded* and *missed*
are different facts and only one of them is about her.

## HBA only

The owner was asked and chose to keep this internal. Nothing here reaches a
model's screen in any wording, which means **she cannot catch up on a warning
she never sees** — a known consequence, recorded in the decision.

It also decides no money. §15 is untouched: a target pays only on a guaranteed
minimum, only at month end, and only when met *and* verified.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil

from sqlalchemy.orm import Session

from app.core.businesstime import business_date, parse_month, utcnow
from app.models.affiliates import AffiliateProfile
from app.services.targets import get_target

#: Nobody has set a requirement for this month.
#:
#: **This is an attention state, not a blank** (owner, 11 September 2026).
#: There is nothing for her to be behind on, and a model nobody has asked
#: anything of is a gap in HBA's own month - it is the reason a target-driven
#: guarantee cannot be decided, and it stays invisible until somebody looks.
NO_TARGET = "no_target"

#: Her counts have not been recorded since this week started. This says
#: nothing about her - only that nobody has typed since Thursday.
#:
#: Also an attention state: an uncounted month is what blocks a guaranteed
#: minimum (§11.3), and *nobody counted* is a thing for HBA to do rather than
#: a verdict on her.
NOT_RECORDED = "not_recorded_this_week"

#: Recorded, and at or past the line for the week she is in.
ON_TRACK = "on_track"

#: Recorded, and short of it.
BEHIND = "behind"

#: The month has not started yet.
NOT_STARTED = "not_started"


@dataclass(frozen=True)
class Pace:
    """Where she stands against this month's weekly line."""

    month: str
    state: str
    #: 1 to 4. The fourth runs to the end of the month however long that is.
    week: int
    #: Videos and stories added together.
    required: int
    #: What the line is for the week she is in, rounded up.
    expected_by_now: int
    done: int
    #: When the week she is in began, so a screen can say what "this week"
    #: means rather than leaving somebody to work it out.
    week_started: date


def week_bounds(month: str, when: date) -> tuple[int, date]:
    """Which week of the month a day falls in, and when that week began.

    Weeks are seven days from the first of the month. **The fourth absorbs
    whatever is left**: a 31-day month has three days past its fourth week and
    they belong to it, because the final checkpoint is the end of the month.
    """
    month = parse_month(month)
    first = date(int(month[:4]), int(month[5:7]), 1)
    elapsed = (when - first).days
    week = min(elapsed // 7 + 1, 4)
    return week, first + timedelta(days=(week - 1) * 7)


def expected_by(required: int, week: int) -> int:
    """The line for a given week, rounded up.

    `ceil(total x week / 4)`, applied to the week rather than accumulated, so
    five targets is 2, 3, 4, 5 rather than a quarter added four times and
    drifting.
    """
    if required <= 0:
        return 0
    return min(ceil(required * week / 4), required)


def pace_for(
    db: Session, affiliate: AffiliateProfile, month: str, *, today: date | None = None
) -> Pace:
    """How she is doing against this month's weekly line. D08.

    `today` is injectable because the answer depends on the date and a test
    that could not choose one would only ever exercise the week the suite
    happened to run in.
    """
    month = parse_month(month)
    today = today or business_date(utcnow())
    first = date(int(month[:4]), int(month[5:7]), 1)
    last = date(
        first.year, first.month, monthrange(first.year, first.month)[1]
    )

    if today < first:
        return Pace(month, NOT_STARTED, 1, 0, 0, 0, first)

    # A month already over is measured at its end, not at whatever today is.
    measured = min(today, last)
    week, week_started = week_bounds(month, measured)

    target = get_target(db, affiliate, month)
    if target is None or target.required_videos is None:
        return Pace(month, NO_TARGET, week, 0, 0, 0, week_started)

    required = (target.required_videos or 0) + (target.required_stories or 0)
    line = expected_by(required, week)

    # **The check that stops this measuring HBA instead of her.** One
    # cumulative pair per month and no weekly history, so a figure last
    # recorded before this week began cannot answer a question about this week.
    recorded_on = (
        business_date(target.recorded_at) if target.recorded_at else None
    )
    if target.actual_videos is None or recorded_on is None:
        return Pace(month, NOT_RECORDED, week, required, line, 0, week_started)
    if recorded_on < week_started:
        return Pace(
            month,
            NOT_RECORDED,
            week,
            required,
            line,
            (target.actual_videos or 0) + (target.actual_stories or 0),
            week_started,
        )

    done = (target.actual_videos or 0) + (target.actual_stories or 0)
    return Pace(
        month,
        ON_TRACK if done >= line else BEHIND,
        week,
        required,
        line,
        done,
        week_started,
    )
