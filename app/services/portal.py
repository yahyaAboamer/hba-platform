"""What a model sees about her own money.

§11.1, §11.4 and ADR 0014, from the other side of the screen.

**Nothing here calculates anything.** Every figure already exists: the engine
decided it in Phase 4, approval froze it in Phase 6, and this reads those
decisions. A second implementation of what she is owed would be a second answer
waiting to disagree with the first, and the one it disagreed with would be the
one she was paid.

## An agreed month is read from the snapshot, never recalculated

The whole month - the total, the commission line, the salary, every carried
line - comes out of `payload_json`, not out of `calculate_month`. Two reasons,
and the first has already caught us once.

`calculate_month` keeps moving after approval: an order settling in October
changes what September *would* come to and never what September *is*. A screen
showing the recalculation under the word "paid" would be presenting a working
number as a debt (§11.1), and on the maintainer's payroll screen it briefly
did.

The second reason is subtler, and is why the whole breakdown comes from the
payload rather than only the total: lines drawn from a live recalculation
underneath a frozen total would not add up. She is the one person guaranteed
to check.

## Blockers are translated, and none of them is her fault

Every blocker the platform can raise is HBA's own work - nobody has set her
rate, nobody has recorded her targets, nobody has confirmed them, an order
needs a decision. Not one is something she did, and
`targets_achieved_but_not_verified` in particular reads as an accusation when
it means the opposite: she hit them, and somebody here is slow.

So each one says whose move it is, and today every one of them says HBA. The
field is not decoration - it is what lets the screen tell her there is nothing
for her to do, which is the actual answer.

## No customer ever appears here

Not a filter, a fact: `attributed_order` and `order_index` hold no customer
name, address, phone or email, because §10.2's thin index never stored them.
The test asserting it stays that way is what keeps this structural.
"""

from dataclasses import asdict
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import parse_month
from app.core.money import format_egp
from app.models.affiliates import AffiliateProfile
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.compensation import CompensationType
from app.models.orders import OrderIndex
from app.models.payroll import CalculationState, PayrollMonth, PayrollSnapshot
from app.services.commission.calculate import MonthCalculation
from app.services.payroll import (
    blockers_for,
    get_month,
    historical_sales,
    is_historical,
    working_month,
)

#: What each blocker means to the person waiting on it, and whose move it is.
#:
#: `who` is `"hba"` for every one of them today. That is not an oversight -
#: §11.3 blocks on missing information, and all of the information missing is
#: information HBA records. The field exists so that a blocker which genuinely
#: is hers can say so without the others quietly changing meaning.
WAITING_ON: dict[str, dict[str, str]] = {
    "no_compensation_terms_for_this_month": {
        "who": "hba",
        "text": "HBA has not set what you are paid for this month yet.",
    },
    "no_target_recorded_for_this_month": {
        "who": "hba",
        "text": (
            "Nobody has recorded what you posted this month yet. HBA does "
            "that - if they have asked you for your numbers, sending them is "
            "what moves it along."
        ),
    },
    "targets_achieved_but_not_verified": {
        "who": "hba",
        "text": (
            "You hit your targets. Someone at HBA still has to confirm the "
            "numbers before your guaranteed minimum can apply."
        ),
    },
    "no_compensation_terms_for_a_carried_month": {
        "who": "hba",
        "text": (
            "An order from an earlier month is being paid with this one, and "
            "HBA has not set what you were on back then."
        ),
    },
    "orders_held_for_multi_code_review": {
        "who": "hba",
        "text": (
            "An order came in with more than one discount code on it. HBA "
            "decides which code it counts for before this month can close."
        ),
    },
    "go_live_month_is_not_configured": {
        "who": "hba",
        "text": "HBA has not opened the programme for this month yet.",
    },
}

#: Not blockers to her - states. "Already approved" is the good outcome, and
#: "settled before the platform" is what a historical month *is*. Showing
#: either under "waiting on" would turn a finished month into a stuck one.
NOT_HER_PROBLEM = frozenset(
    {
        "month_is_already_approved",
        "month_predates_the_platform",
        # A house account holds no user account and cannot sign in. Listed so
        # that one which somehow could would not render an empty screen.
        "house_accounts_are_never_owed",
    }
)

#: What each order state means to her. `void` matters most: §9.4 pays on
#: delivery, and an order that vanishes without a word looks like a mistake.
ORDER_STATE_TEXT = {
    CommissionState.EARNED: "Counted",
    CommissionState.PENDING: "On its way",
    CommissionState.VOID: "Did not arrive",
}


