"""What the owner needs to see about a month, in one answer.

Phase 07B. A01: model-generated sales, expected payout, fixed salaries,
commissions, necessary guarantee top-ups, the active model count, the top three
by generated sales, and content progress needing review.

## The breakdown adds up, by construction

A month's payout is one exact figure rounded **once** (ADR 0003, 0004). So the
parts here are carved **out of** that rounded payout rather than rounded
separately and added — otherwise three components that each round up would
report a total the payroll screen disagrees with by a pound, on the one screen
whose job is to say how much money to find.

Per model, the parts are taken in the order the arrangement decides them:

    commission            what the orders came to
    fixed salary          paid as well, on fixed_plus_commission
    guarantee top-up      what a floor added, where it applied

and whatever is left of the payout after the other two is the commission part.
Nothing is computed twice and nothing is computed in the browser.

## Nothing here is a second opinion

Every figure comes from `calculate_month` through `blockers_for`, the same call
the payroll screen makes. This aggregates; it does not re-derive. A second
implementation of what a month is worth is a second answer waiting to disagree
with the first in front of the person paying.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.core.businesstime import parse_month
from sqlalchemy import func, select

from app.models.affiliates import AccountKind, AffiliateProfile
from app.models.codes import DiscountCodePeriod
from app.models.attributed_orders import AttributedOrder
from app.services.commission.calculate import COUNTED_STATES
from app.models.targets import MonthlyTarget
from app.models.compensation import CompensationType
from app.services.affiliates import list_affiliates
from app.services.pace import BEHIND, NO_TARGET, NOT_RECORDED, pace_for
from app.services.payroll import blockers_for
from app.services.performance import month_performance

#: Pace states that are somebody's job rather than a verdict on a model.
#: `NO_TARGET` and `NOT_RECORDED` are HBA's own work; `BEHIND` is the only one
#: that is about her, and the owner sees all three because all three stop a
#: month closing cleanly.
NEEDS_REVIEW = (NO_TARGET, NOT_RECORDED, BEHIND)


@dataclass
class Breakdown:
    """Where an expected payout comes from. The parts sum to `payout`."""

    payout_piastres: int = 0
    commission_piastres: int = 0
    fixed_piastres: int = 0
    guarantee_top_up_piastres: int = 0


@dataclass
class Summary:
    month: str
    active_models: int
    sales_piastres: int
    breakdown: Breakdown = field(default_factory=Breakdown)
    #: Ready to approve, and what still blocks the rest.
    #: Models with attributed sales this month, which is not the same as the
    #: active count — the design's sales card says which of the two its figure
    #: came from, so a quiet month reads as quiet rather than as broken.
    selling_models: int = 0

    ready: int = 0
    blocked: int = 0
    #: A01's *content progress needing review*, by why.
    needs_review: dict[str, int] = field(default_factory=dict)

    #: **The models themselves, not a count of them.** A panel that says
    #: *3 models - nothing recorded this week* tells the owner a number and
    #: then makes her go and find out which three, which is the screen doing
    #: half a job. These rows carry what was asked for, what was produced and
    #: when it was last touched, which is the whole question.
    content: list[dict] = field(default_factory=list)
    #: The top three by generated sales. Shares a place on a tie, exactly as
    #: the models' own board does (D03) - a board where three people are
    #: level and only two are shown is a board that picked one of them.
    top: list[dict] = field(default_factory=list)
    #: January to the month being looked at, one figure each, for the chart
    #: the approved Home draws under everything else.
    year: list[dict] = field(default_factory=list)


def _attribute(calculation) -> Breakdown:
    """Carve one model's payout into its parts.

    **Taken out of the rounded payout, never rounded separately.** A fixed
    salary is an exact integer and a guarantee is an exact floor, so both can
    be subtracted safely; the commission is whatever remains, which is what
    makes the three add up to the figure the payroll screen shows.
    """
    payout = calculation.payout_piastres
    fixed = 0
    top_up = 0

    if calculation.compensation_type == CompensationType.FIXED_PLUS_COMMISSION:
        # **Both are paid** - the arrangement this codebase warns is most often
        # got wrong. The salary is exact, so the commission is the remainder.
        fixed = min(calculation.fixed_piastres, payout)
    elif calculation.compensation_type == CompensationType.BASE_GUARANTEE:
        if calculation.guarantee_applied:
            # The floor carried her above what the orders came to. What the
            # floor added is the top-up; the rest is what she actually sold.
            #
            # Half-up to the piastre, the platform's one rounding rule (ADR
            # 0004). The commission is exact and undivided until here, and
            # this is the only place it is reduced - the payout it is
            # subtracted from was rounded by the same rule, so the two cannot
            # drift apart by more than the rounding they share.
            earned = int(
                Decimal(calculation.commission_piastres).quantize(
                    Decimal(1), rounding=ROUND_HALF_UP
                )
            )
            top_up = max(payout - earned, 0)

    return Breakdown(
        payout_piastres=payout,
        fixed_piastres=fixed,
        guarantee_top_up_piastres=top_up,
        commission_piastres=max(payout - fixed - top_up, 0),
    )


def month_summary(db: Session, month: str) -> Summary:
    """The owner's whole month, in one pass over the models.

    One `calculate_month` per model, which is what the payroll screen already
    costs for the same list. It is not free and it is not duplicated: this
    screen and that one ask the same question, and the answer comes from the
    same place.
    """
    month = parse_month(month)

    # House accounts are excluded once, here, rather than in each figure -
    # a house code has real sales and no payee, and it must not enter a model
    # count, a payout total or a leaderboard.
    models = [row for row in list_affiliates(db) if row.is_payable]

    summary = Summary(
        month=month,
        active_models=sum(1 for row in models if row.status == "active"),
        sales_piastres=0,
    )
    review: dict[str, int] = {}

    for affiliate in models:
        blockers, calculation = blockers_for(db, affiliate, month)
        # **Counted sales** (F02, ADR 0040): what the month is paid on, which
        # is delivered and pending together. It summed delivered only while
        # the engine did, and the chart under this card sums the same thing -
        # a card and its own chart disagreeing about August is the kind of
        # difference nobody can explain from the screen.
        summary.sales_piastres += (
            calculation.earned_base_piastres + calculation.pending_base_piastres
        )

        if blockers:
            summary.blocked += 1
        else:
            summary.ready += 1
            part = _attribute(calculation)
            summary.breakdown.payout_piastres += part.payout_piastres
            summary.breakdown.commission_piastres += part.commission_piastres
            summary.breakdown.fixed_piastres += part.fixed_piastres
            summary.breakdown.guarantee_top_up_piastres += (
                part.guarantee_top_up_piastres
            )

        state = pace_for(db, affiliate, month).state
        if state in NEEDS_REVIEW:
            review[state] = review.get(state, 0) + 1

    summary.selling_models = sum(
        1 for row in month_performance(db, month) if row.sales_piastres > 0
    )
    summary.needs_review = review
    summary.content = content_rows(db, models, month)
    summary.top = _top_three(db, month)
    summary.year = sales_by_month(db, month)
    return summary


def sales_by_month(db: Session, month: str) -> list[dict]:
    """Generated sales for each month of this month's year, to date.

    **One query, not twelve `calculate_month` calls.** The figure the chart
    wants is the same one the sales card shows - what models generated, before
    anybody's commission - and that is a sum over attributed orders. Running
    the payroll engine eleven more times to obtain it would make Home the
    slowest screen in the tool for a row of bars.

    **Counted orders, which is the live rule** (F02, ADR 0040): delivered and
    pending, never a failed delivery. It was delivered-only while the payroll
    engine was, and leaving it there would have drawn a chart that disagreed
    with the money beside it - the bar saying one thing about August and the
    payment saying another.

    No house account: this is *sales generated by models*, and a house code
    has real sales and no model behind it.

    Months with no orders are present with a zero rather than absent. A chart
    that drops empty months draws a quiet March as though it never happened,
    and the gap is the thing worth seeing.
    """
    month = parse_month(month)
    year, last = month.split("-")
    months = [f"{year}-{index:02d}" for index in range(1, int(last) + 1)]

    totals = dict(
        db.execute(
            select(
                AttributedOrder.business_month,
                func.coalesce(
                    func.sum(AttributedOrder.commission_base_piastres), 0
                ),
            )
            .join(
                AffiliateProfile,
                AffiliateProfile.id == AttributedOrder.affiliate_id,
            )
            .where(AttributedOrder.business_month.in_(months))
            .where(AttributedOrder.commission_state.in_(COUNTED_STATES))
            .where(AffiliateProfile.account_kind != AccountKind.HOUSE)
            .group_by(AttributedOrder.business_month)
        ).all()
    )

    return [
        {"month": each, "sales_piastres": int(totals.get(each, 0))}
        for each in months
    ]


def content_rows(
    db: Session, models: list[AffiliateProfile], month: str
) -> list[dict]:
    """What each model was asked for, what she produced, and when.

    **Videos and stories stay apart here**, unlike D08's pace, which adds them
    together to decide whether she is on track. The pace answers *is this
    month in trouble*; this table answers *what is missing*, and four videos
    short is a different conversation from four stories short.

    One query for the month rather than one per model: the row may not exist
    at all, and a missing row is not the same as a row of zeroes - nobody
    asked her for anything, as against she has produced nothing.
    """
    targets = {
        row.affiliate_id: row
        for row in db.scalars(
            select(MonthlyTarget).where(MonthlyTarget.month == month)
        )
    }

    rows = []
    for affiliate in models:
        target = targets.get(affiliate.id)
        produced = (target.actual_videos or 0) + (target.actual_stories or 0) if target else 0
        rows.append(
            {
                "affiliate_id": affiliate.id,
                "name": affiliate.name,
                "required_videos": target.required_videos if target else None,
                "required_stories": target.required_stories if target else None,
                "actual_videos": target.actual_videos if target else None,
                "actual_stories": target.actual_stories if target else None,
                "last_update": (
                    target.recorded_at.isoformat()
                    if target and target.recorded_at
                    else None
                ),
                "_produced": produced,
            }
        )

    # **Worst first**, because this panel exists to be acted on. A model with
    # nothing recorded at all leads, then the least produced. Alphabetical
    # order would put the model who is fine at the top on a good day and bury
    # the one who is not.
    rows.sort(key=lambda row: (row["last_update"] is not None, row["_produced"], row["name"]))
    for row in rows:
        del row["_produced"]
    return rows


def _top_three(db: Session, month: str) -> list[dict]:
    """The three best months by generated sales, sharing a place on a tie.

    Reuses the models' own board (D03), so the owner and the models are never
    told different things about who is ahead. **A tie is shown whole**: three
    people level at the top are all shown, because a list that cut one of them
    would have picked a winner the rule did not.
    """
    board = month_performance(db, month)
    if not board:
        return []

    # Her code, as it stood **in that month** - not her current one. A code
    # that changed hands in October must not relabel September's leaderboard.
    codes = {
        row.affiliate_id: row.code
        for row in db.scalars(
            select(DiscountCodePeriod).where(
                DiscountCodePeriod.start_month <= month,
                (DiscountCodePeriod.end_month.is_(None))
                | (DiscountCodePeriod.end_month >= month),
            )
        )
    }

    # **Everyone in the first three places, however many people that is.**
    # Ranks already skip on a tie (D03), so three level at the top are 1, 1, 1
    # and the next is 4 - and `rank <= 3` includes exactly the three of them.
    # Taking "the first three rows" instead would cut one of three equals and
    # pick a winner the rule did not.
    return [
        {
            "affiliate_id": row.affiliate_id,
            "name": row.name,
            "code": codes.get(row.affiliate_id),
            "rank": row.rank,
            "sales_piastres": row.sales_piastres,
            "uses": row.uses,
        }
        for row in board
        if row.rank <= 3 and row.sales_piastres > 0
    ]
