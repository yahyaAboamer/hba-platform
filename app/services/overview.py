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
from app.models.affiliates import AffiliateProfile
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
    ready: int = 0
    blocked: int = 0
    #: A01's *content progress needing review*, by why.
    needs_review: dict[str, int] = field(default_factory=dict)
    #: The top three by generated sales. Shares a place on a tie, exactly as
    #: the models' own board does (D03) - a board where three people are
    #: level and only two are shown is a board that picked one of them.
    top: list[dict] = field(default_factory=list)


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
        summary.sales_piastres += calculation.earned_base_piastres

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

    summary.needs_review = review
    summary.top = _top_three(db, month)
    return summary


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

    # **Everyone in the first three places, however many people that is.**
    # Ranks already skip on a tie (D03), so three level at the top are 1, 1, 1
    # and the next is 4 - and `rank <= 3` includes exactly the three of them.
    # Taking "the first three rows" instead would cut one of three equals and
    # pick a winner the rule did not.
    return [
        {
            "affiliate_id": row.affiliate_id,
            "name": row.name,
            "rank": row.rank,
            "sales_piastres": row.sales_piastres,
            "uses": row.uses,
        }
        for row in board
        if row.rank <= 3 and row.sales_piastres > 0
    ]
