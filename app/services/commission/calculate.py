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

## Which orders count — F02

**Pending and delivered both count. A failed delivery does not.** An order on
its way is a sale that has happened; the courier's confirmation is evidence
about the same sale, not a second event that creates it.

Two things keep that from paying anybody twice. Approval settles every order
it counted, so a later month cannot pay the same one again; and
`carried_forward` now pays only what an **earlier, delivered-only** approval
left out, which is a finite backlog that empties and is never added to.

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
no answer, so the month blocks rather than guessing. It never assumes they missed,
which underpays, and never assumes they hit them, which overpays.

**Missing information blocks; poor performance does not.** A model who missed their
targets is paid their commission, promptly, and the month approves. §11.3, and the
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

from sqlalchemy import func, select
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
from app.models.payroll import PayrollMonth, PayrollSnapshot
from app.services.compensation import terms_for
from app.services.commission.source import SourceOrder
from app.services.targets import get_target

#: Why a month's figure is not final. §11.3 refuses approval on any of these.
NO_TERMS = "no_compensation_terms_for_this_month"

#: Nobody has said what they were asked to produce, so nobody can say whether the
#: guarantee applies. §11.3 blocks on **missing information**, never on poor
#: performance.
NO_TARGET = "no_target_recorded_for_this_month"

#: They hit their targets and nobody has confirmed the numbers. Verification is
#: what unlocks the guarantee (§11.3), so this is not a formality.
TARGETS_UNVERIFIED = "targets_achieved_but_not_verified"

#: F02. The live counting rule, written into every snapshot it agrees.
PENDING_INCLUSIVE = "pending_inclusive"

#: The rule before it. **A snapshot carries no policy at all if it was agreed
#: under this one**, which is what identifies the months the transition has to
#: reconcile.
DELIVERED_ONLY = "delivered_only"

#: F02. The order states the live policy pays for, defined once beside the
#: arithmetic that sums them. Approval settles exactly these, so what a month
#: paid for and what it recorded paying for cannot drift apart.
COUNTED_STATES = (CommissionState.EARNED, CommissionState.PENDING)


@dataclass(frozen=True)
class SourceMonthSales:
    """What a month sold, whoever ended up paying the commission on it. R3.

    **Every order attributed to the month**, with no settlement filter. The
    payment calculation excludes an order a *different* month's payroll
    settled, and it has to: paying it twice is the one thing the transition
    guards against. But that is a fact about which payroll paid, not about
    when the sale happened — and a model's own screen answers the second
    question.

    Reading her performance out of the payment calculator made a legacy
    carried order vanish from the month she actually sold it in. Her August
    sales fell because September's payroll paid one of them, which is not
    something that happened to August.
    """

    counted_piastres: int = 0
    delivered_piastres: int = 0
    pending_piastres: int = 0
    failed_piastres: int = 0
    counted_orders: int = 0
    delivered_orders: int = 0
    pending_orders: int = 0
    failed_orders: int = 0


def source_month_sales(
    db: Session, affiliate: AffiliateProfile, month: str
) -> SourceMonthSales:
    """Her sales for one month, by delivery outcome. F02, F13, R3."""
    parse_month(month)
    rows = db.execute(
        select(
            AttributedOrder.commission_state,
            func.count(AttributedOrder.shopify_order_id),
            func.coalesce(func.sum(AttributedOrder.commission_base_piastres), 0),
        )
        .where(AttributedOrder.affiliate_id == affiliate.id)
        .where(AttributedOrder.business_month == month)
        .group_by(AttributedOrder.commission_state)
    ).all()

    by_state = {state: (int(count or 0), int(base or 0)) for state, count, base in rows}
    delivered_orders, delivered = by_state.get(CommissionState.EARNED, (0, 0))
    pending_orders, pending = by_state.get(CommissionState.PENDING, (0, 0))
    failed_orders, failed = by_state.get(CommissionState.VOID, (0, 0))

    return SourceMonthSales(
        # F02: what the month is paid on. The two are kept beside it rather
        # than folded away - *counted* is the money and *delivered/pending* is
        # how far along it is, and her screen says both.
        counted_piastres=delivered + pending,
        delivered_piastres=delivered,
        pending_piastres=pending,
        failed_piastres=failed,
        counted_orders=delivered_orders + pending_orders,
        delivered_orders=delivered_orders,
        pending_orders=pending_orders,
        failed_orders=failed_orders,
    )