def _display_piastres(exact: Decimal | str | int) -> int:
    """One fractional-piastre line as whole piastres, **for reading only**.

    `Decimal`, never `float` (ADR 0002). The payout is rounded once, half-up,
    on the total alone (ADR 0004); this rounds a single line so it can be shown
    beside the others, and the total is never assembled from these. Where they
    do not add up, `_makeup` says so in a line of its own rather than leaving
    her to hunt for the gap.
    """
    return int(Decimal(exact).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _as_payload(calculation: MonthCalculation) -> dict:
    """A live calculation in the shape a snapshot stores it.

    So the rest of this module reads one shape rather than two - a snapshot's
    `payload_json` is `asdict(MonthCalculation)` with its Decimals written as
    strings, and a branch per field is a branch that drifts.
    """
    body = asdict(calculation)
    body["commission_piastres"] = str(calculation.commission_piastres)
    body["carried_piastres"] = str(calculation.carried_piastres)
    body["exact_unrounded_piastres"] = str(calculation.exact_unrounded_piastres)
    return body


def months_for(db: Session, affiliate: AffiliateProfile) -> list[str]:
    """Every month she can look at, newest first.

    From her first month to the working one. **Months before she joined are not
    offered at all** - the maintainer's picker shows the whole calendar because
    she is deciding which payroll to run, but a model opening a month that
    predates her would find an empty screen with no way to tell whether that
    meant nothing happened or something is broken.

    Her first month is the earliest month she has an order in or a payroll
    record for, whichever is earlier. Not her join date: an order can be
    attributed to a month before her profile row was created, and it is the
    orders she will be looking for.
    """
    earliest_order = db.scalar(
        select(AttributedOrder.business_month)
        .where(AttributedOrder.affiliate_id == affiliate.id)
        .order_by(AttributedOrder.business_month)
        .limit(1)
    )
    earliest_payroll = db.scalar(
        select(PayrollMonth.month)
        .where(PayrollMonth.affiliate_id == affiliate.id)
        .order_by(PayrollMonth.month)
        .limit(1)
    )

    working = working_month()
    known = [month for month in (earliest_order, earliest_payroll) if month]
    if not known:
        # New, or joined before any order landed. One month: the one she is in.
        return [working]

    first = min(known)
    if first > working:
        return [working]

    months: list[str] = []
    year, index = (int(part) for part in first.split("-"))
    cursor = f"{year:04d}-{index:02d}"
    # Bounded by real data at one end and by today at the other, so this cannot
    # run away. The cap is here because a mis-set go-live month is exactly the
    # sort of thing that makes a month-walking loop run to the heat death.
    while cursor <= working and len(months) < 120:
        months.append(cursor)
        index += 1
        if index == 13:
            year, index = year + 1, 1
        cursor = f"{year:04d}-{index:02d}"

    return list(reversed(months))


def _carried_out(db: Session, affiliate: AffiliateProfile, month: str) -> list[dict]:
    """Orders she sold in this month that a **later** payroll paid.

    The other half of §11.4, and the half only she needs. The maintainer sees
    carry-forward as money arriving in September; she sees it as money missing
    from August, because she counted August's orders herself and the total does
    not match.

    `calculate_month` deliberately excludes these from the month they were sold
    in - otherwise reopening August would offer money September already paid -
    so without this line her arithmetic cannot close.
    """
    rows = db.execute(
        select(AttributedOrder, PayrollMonth.month)
        .join(
            PayrollSnapshot,
            PayrollSnapshot.id == AttributedOrder.settled_in_snapshot_id,
        )
        .join(PayrollMonth, PayrollMonth.id == PayrollSnapshot.payroll_month_id)
        .where(AttributedOrder.affiliate_id == affiliate.id)
        .where(AttributedOrder.business_month == month)
        .where(PayrollMonth.month != month)
    ).all()

    by_month: dict[str, dict] = {}
    for order, paid_in in rows:
        line = by_month.setdefault(
            paid_in, {"to_month": paid_in, "orders": 0, "base_piastres": 0}
        )
        line["orders"] += 1
        line["base_piastres"] += order.commission_base_piastres

    return [
        {**by_month[key], "base": format_egp(by_month[key]["base_piastres"])}
        for key in sorted(by_month)
    ]


def _settled_months(
    db: Session, affiliate: AffiliateProfile, month: str
) -> dict[str, str]:
    """Which payroll paid each of this month's orders, keyed by order id."""
    rows = db.execute(
        select(AttributedOrder.shopify_order_id, PayrollMonth.month)
        .join(
            PayrollSnapshot,
            PayrollSnapshot.id == AttributedOrder.settled_in_snapshot_id,
        )
        .join(PayrollMonth, PayrollMonth.id == PayrollSnapshot.payroll_month_id)
        .where(AttributedOrder.affiliate_id == affiliate.id)
        .where(AttributedOrder.business_month == month)
    ).all()
    return {order_id: paid_in for order_id, paid_in in rows}


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _makeup(figures: dict, total_piastres: int) -> list[dict]:
    """What the total is made of, in lines that add up to it.

    The lines are display-rounded and the total is not assembled from them
    (ADR 0004 rounds once, on the total), so they can miss it by up to half a
    pound. Where they do, the difference gets a line of its own. A breakdown
    that silently does not sum is worse than no breakdown at all to the one
    person who is going to add it up.
    """
    lines: list[dict] = []

    commission = _display_piastres(figures.get("commission_piastres") or 0)
    rate_bp = figures.get("commission_rate_bp")
    earned = figures.get("earned_base_piastres") or 0

    if figures.get("guarantee_applied"):
        # §9.5. Never both, and never one on top of the other. Naming what it
        # replaced is the difference between a floor she understands and a
        # figure she cannot place.
        lines.append(
            {
                "label": "Your guaranteed minimum",
                "piastres": int(figures.get("base_amount_piastres") or 0),
                "detail": (
                    f"instead of your commission of {format_egp(commission)}, "
                    "which came to less this month"
                ),
            }
        )
    else:
        lines.append(
            {
                "label": "Commission on this month's sales",
                "piastres": commission,
                "detail": (
                    f"{rate_bp / 100:g}% of {format_egp(earned)}" if rate_bp else None
                ),
            }
        )

    if figures.get("compensation_type") == CompensationType.FIXED_PLUS_COMMISSION:
        lines.append(
            {
                "label": "Your monthly salary",
                "piastres": int(figures.get("fixed_piastres") or 0),
                "detail": None,
            }
        )

    for line in figures.get("carried_lines") or []:
        rate = line["commission_rate_bp"] / 100
        lines.append(
            {
                "label": f"Carried from {line['from_month']}",
                "piastres": _display_piastres(line["commission_piastres"]),
                "detail": (
                    f"{_plural(line['orders'], 'order')} that arrived after "
                    f"{line['from_month']} closed, at {rate:g}% - that month's "
                    "rate, not this one's"
                ),
            }
        )

    difference = total_piastres - sum(line["piastres"] for line in lines)
    if difference:
        lines.append(
            {
                "label": "Rounded to the nearest pound",
                "piastres": difference,
                "detail": None,
            }
        )

    return [{**line, "amount": format_egp(line["piastres"])} for line in lines]


def _guarantee(figures: dict) -> dict | None:
    """Her guaranteed minimum, and why it is or is not in the figure above.

    Only on a `base_guarantee` arrangement, and **present whether or not it
    applied** - which is the whole point. A month where her targets have not
    been recorded pays her commission, because §9.5's comparison has no answer
    without them. Sara's September looked like this: a guaranteed minimum of
    E£8,000, a commission of E£1,100, and a screen showing E£1,100 with no
    mention of the guarantee at all.

    Nothing was wrong with the figure. What was wrong was that the one number
    she signed for did not appear on the screen, so the honest reading of it
    was *they have forgotten my minimum*.
    """
    if figures.get("compensation_type") != CompensationType.BASE_GUARANTEE:
        return None

    amount = int(figures.get("base_amount_piastres") or 0)
    return {
        "piastres": amount,
        "amount": format_egp(amount),
        "applied": bool(figures.get("guarantee_applied")),
        # §15. Three answers, not two. `null` means nobody has recorded what
        # she produced - a different thing from missing the target, and the
        # difference decides which sentence she should be reading.
        "targets_achieved": figures.get("target_achieved"),
        "targets_verified": bool(figures.get("target_verified")),
    }


def my_month(db: Session, affiliate: AffiliateProfile, month: str) -> dict:
    """One of her months: what it is worth, and whether that is settled.

    Three shapes, and which one she gets is the most important thing on the
    screen (§11.1).

    *Historical* - before go-live. Her sales are real and there is no
    commission figure, because March's rates live in the old system and in
    somebody's memory (ADR 0014). Shown with the reason attached: an empty
    commission on a month full of sales reads as *HBA did not pay me for
    March*, which is the opposite of true.

    *Open* - still moving. Orders are still arriving and the figure will
    change.

    *Agreed* - frozen. This is what she is owed, and it does not move again.
    """
    parse_month(month)
    working = working_month()

    if is_historical(month):
        sales = historical_sales(db, affiliate, month)
        return {
            "month": month,
            "state": "historical",
            "is_working_month": month == working,
            "sales": {
                "earned_piastres": sales["net_sales_piastres"],
                "earned": format_egp(sales["net_sales_piastres"]),
                "pending_piastres": 0,
                "pending": format_egp(0),
            },
            "orders": {"earned": sales["orders"], "pending": 0, "void": 0},
            "amount_piastres": None,
            "amount": None,
            "makeup": [],
            "carried_in": [],
            "carried_out": [],
            "guarantee_applied": False,
            "guarantee": None,
            "commission_rate_bp": None,
            "waiting_on": [],
            "note": (
                "This month was settled before HBA started using this system. "
                "Your sales are here; what you were paid for them was agreed "
                "the old way, and this page will not invent a figure it was "
                "never told."
            ),
        }

    blockers, calculation = blockers_for(db, affiliate, month)
    payroll_month = get_month(db, affiliate, month)
    snapshot = payroll_month.active_snapshot if payroll_month else None
    agreed = (
        payroll_month is not None
        and payroll_month.calculation_state == CalculationState.APPROVED
        and snapshot is not None
    )

    # An agreed month comes out of the snapshot in full - total *and* lines.
    # See the module docstring: a live recalculation underneath a frozen total
    # is a breakdown that does not add up.
    figures = snapshot.payload_json if agreed else _as_payload(calculation)
    total = (
        snapshot.approved_obligation_piastres if agreed else calculation.payout_piastres
    )

    return {
        "month": month,
        "state": "agreed" if agreed else "open",
        "is_working_month": month == working,
        "sales": {
            "earned_piastres": figures["earned_base_piastres"],
            "earned": format_egp(figures["earned_base_piastres"]),
            # Shown, never hidden. Hiding an order still in transit makes her
            # month look smaller than it is, and produces exactly the question
            # this platform exists to stop her having to ask.
            "pending_piastres": figures["pending_base_piastres"],
            "pending": format_egp(figures["pending_base_piastres"]),
        },
        "orders": {
            "earned": figures["earned_orders"],
            "pending": figures["pending_orders"],
            "void": figures["void_orders"],
        },
        "amount_piastres": total,
        "amount": format_egp(total),
        "makeup": _makeup(figures, total),
        "carried_in": [
            {
                "from_month": line["from_month"],
                "orders": line["orders"],
                "base_piastres": line["base_piastres"],
                "base": format_egp(line["base_piastres"]),
                "commission_rate_bp": line["commission_rate_bp"],
                "piastres": _display_piastres(line["commission_piastres"]),
                "amount": format_egp(_display_piastres(line["commission_piastres"])),
            }
            for line in (figures.get("carried_lines") or [])
        ],
        "carried_out": _carried_out(db, affiliate, month),
        "guarantee_applied": bool(figures.get("guarantee_applied")),
        "guarantee": _guarantee(figures),
        "commission_rate_bp": figures.get("commission_rate_bp"),
        # Nothing blocks a month that is already agreed. The live blocker list
        # keeps answering "could this be approved *now*", and after approval
        # that question has a stale answer: unverifying a target in October
        # would otherwise put "someone still has to confirm your numbers" on
        # top of a month she was paid for in September.
        "waiting_on": (
            []
            if agreed
            else [
                WAITING_ON[key]
                for key in blockers
                if key not in NOT_HER_PROBLEM and key in WAITING_ON
            ]
        ),
        "note": None,
    }


def my_orders(db: Session, affiliate: AffiliateProfile, month: str) -> list[dict]:
    """The orders behind the figure, so she can count them against her own list.

    Order number, date, what it was worth to her, whether it counts, and which
    payroll paid it. **No customer appears** - not because anything is filtered
    here, but because §10.2's index never stored a name, an address or a phone
    number in the first place.

    Joined to `order_index` for the number and the date: the attributed row
    carries neither, and `shopify_order_id` is an internal identifier that
    means nothing to anybody outside the database.
    """
    parse_month(month)
    settled = _settled_months(db, affiliate, month)

    rows = db.execute(
        select(AttributedOrder, OrderIndex)
        .join(
            OrderIndex,
            OrderIndex.shopify_order_id == AttributedOrder.shopify_order_id,
        )
        .where(AttributedOrder.affiliate_id == affiliate.id)
        .where(AttributedOrder.business_month == month)
        .order_by(OrderIndex.placed_at.desc())
    ).all()

    return [
        {
            "order_number": index.order_number,
            "placed_at": index.placed_at.isoformat(),
            "base_piastres": order.commission_base_piastres,
            "base": format_egp(order.commission_base_piastres),
            "state": order.commission_state,
            "state_text": ORDER_STATE_TEXT.get(
                order.commission_state, order.commission_state
            ),
            "delivered_at": (
                order.delivered_at.isoformat() if order.delivered_at else None
            ),
            # §11.4. Named only when a *different* month paid it - an order
            # settled by its own month needs no explanation, and labelling
            # every row would bury the two that matter.
            "paid_in_month": (
                settled.get(order.shopify_order_id)
                if settled.get(order.shopify_order_id) != month
                else None
            ),
        }
        for order, index in rows
    ]
