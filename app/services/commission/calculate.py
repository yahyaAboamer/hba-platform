"""What is a model owed for a month? — §9.5 and §9.6.

The end of the chain. Attribution said whose orders these are, the base said
what each is worth, the state said which of them count; this turns those into
one figure.

## The arithmetic is exact until the last step

`base × rate_bp` produces fractional piastres — `106,237 × 1000 ÷ 10,000 =
10,623.7` — so the numerator is carried **undivided** across every order and
divided **once** at the end (ADR 0003). Rounding happens once more, half-up, on
the final total (ADR 0004).

**Never per order.** Rounding forty orders before summing compounds forty
errors, and the result is not the same figure. Both numbers come back —
`exact_unrounded_piastres` and the rounded one — because the audit has to show
what was calculated as well as what will be paid.

## Three ways to be paid

| Type | Payout |
|---|---|
| `commission` | base sum × rate |
| `fixed_plus_commission` | commission **plus** the fixed salary |
| `base_guarantee` | **max(commission, base amount)** — targets achieved *and* verified |

The base guarantee is never added on top of a higher commission, and never caps
it. §9.5.

## Two things it refuses to decide

**A base guarantee, because targets are Phase 5.** "Achieved and verified" has
no answer yet, so the calculation returns the commission figure **and says the
guarantee is unresolved**. It never assumes targets were missed, which underpays,
and never assumes they were met, which overpays. §11.3 makes it a hard blocker
on approval.

## House accounts

`HBA10` is a real code used by real customers and needs a working dashboard.
Its orders attribute normally and its sales are real; it is simply **never
owed money** (§8, §17). So the sales figures are calculated and the payout is
zero, rather than the orders being hidden — hiding them would report HBA's own
sales as belonging to nobody, which is a different and wrong answer.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import parse_month
from app.core.money import (
    commission_numerator,
    exact_commission_piastres,
    round_half_up_to_pounds,
)
from app.models.affiliates import AccountKind, AffiliateProfile
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.compensation import CompensationType
from app.services.compensation import terms_for

#: Why a month's figure is not final. §11.3 refuses approval on any of these.
NO_TERMS = "no_compensation_terms_for_this_month"
TARGETS_UNVERIFIED = "base_guarantee_needs_targets_which_arrive_in_phase_5"


@dataclass(frozen=True)
class MonthCalculation:
    """What a month is worth, and everything needed to argue with it."""

    affiliate_id: int
    month: str

    #: Orders that count, and what they are worth together.
    earned_orders: int = 0
    earned_base_piastres: int = 0

    #: Shown separately rather than hidden, so a model can see what is coming.
    pending_orders: int = 0
    pending_base_piastres: int = 0

    void_orders: int = 0

    compensation_type: str | None = None
    commission_rate_bp: int | None = None

    #: The commission alone, before a fixed salary or a guarantee.
    commission_piastres: Decimal = Decimal(0)

    fixed_piastres: int = 0
    base_amount_piastres: int = 0

    #: Everything, exactly, before rounding. ADR 0003.
    exact_unrounded_piastres: Decimal = Decimal(0)

    #: The same figure rounded half-up to whole pounds. ADR 0004.
    payout_piastres: int = 0

    #: Real, and never owed. §8, §17.
    is_house: bool = False

    #: Empty means the figure can be approved as it stands.
    blockers: list[str] = field(default_factory=list)

    @property
    def is_payable(self) -> bool:
        return not self.is_house and not self.blockers


def calculate_month(
    db: Session, affiliate: AffiliateProfile, month: str
) -> MonthCalculation:
    """What this affiliate is owed for this month.

    Reads that month's terms, not today's (Phase 3). A rate change in June must
    not silently rewrite what April was worth.
    """
    parse_month(month)

    rows = list(
        db.scalars(
            select(AttributedOrder)
            .where(AttributedOrder.affiliate_id == affiliate.id)
            .where(AttributedOrder.business_month == month)
        )
    )

    earned_base = 0
    earned_count = 0
    pending_base = 0
    pending_count = 0
    void_count = 0

    for row in rows:
        if row.commission_state == CommissionState.EARNED:
            earned_count += 1
            earned_base += row.commission_base_piastres
        elif row.commission_state == CommissionState.PENDING:
            pending_count += 1
            pending_base += row.commission_base_piastres
        else:
            void_count += 1

    is_house = affiliate.account_kind == AccountKind.HOUSE
    blockers: list[str] = []

    terms = terms_for(db, affiliate, month)
    if terms is None:
        # Sales are still real and still worth reporting; what she is owed is
        # not calculable without terms, and guessing at a rate is how somebody
        # gets paid the wrong amount for eight months.
        blockers.append(NO_TERMS)
        return MonthCalculation(
            affiliate_id=affiliate.id,
            month=month,
            earned_orders=earned_count,
            earned_base_piastres=earned_base,
            pending_orders=pending_count,
            pending_base_piastres=pending_base,
            void_orders=void_count,
            is_house=is_house,
            blockers=blockers,
        )

    # One numerator for the whole month, divided once. Summing per-order
    # commissions instead would round each of them first.
    numerator = (
        commission_numerator(earned_base, terms.commission_rate_bp)
        if earned_base
        else 0
    )
    commission = exact_commission_piastres(numerator)

    fixed = 0
    guarantee = 0
    exact = commission

    if terms.compensation_type == CompensationType.FIXED_PLUS_COMMISSION:
        fixed = int(terms.fixed_amount_piastres or 0)
        exact = commission + fixed
    elif terms.compensation_type == CompensationType.BASE_GUARANTEE:
        guarantee = int(terms.base_amount_piastres or 0)
        # Targets arrive in Phase 5. Until then the guarantee cannot be
        # applied: max(commission, guarantee) is only correct when the targets
        # were achieved *and* verified, and neither assumption is safe.
        blockers.append(TARGETS_UNVERIFIED)

    payout = 0 if is_house else round_half_up_to_pounds(exact)

    return MonthCalculation(
        affiliate_id=affiliate.id,
        month=month,
        earned_orders=earned_count,
        earned_base_piastres=earned_base,
        pending_orders=pending_count,
        pending_base_piastres=pending_base,
        void_orders=void_count,
        compensation_type=terms.compensation_type,
        commission_rate_bp=terms.commission_rate_bp,
        commission_piastres=commission,
        fixed_piastres=fixed,
        base_amount_piastres=guarantee,
        exact_unrounded_piastres=exact,
        payout_piastres=payout,
        is_house=is_house,
        blockers=blockers,
    )