def counted_sales_from(figures: dict, policy: str = PENDING_INCLUSIVE) -> int:
    """The sales a figure was computed on, out of a stored or live calculation.

    **The commission line has to name the money it is a percentage of**, and
    that is not always the delivered total: since F02 it is delivered and
    pending together. A statement saying *10% of EGP 2,000* above a commission
    worked out on EGP 3,000 is a breakdown that does not add up, and the one
    person guaranteed to check is the person being paid.

    `policy` is the rule the figures were produced under - a snapshot's own,
    for an agreed month - so an old statement keeps saying what it always
    said.
    """
    earned = int(figures.get("earned_base_piastres") or 0)
    pending = int(figures.get("pending_base_piastres") or 0)
    return earned + (
        pending if CommissionState.PENDING in counted_states_for(policy) else 0
    )


def counted_states_for(policy: str) -> tuple[str, ...]:
    """Which order states a given policy pays for.

    Anything that is not the live rule is the old one: the absence of a policy
    means a month agreed before the transition, and there are no others.
    """
    return COUNTED_STATES if policy == PENDING_INCLUSIVE else (CommissionState.EARNED,)

#: §11.4. An order carried from a month that has no compensation terms. Its
#: sales are real; what it is worth is not calculable, and guessing at a rate
#: they were on eight months ago is how somebody gets paid the wrong amount.
NO_TERMS_FOR_CARRIED = "no_compensation_terms_for_a_carried_month"


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

    #: §15. ``None`` means nobody has recorded what they produced - which is a
    #: different answer from missing the target, and blocks where missing does
    #: not.
    target_achieved: bool | None = None
    target_verified: bool = False

    #: Whether ``max(commission, base)`` actually took effect. False on a
    #: `commission` model, on a missed target, and on an unverified one.
    guarantee_applied: bool = False

    #: Real, and never owed. §8, §17.
    is_house: bool = False

    #: §11.4. Orders from earlier approved months that this payroll pays.
    #: Each earlier month is commissioned at **its own** rate, never this
    #: month's - a rate change in September must not rewrite what an August
    #: sale was worth (§9.5).
    carried_orders: int = 0
    carried_base_piastres: int = 0
    carried_piastres: Decimal = Decimal(0)
    #: One line per month carried from, so the figure can be taken apart.
    carried_lines: list[dict] = field(default_factory=list)

    #: A carried month with no terms. Its sales are real and its commission is
    #: not calculable, so the month cannot be approved until somebody says what
    #: they were on back then.
    carried_without_terms: list[str] = field(default_factory=list)

    #: Empty means the figure can be approved as it stands.
    blockers: list[str] = field(default_factory=list)

    @property
    def is_payable(self) -> bool:
        return not self.is_house and not self.blockers


def not_settled_by_another_month(affiliate_id: int, month: str):
    """An order counts toward a month unless a **different** month paid it.

    Both halves matter, and each has a failure behind it.

    *Unless another month paid it*: once September's payroll has paid a late
    August order, reopening August must not offer that money again. Without
    this, August recalculates to include an order September already settled,
    and re-approving it agrees the same commission twice.

    *A different month, not any month*: an approved month's own orders are
    settled by its own snapshot, and they must keep counting - otherwise every
    approved month would recalculate to zero the moment it was agreed.
    """
    return ~(
        select(PayrollSnapshot.id)
        .join(PayrollMonth, PayrollSnapshot.payroll_month_id == PayrollMonth.id)
        .where(PayrollSnapshot.id == AttributedOrder.settled_in_snapshot_id)
        .where(PayrollMonth.affiliate_id == affiliate_id)
        .where(PayrollMonth.month != month)
        .exists()
    )


