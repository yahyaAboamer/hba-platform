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

**A base guarantee whose targets nobody recorded.** "Achieved and verified" has
no answer, so the month blocks rather than guessing. It never assumes she missed,
which underpays, and never assumes she hit them, which overpays.

**Missing information blocks; poor performance does not.** A model who missed her
targets is paid her commission, promptly, and the month approves. §11.3, and the
distinction is the whole design - the block exists where the platform *does not
know*, never as a penalty.

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
from app.services.targets import get_target

#: Why a month's figure is not final. §11.3 refuses approval on any of these.
NO_TERMS = "no_compensation_terms_for_this_month"

#: Nobody has said what she was asked to produce, so nobody can say whether the
#: guarantee applies. §11.3 blocks on **missing information**, never on poor
#: performance.
NO_TARGET = "no_target_recorded_for_this_month"

#: She hit her targets and nobody has confirmed the numbers. Verification is
#: what unlocks the guarantee (§11.3), so this is not a formality.
TARGETS_UNVERIFIED = "targets_achieved_but_not_verified"


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

    #: §15. ``None`` means nobody has recorded what she produced - which is a
    #: different answer from missing the target, and blocks where missing does
    #: not.
    target_achieved: bool | None = None
    target_verified: bool = False

    #: Whether ``max(commission, base)`` actually took effect. False on a
    #: `commission` model, on a missed target, and on an unverified one.
    guarantee_applied: bool = False

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

    target = get_target(db, affiliate, month)
    achieved = target.is_achieved if target else None
    verified = bool(target and target.is_verified)
    guarantee_applied = False

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
            target_achieved=achieved,
            target_verified=verified,
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

        if achieved is None:
            # Nobody has recorded what she produced. Not a judgement about her
            # month - the platform simply does not know, and §11.3 blocks on
            # missing information.
            blockers.append(NO_TARGET)
        elif not achieved:
            # A confirmed miss. She is paid her commission, promptly, and the
            # month approves - the block is never a punishment for a quiet
            # month.
            pass
        elif not verified:
            blockers.append(TARGETS_UNVERIFIED)
        else:
            # §9.5. The base is never added on top of a higher commission and
            # never caps it, which is the intuitive mistake the spec calls out.
            if guarantee > commission:
                exact = Decimal(guarantee)
                guarantee_applied = True

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
        target_achieved=achieved,
        target_verified=verified,
        guarantee_applied=guarantee_applied,
        is_house=is_house,
        blockers=blockers,
    )