def carried_forward(db: Session, affiliate: AffiliateProfile, month: str) -> dict:
    """What this payroll owes on orders that arrived after their own month closed.

    §11.4, and the common path rather than an edge case: Egyptian
    cash-on-delivery routinely straddles month end, so an order placed on
    29 August may still be travelling when payroll runs on 5 September.

    **Each carried month is commissioned at its own rate.** The order is an
    August sale and §9.5 is firm that a rate change in September must not
    rewrite what August was worth, so the rate is resolved per source month
    rather than once for the payroll doing the paying.

    **Carried money never enters a base-guarantee comparison.** A guarantee is
    a floor under *this month's* work, and an order from a different month is
    not this month's work. It is added after the comparison, never inside it.

    Returned exact and undivided per month (ADR 0003): the caller sums these
    with everything else and rounds once, so a carried line cannot introduce a
    second rounding step of its own.
    """
    # Imported here rather than at module scope: `app.services.payroll` imports
    # this module, and the pair would not load.
    from app.services.payroll import carried_into

    orders = carried_into(db, affiliate, month)
    if not orders:
        return {
            "orders": 0,
            "base_piastres": 0,
            "exact": Decimal(0),
            "lines": [],
            "months_without_terms": [],
        }

    by_month: dict[str, dict] = {}
    for order in orders:
        line = by_month.setdefault(
            order.business_month,
            {"from_month": order.business_month, "orders": 0, "base_piastres": 0},
        )
        line["orders"] += 1
        line["base_piastres"] += order.commission_base_piastres

    lines = []
    without_terms = []
    total = Decimal(0)

    for from_month in sorted(by_month):
        line = by_month[from_month]
        terms = terms_for(db, affiliate, from_month)
        if terms is None:
            without_terms.append(from_month)
            continue

        exact = exact_commission_piastres(
            commission_numerator(line["base_piastres"], terms.commission_rate_bp)
        )
        total += exact
        lines.append(
            {
                **line,
                "commission_rate_bp": terms.commission_rate_bp,
                "commission_piastres": str(exact),
            }
        )

    return {
        "orders": sum(line["orders"] for line in lines),
        "base_piastres": sum(line["base_piastres"] for line in lines),
        "exact": total,
        "lines": lines,
        "months_without_terms": without_terms,
    }


def calculate_month(
    db: Session,
    affiliate: AffiliateProfile,
    month: str,
    *,
    policy: str = PENDING_INCLUSIVE,
) -> MonthCalculation:
    """What this month is worth under the live policy. F02.

    **Pending and delivered both count; a failed delivery does not.** This was
    delivered-only until the transition, and the two words in this docstring
    are the whole of the change: an order that has left the warehouse is a
    sale, and waiting for the courier to confirm it is not a reason to leave a
    model's own month looking smaller than it is.

    The reason it is safe to count a pending order is not that it always
    arrives — it is that the same order can never be counted twice. Approval
    settles every order it counted against its snapshot, `carried_forward`
    only pays orders an *earlier policy* left out, and a delivery that fails
    afterwards becomes a correction against the agreed figure rather than a
    silent rewrite of it (05C).

    ## `policy`, and the one caller that supplies it

    A month agreed before the transition must be *re-*calculated the way it
    was calculated: comparing a delivered-only agreement with a
    pending-inclusive recalculation reports the policy change itself as a
    difference, and would tell somebody a closed month is suddenly worth more.
    `corrections.correction_for` passes the snapshot's own recorded rule so
    that a comparison answers *has the evidence moved*, which is the only
    question it is asked.
    """
    return _calculate(db, affiliate, month, source_orders=None, policy=policy)


def preview_calculation(
    db: Session,
    affiliate: AffiliateProfile,
    month: str,
    *,
    source_orders: list[SourceOrder],
) -> MonthCalculation:
    """The same policy, computed from supplied source facts rather than rows.

    It exists for the reconciliation screen, which reads delivery state
    directly (`source_order`) so it can distinguish *failed* from *we have not
    been told*, and reports per-order issues no ledger column carries.

    Since the transition the **policy** is identical to `calculate_month` —
    pending and delivered count. What still differs is the source of the facts
    and the fact that this one never touches carry: it answers *what do this
    month's own orders come to*, which is the question a reconciliation asks.
    """
    return _calculate(db, affiliate, month, source_orders=source_orders)


def _calculate(
    db: Session,
    affiliate: AffiliateProfile,
    month: str,
    *,
    source_orders: list[SourceOrder] | None,
    policy: str = PENDING_INCLUSIVE,
) -> MonthCalculation:
    """Shared monthly terms, target qualification and aggregate-once arithmetic.

    Reads the source month's terms, not today's: a rate change in June must not
    silently rewrite April. Only the two named entry points select the policy.
    """
    parse_month(month)

    is_preview = source_orders is not None
    if source_orders is None:
        legacy_rows = list(
            db.scalars(
                select(AttributedOrder)
                .where(AttributedOrder.affiliate_id == affiliate.id)
                .where(AttributedOrder.business_month == month)
                .where(not_settled_by_another_month(affiliate.id, month))
            )
        )
        order_amounts = [
            (row.commission_state, row.commission_base_piastres)
            for row in legacy_rows
        ]
    else:
        order_amounts = [(row.state, row.base_piastres) for row in source_orders]

    earned_base = 0
    earned_count = 0
    pending_base = 0
    pending_count = 0
    void_count = 0

    for state, base in order_amounts:
        if state == CommissionState.EARNED:
            earned_count += 1
            earned_base += base
        elif state == CommissionState.PENDING:
            pending_count += 1
            pending_base += base
        elif state == CommissionState.VOID:
            # Equivalent to the old else for today's three real commission
            # states. Preview also supplies the pseudo-state "unavailable",
            # which is not a failed delivery. Revisit this classification when
            # adding a real fourth state; it must not silently disappear here.
            void_count += 1

    is_house = affiliate.account_kind == AccountKind.HOUSE
    blockers: list[str] = sorted({
        issue for row in (source_orders or []) for issue in row.issues
    })

    target = get_target(db, affiliate, month)
    achieved = target.is_achieved if target else None
    verified = bool(target and target.is_verified)
    guarantee_applied = False

    if is_preview:
        carried = {
            "orders": 0,
            "base_piastres": 0,
            "exact": Decimal(0),
            "lines": [],
            "months_without_terms": [],
        }
    else:
        carried = carried_forward(db, affiliate, month)
    if carried["months_without_terms"]:
        blockers.append(NO_TERMS_FOR_CARRIED)

    terms = terms_for(db, affiliate, month)
    if terms is None:
        # Sales are still real and still worth reporting; what they are owed is
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
            carried_orders=carried["orders"],
            carried_base_piastres=carried["base_piastres"],
            carried_piastres=carried["exact"],
            carried_lines=carried["lines"],
            carried_without_terms=carried["months_without_terms"],
            blockers=blockers,
        )

    # **F02: pending and delivered both count.** One numerator for the whole
    # month, divided once; summing per-order commissions would round each of
    # them first.
    #
    # Both entry points count the same way. The preview's numbers used to be
    # the only pending-inclusive ones in the platform, and the gap between
    # them was the defect: a model could be shown an entitlement on one screen
    # and paid a different figure from another.
    counted_base = earned_base + (
        pending_base if CommissionState.PENDING in counted_states_for(policy) else 0
    )
    numerator = (
        commission_numerator(counted_base, terms.commission_rate_bp)
        if counted_base
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
            # Nobody has recorded what they produced. Not a judgement about their
            # month - the platform simply does not know, and §11.3 blocks on
            # missing information.
            blockers.append(NO_TARGET)
        elif not achieved:
            # A confirmed miss. They are paid their commission, promptly, and the
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

    # §11.4. Added **after** the guarantee comparison, never inside it: a
    # guarantee is a floor under this month's work, and an order from an
    # earlier month is not this month's work. Rounding still happens once, on
    # the total (ADR 0004).
    exact = exact + carried["exact"]

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
        carried_orders=carried["orders"],
        carried_base_piastres=carried["base_piastres"],
        carried_piastres=carried["exact"],
        carried_lines=carried["lines"],
        carried_without_terms=carried["months_without_terms"],
        blockers=blockers,
    )
