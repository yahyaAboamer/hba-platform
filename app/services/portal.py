"""What a model sees about their own money.

§11.1, §11.4 and ADR 0014, from the other side of the screen.

**Nothing here calculates anything.** Every figure already exists: the engine
decided it in Phase 4, approval froze it in Phase 6, and this reads those
decisions. A second implementation of what they are owed would be a second answer
waiting to disagree with the first, and the one it disagreed with would be the
one they were paid.

## An agreed month's money is read from the snapshot, never recalculated

The money - the total, the commission line, the salary, every carried line -
comes out of `payload_json`, not out of `calculate_month`. Two reasons, and
the first has already caught us once.

`calculate_month` keeps moving after approval: an order settling in October
changes what September *would* come to and never what September *is*. A screen
showing the recalculation under the word "paid" would be presenting a working
number as a debt (§11.1), and on the maintainer's payroll screen it briefly
did.

The second reason is subtler, and is why the whole breakdown comes from the
payload rather than only the total: lines drawn from a live recalculation
underneath a frozen total would not add up. They are the one person guaranteed
to check.

**Her sales and order counts are the opposite case** (F13). Those describe
what happened in the month, not what she is owed for it, and a parcel refused
in November did happen - to September. So the counts, the sales figure and the
chart come from the month as it is now, while the agreed total beside them
does not move. A failure after approval is settled as a correction against the
agreement (05C), never by quietly restating what the agreement said.

## Blockers are translated, and none of them is their fault

Every blocker the platform can raise is HBA's own work - nobody has set their
rate, nobody has recorded their targets, nobody has confirmed them, an order
needs a decision. Not one is something they did, and
`targets_achieved_but_not_verified` in particular reads as an accusation when
it means the opposite: they hit them, and somebody here is slow.

So each one says whose move it is, and today every one of them says HBA. The
field is not decoration - it is what lets the screen tell them there is nothing
for them to do, which is the actual answer.

## No customer ever appears here

Not a filter, a fact: `attributed_order` and `order_index` hold no customer
name, address, phone or email, because §10.2's thin index never stored them.
The test asserting it stays that way is what keeps this structural.
"""

from dataclasses import asdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import (
    business_date,
    business_month,
    month_add,
    parse_month,
    utcnow,
)
from app.core.money import (
    commission_numerator,
    exact_commission_piastres,
    format_egp,
)
from app.core.periods import PLATFORM_START_MONTH
from app.models.affiliates import AffiliateProfile
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.catalogue import OrderLineItem
from app.models.compensation import CompensationType
from app.models.orders import OrderIndex
from app.models.payments import (
    AdjustmentType,
    PaymentAllocation,
    PaymentTransaction,
    PayrollAdjustment,
)
from app.models.targets import MonthlyTarget
from app.models.payroll import CalculationState, PayrollMonth, PayrollSnapshot
from app.services.commission.base import commission_base
from app.services.commission.calculate import (
    PENDING_INCLUSIVE,
    MonthCalculation,
    counted_sales_from,
    counted_states_for,
    source_month_sales,
)
from app.services.compensation import all_terms, terms_for
from app.services.payments import adjustments_for, balance_for, payments_for
from app.services.performance import uses_for
from app.services.payments_state import SettlementState
from app.services.commission.state import ORDER_STATUS_TEXT, order_status
from app.services.payroll import (
    counted_in_snapshot,
    blockers_for,
    get_month,
    is_historical,
    policy_of,
    snapshots_for,
    working_month,
)
from app.services.targets import get_target

#: What each blocker means to the person waiting on it, and whose move it is.
#:
#: `who` is `"hba"` for every one of them today. That is not an oversight -
#: §11.3 blocks on missing information, and all of the information missing is
#: information HBA records. The field exists so that a blocker which genuinely
#: is theirs can say so without the others quietly changing meaning.
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

#: Not blockers to them - states. "Already approved" is the good outcome, and
#: showing it under "waiting on" would turn a finished month into a stuck one.
#:
#: `month_predates_the_platform` was here too, until ADR 0036 removed the
#: blocker itself. Those months are approved like any other now.
NOT_HER_PROBLEM = frozenset(
    {
        "month_is_already_approved",
        # A house account holds no user account and cannot sign in. Listed so
        # that one which somehow could would not render an empty screen.
        "house_accounts_are_never_owed",
    }
)


def _display_piastres(exact: Decimal | str | int) -> int:
    """One fractional-piastre line as whole piastres, **for reading only**.

    `Decimal`, never `float` (ADR 0002). The payout is rounded once, half-up,
    on the total alone (ADR 0004); this rounds a single line so it can be shown
    beside the others, and the total is never assembled from these. Where they
    do not add up, `_makeup` says so in a line of its own rather than leaving
    them to hunt for the gap.
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


def _months_between(first: str, working: str) -> list[str]:
    """Every month from `first` to `working` inclusive, newest first.

    Bounded at both ends by real values, so it cannot run away - and capped
    anyway, because a mis-set go-live month is exactly the sort of thing that
    makes a month-walking loop run to the heat death.
    """
    months: list[str] = []
    year, index = (int(part) for part in first.split("-"))
    cursor = f"{year:04d}-{index:02d}"
    while cursor <= working and len(months) < 120:
        months.append(cursor)
        index += 1
        if index == 13:
            year, index = year + 1, 1
        cursor = f"{year:04d}-{index:02d}"

    return list(reversed(months))


def months_for(db: Session, affiliate: AffiliateProfile) -> list[str]:
    """Every month they can look at, newest first.

    From their first month to the working one. **Months before they joined are not
    offered at all** - the maintainer's picker shows the whole calendar because
    they are deciding which payroll to run, but a model opening a month that
    predates them would find an empty screen with no way to tell whether that
    meant nothing happened or something is broken.

    ## Which month is her first

    **Her recorded collaboration start, when there is one.** That is the fact
    rule H01 is about: the month she actually began with HBA, entered by
    somebody who knows, because nothing derives it.

    When there is not one, the old derivation stands: the earliest month she
    has an attributed order or a payroll record in. It is a good guess and it
    is a different fact - it answers *when did money first appear* rather than
    *when did she start*. The two usually agree. When they do not, the
    derivation hides a month she was here for and sold nothing in, and H01 says
    that month should be visible and empty rather than absent.

    So the recorded value wins outright where it exists, **even when it is
    later than her first order**. An order attributed to a month before she
    started is a matching error, not a reason to open that month to her; the
    diagnostics for that live on the maintainer's side, not in her picker.

    One floor and one ceiling either way. Nothing before `PLATFORM_START_MONTH`,
    because there are no orders there to show, and nothing after the working
    month, because it has not happened.
    """
    recorded = affiliate.collaboration_start_month
    if recorded:
        working = working_month()
        first = max(recorded, PLATFORM_START_MONTH)
        if first > working:
            return [working]
        return _months_between(first, working)

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
        # New, or joined before any order landed. One month: the one they are in.
        return [working]

    first = min(known)
    if first > working:
        return [working]

    return _months_between(first, working)


def _not_started(month: str) -> bool:
    """Whether this month has not begun yet.

    Before go-live, `working_month()` opens every screen on the go-live month -
    which is right, because an empty August is a useless first impression when
    the platform starts in September. For the maintainer that month is
    something to get ready. For a model invited on the 31st of August it is a
    month with nothing in it, and *Still adding up - E0.00* is a poor first
    thing to see from a platform they have just been told to trust.

    Compared against the real business month in Cairo (ADR 0005), never the
    browser's clock: a model in another timezone must not be told their month has
    not started when it has.
    """
    return month > business_month(utcnow())


def _average_order(figures: dict) -> int | None:
    """What a counted order under their code was worth, on average.

    Counted orders only - delivered and pending since F02, never a failed
    delivery, which earned nothing and would drag the figure toward a number
    describing no order she actually made.

    `None` at zero counted orders, never zero: the difference between *your
    average order is worth nothing* and *there is nothing to average yet*.

    Kept for the statement path, which reads a snapshot's frozen figures.
    `my_month` averages her live source-month sales instead (R3).
    """
    orders = (figures.get("earned_orders") or 0) + (figures.get("pending_orders") or 0)
    if not orders:
        return None
    base = (figures.get("earned_base_piastres") or 0) + (
        figures.get("pending_base_piastres") or 0
    )
    return round(base / orders)


def _window(month: str, agreed: bool) -> dict:
    """When the month opens, when it closes, and how far through it is.

    **The second question had no answer.** The first thing a model wants is
    *how much*; the second is *when does it land*. A figure captioned "still
    adding up", with no closing date anywhere near it, reads as a number that
    might keep moving for ever - and the walkthrough said exactly that.

    Dates are Cairo's (ADR 0005), never the browser's. A model travelling, or
    one of HBA's people looking at this from another timezone, must not be
    told a month closes a day early.

    Facts only - no words. Every other sentence on this screen is written in
    `MyMonth.tsx` next to the thing it describes, and a date phrased here
    would be the one piece of its copy that had to be changed in Python.

    An **agreed** month is finished by definition, whatever the calendar says.
    Approval is what ends it, so the progress line is full and there are no
    days left even in the case where somebody approves early.
    """
    start = date(int(month[:4]), int(month[5:7]), 1)
    # The first of next month, minus a day. Correct in February and in
    # December, which is more than can be said for a table of month lengths.
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    span = (end - start).days + 1
    today = business_date(utcnow())

    if agreed or today > end:
        return {
            "opens": start.isoformat(),
            "closes": end.isoformat(),
            "progress_pct": 100,
            "days_left": None,
        }

    # `+ 1` because a month is one day through on its first day, not none.
    elapsed = 0 if today < start else (today - start).days + 1
    return {
        "opens": start.isoformat(),
        "closes": end.isoformat(),
        "progress_pct": round(100 * elapsed / span),
        "days_left": (end - today).days if today >= start else span,
    }


def _carried_out(db: Session, affiliate: AffiliateProfile, month: str) -> list[dict]:
    """Orders they sold in this month that a **later** payroll paid.

    The other half of §11.4, and the half only they need. The maintainer sees
    carry-forward as money arriving in September; they see it as money missing
    from August, because they counted August's orders themselves and the total does
    not match.

    `calculate_month` deliberately excludes these from the month they were sold
    in - otherwise reopening August would offer money September already paid -
    so without this line their arithmetic cannot close.
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


def _makeup(figures: dict, total_piastres: int, policy: str = PENDING_INCLUSIVE) -> list[dict]:
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
    # The sales this commission is a percentage **of**, under the rule that
    # produced it - delivered and pending since F02, and delivered only on a
    # month agreed before the switch. Naming the delivered total beside a
    # commission worked out on more than that is a breakdown that does not add
    # up.
    earned = counted_sales_from(figures, policy)

    if figures.get("guarantee_applied"):
        # §9.5. Never both, and never one on top of the other. Naming what it
        # replaced is the difference between a floor they understand and a
        # figure they cannot place.
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
    """Their guaranteed minimum, and why it is or is not in the figure above.

    Only on a `base_guarantee` arrangement, and **present whether or not it
    applied** - which is the whole point. A month where their targets have not
    been recorded pays their commission, because §9.5's comparison has no answer
    without them. Sara's September looked like this: a guaranteed minimum of
    EGP 8,000, a commission of EGP 1,100, and a screen showing EGP 1,100 with no
    mention of the guarantee at all.

    Nothing was wrong with the figure. What was wrong was that the one number
    they signed for did not appear on the screen, so the honest reading of it
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
        # they produced - a different thing from missing the target, and the
        # difference decides which sentence they should be reading.
        "targets_achieved": figures.get("target_achieved"),
        "targets_verified": bool(figures.get("target_verified")),
    }


def my_month(db: Session, affiliate: AffiliateProfile, month: str) -> dict:
    """One of their months: what it is worth, and whether that is settled.

    Three shapes, and which one they get is the most important thing on the
    screen (§11.1).

    *Open* - still moving. Orders are still arriving and the figure will
    change.

    *Agreed* - frozen. This is what they are owed, and it does not move again.

    *Historical* - **the fallback, and no longer the normal shape of an old
    month.** ADR 0036 gave the months before go-live compensation terms of
    their own, so March is calculated, approved and frozen exactly like August
    and comes back here as *agreed*. The business's reason for wanting that:
    *"I don't want the models to feel that we treated them differently."*

    This branch is what is left when that has not happened yet - a month before
    go-live whose terms nobody has entered, which cannot be calculated and must
    not be guessed at. It shows the sales, which are real, and says why the
    amount is absent. ADR 0036 kept it deliberately as the fallback where a
    model's historical rates genuinely cannot be established.
    """
    parse_month(month)
    working = working_month()

    # Read before the branch below, because *has this month been agreed* is now
    # what decides which shape it takes - not when it happened.
    payroll_month = get_month(db, affiliate, month)
    snapshot = payroll_month.active_snapshot if payroll_month else None
    agreed = (
        payroll_month is not None
        and payroll_month.calculation_state == CalculationState.APPROVED
        and snapshot is not None
    )

    if is_historical(month) and not agreed:
        # **A normal month with one thing missing.** The business asked for
        # this and was right: the orders are real, the counting is real, only
        # the *payment* happened elsewhere. Reporting one lump of sales and
        # nothing else made a month they worked look like a month that did not
        # happen.
        #
        # So the states are counted the same way they are in any other month,
        # from the same rows, and only the commission figure is withheld -
        # because March's rates live in the old system and guessing at them is
        # how somebody is told the wrong number (ADR 0014).
        rows = list(
            db.scalars(
                select(AttributedOrder)
                .where(AttributedOrder.affiliate_id == affiliate.id)
                .where(AttributedOrder.business_month == month)
            )
        )
        counted = [r for r in rows if r.commission_state == CommissionState.EARNED]
        travelling = [r for r in rows if r.commission_state == CommissionState.PENDING]
        gone = [r for r in rows if r.commission_state == CommissionState.VOID]
        earned_base = sum(r.commission_base_piastres for r in counted)
        pending_base = sum(r.commission_base_piastres for r in travelling)
        failed_base = sum(r.commission_base_piastres for r in gone)

        return {
            "month": month,
            "state": "historical",
            #: R3: the historical shape counts delivered and pending too.
            "policy": PENDING_INCLUSIVE,
            "is_working_month": month == working,
            "not_started": False,
            "sales": {
                # R3. The same shape as any other month, counted the same way
                # (F02): what she sold is not a question the platform answers
                # differently either side of go-live. Only the commission is
                # withheld, because those rates live in the old system.
                "counted_piastres": earned_base + pending_base,
                "counted": format_egp(earned_base + pending_base),
                "counted_orders": len(counted) + len(travelling),
                "earned_piastres": earned_base,
                "earned": format_egp(earned_base),
                "pending_piastres": pending_base,
                "pending": format_egp(pending_base),
                "failed_piastres": failed_base,
                "failed": format_egp(failed_base),
            },
            "orders": {
                "earned": len(counted),
                "pending": len(travelling),
                "void": len(gone),
                "counted": len(counted) + len(travelling),
                # A08. **The same figure a month after go-live gets.** Her code
                # uses are a fact about her orders, and her orders are in the
                # index either side of the line - only the commission was
                # agreed elsewhere (ADR 0014). Leaving it out here made the
                # card say "—" for a month it could answer perfectly well.
                "uses": uses_for(db, affiliate, month),
            },
            "amount_piastres": None,
            "amount": None,
            "makeup": [],
            "carried_in": [],
            "carried_out": [],
            "guarantee_applied": False,
            "guarantee": None,
            "targets": None,
            "commission_rate_bp": None,
            "waiting_on": [],
            # Their words, not the platform's. They do not know or care what a
            # platform is, and the earlier version's blank read as *they did
            # not pay me for June*.
            "note": (
                "HBA paid you for this month before this page existed, so the "
                "amount is not shown here — but everything you sold is."
            ),
        }

    blockers, calculation = blockers_for(db, affiliate, month)

    # An agreed month's **money** comes out of the snapshot in full - total
    # *and* lines. See the module docstring: a live recalculation underneath a
    # frozen total is a breakdown that does not add up.
    figures = snapshot.payload_json if agreed else _as_payload(calculation)
    total = (
        snapshot.approved_obligation_piastres if agreed else calculation.payout_piastres
    )

    # **Her performance is not frozen, and never was** (F13).
    #
    # What she earned in September is settled: it was agreed, it is owed, and
    # an order failing in November does not reach back and change it. What she
    # *sold* in September is a fact about September that the November delivery
    # failure corrects — the parcel did not arrive, so the sale did not stand,
    # and her sales figure and her chart say so.
    #
    # Reading both out of the snapshot conflated the two: a failed order left
    # no trace anywhere she could see, and the month's own graph went on
    # showing a sale that had been reversed. The money stays where it is; the
    # counts come from the month as it is now.
    #
    # **Read from the month's own orders, not from the payment calculation**
    # (R3). That calculation leaves out an order a different month's payroll
    # settled - it must, or the transition would pay one twice - and that is a
    # fact about which payroll paid rather than about when she sold. Reading
    # her performance out of it made an August sale disappear from August
    # because September's payroll happened to settle it.
    performance = source_month_sales(db, affiliate, month)
    average_order = (
        round(performance.counted_piastres / performance.counted_orders)
        if performance.counted_orders
        else None
    )

    return {
        "month": month,
        "state": "agreed" if agreed else "open",
        #: The counting rule behind the figure: the snapshot's own on an
        #: agreed month, so a month agreed delivered-only (before ADR 0040)
        #: is described as it was agreed, and the live rule otherwise.
        "policy": policy_of(snapshot) if agreed else PENDING_INCLUSIVE,
        "is_working_month": month == working,
        # A month the calendar has not reached. Distinct from "open with no
        # sales yet", which is the same figures and a completely different
        # sentence.
        "not_started": _not_started(month),
        "sales": {
            # **What the month is paid on** (F02, R3): delivered and pending
            # together. Her Home screen says *net sales counted*, and it said
            # the delivered part of it while the money was worked out on both
            # - a card that disagreed with the figure above it.
            "counted_piastres": performance.counted_piastres,
            "counted": format_egp(performance.counted_piastres),
            "counted_orders": performance.counted_orders,
            # The two halves of that, kept separate. *Counted* is the money;
            # these say how far along it is, and her screen shows both.
            "earned_piastres": performance.delivered_piastres,
            "earned": format_egp(performance.delivered_piastres),
            # Shown, never hidden. Hiding an order still in transit makes their
            # month look smaller than it is, and produces exactly the question
            # this platform exists to stop their having to ask.
            "pending_piastres": performance.pending_piastres,
            "pending": format_egp(performance.pending_piastres),
            # A failed delivery counts for nothing and is still worth saying:
            # it is the difference she will otherwise try to reconcile.
            "failed_piastres": performance.failed_piastres,
            "failed": format_egp(performance.failed_piastres),
            # **What a typical order under their code is worth.** Their own
            # figure, and one they cannot work out from anything else on the
            # screen without dividing two numbers in their head.
            #
            # `None` rather than zero at no counted orders: a zero here is a
            # claim that their average order is worth nothing, and the truth
            # is that there is nothing yet to average.
            "average_order_piastres": average_order,
            "average_order": (
                format_egp(average_order) if average_order is not None else None
            ),
        },
        "window": _window(month, agreed),
        "orders": {
            "earned": performance.delivered_orders,
            "pending": performance.pending_orders,
            "void": performance.failed_orders,
            "counted": performance.counted_orders,
            # **How often her code was used** (M01, and D03 for what counts).
            #
            # Not derivable from the three counts beside it, which is why it is
            # its own figure rather than a sum. Those are *commission* states,
            # and a use is a **delivery** outcome: an order delivered and later
            # refunded pays nothing and is still a use, while a parcel refused
            # at the door is neither. Adding earned and pending would be wrong
            # in both directions at once.
            "uses": uses_for(db, affiliate, month),
        },
        "amount_piastres": total,
        "amount": format_egp(total),
        "makeup": _makeup(
            figures, total, policy_of(snapshot) if agreed else PENDING_INCLUSIVE
        ),
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
        "targets": _targets(db, affiliate, month, figures),
        "commission_rate_bp": figures.get("commission_rate_bp"),
        # Nothing blocks a month that is already agreed. The live blocker list
        # keeps answering "could this be approved *now*", and after approval
        # that question has a stale answer: unverifying a target in October
        # would otherwise put "someone still has to confirm your numbers" on
        # top of a month they were paid for in September.
        "waiting_on": (
            []
            if agreed
            else [
                WAITING_ON[key]
                for key in blockers
                if key not in NOT_HER_PROBLEM and key in WAITING_ON
            ]
        ),
        # §16, Phase 10 Batch C. Frozen on the snapshot at approval, so this
        # names the rules this month was actually calculated under - never
        # the current ones, which may have changed since. `None` for an open
        # month: nothing has been frozen yet to name.
        "policy_version": (
            {
                "id": snapshot.policy_version_id,
                "effective_month": snapshot.policy_version.effective_month,
            }
            if agreed and snapshot.policy_version_id is not None
            else None
        ),
        # **A figure that changed after it was agreed says so.**
        #
        # A settled month is meant to be final, so when a correction moves one
        # the model has already been told about, the number quietly becoming a
        # different number is the worst possible way for them to find out.
        # These two facts are deliberately separate sentences on separate
        # months, because they are separate things: one month was recalculated,
        # and a *different* month is carrying money that did not come from it.
        # Explaining both on the later month would leave the earlier one
        # showing a changed figure with nothing attached to it.
        "recalculated": _recalculated(db, payroll_month) if agreed else None,
        "credited_from": _credited_from(db, affiliate, payroll_month),
        "note": None,
    }


def _recalculated(db: Session, payroll_month: PayrollMonth | None) -> dict | None:
    """What this month was worth before it was reopened, if it ever was.

    More than one snapshot means it was agreed, reopened and agreed again. The
    first figure is what the model was originally told; the last is what stands
    now. Both are needed - "it changed" without the old number is not something
    anybody can check against their own record.
    """
    if payroll_month is None:
        return None

    versions = snapshots_for(db, payroll_month)
    if len(versions) < 2:
        return None

    previous, latest = versions[-2], versions[-1]
    if previous.approved_obligation_piastres == latest.approved_obligation_piastres:
        # Reopened and re-approved at the same figure - a correction that
        # turned out to change nothing they are owed. Saying "this was
        # recalculated" over an unchanged number invites a question with no
        # answer.
        return None

    return {
        "was_piastres": previous.approved_obligation_piastres,
        "now_piastres": latest.approved_obligation_piastres,
        "at": latest.approved_at.isoformat() if latest.approved_at else None,
    }


def _credited_from(
    db: Session, affiliate: AffiliateProfile, payroll_month: PayrollMonth | None
) -> list[dict]:
    """An earlier month's overpayment being recovered out of this one.

    ## The sentence is written here, not in the browser

    05C, and it matters more than it looks. **D04 (10 September 2026): a
    carried overpayment consumes a later month's whole payable, below a
    guaranteed minimum if it has to.** So a model can open a month she met her
    targets in, in which she is owed nothing at all, and the only thing
    standing between that and a support message is this sentence.

    It also used to be the wrong sentence. The screen said *includes EGP 9,000
    from August*, which reads as money **added** to the month - the exact
    opposite of what is happening. She already received it; that is why nothing
    is being sent now.

    The wording lives in the service because §11.5 requires an adjustment to be
    visible to the person it was made about - *a credit she cannot see is a
    credit she cannot check* - and a figure the browser assembles is one no
    test here can hold to account.
    """
    if payroll_month is None:
        return []

    return [
        {
            "month": adjustment.source_month.month,
            "piastres": adjustment.amount_piastres,
            # Her words, and the direction stated outright. "Carried" and
            # "credited" are the ledger's words for this and both read to a
            # person as money arriving.
            "text": (
                f"{format_egp(adjustment.amount_piastres)} of this month goes "
                f"to repay {_month_words(adjustment.source_month.month)}, "
                "which was paid before an order from it was refused. You were "
                "sent that money at the time, so it is not being sent again."
            ),
        }
        for adjustment in adjustments_for(db, affiliate)
        if adjustment.destination_payroll_month_id == payroll_month.id
    ]



def _placed_value(order: AttributedOrder, index: OrderIndex) -> int | None:
    """What the customer's order came to when it was placed, if that differs.

    Only where the commission base has lost it. A cancelled order comes back
    from Shopify worth nothing (§9.3 pays on the current totals, deliberately),
    and a screen with no other figure to show was printing a struck-through
    zero - which claims the order was worth nothing *and* was cancelled, and is
    not a fact about anything.

    `None` where the base already tells the story, so no screen can end up
    showing the same money twice under two labels. `None` too on a row indexed
    before `original_total_piastres` existed: that is *we never asked*, not
    *it was free*.
    """
    if order.commission_base_piastres > 0:
        return None
    if index.original_total_piastres is None:
        return None

    placed = commission_base(
        index.original_total_piastres,
        index.shipping_piastres,
        index.tax_piastres,
    )
    return placed or None


def _forgone_commission(
    value: int | None, rate_bp: int | None, state: str
) -> int | None:
    """What a void order would have earned, had it arrived.

    Only on a void row, and only where a value survived: the base a failed
    delivery keeps (F03), or the placed-at figure of a cancelled order whose
    base Shopify zeroed. A model matching a void order against her own record
    wants the figure she *would* have had - the business asked for it
    explicitly, struck through rather than replaced by the words "nothing
    earned", which is how the approved portal draws a failed delivery.

    **Never paid, never summed.** It is the same arithmetic as a counted
    order applied to a sale that did not complete, and no total on any screen
    includes it. `None` on an order that is still travelling: that one has not
    lost anything yet.
    """
    if state != CommissionState.VOID or not rate_bp or not value:
        return None
    exact = exact_commission_piastres(commission_numerator(value, rate_bp))
    return int(exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP)) or None


def month_rule(
    db: Session, affiliate: AffiliateProfile, month: str
) -> tuple[int | None, tuple[str, ...], PayrollSnapshot | None]:
    """The rate one month's orders are worth, which states it counts, and the
    agreement they were counted in, if the month has one.

    **An agreed month answers from its snapshot** - the rate it was approved at
    and the counting rule it was approved under (`policy_of`) - so nothing
    about a frozen month is read from anything that can still be edited. Any
    other month is on its own terms and the live rule. Shared by her orders
    and the staff order view, so one order cannot tell two stories.
    """
    payroll_month = get_month(db, affiliate, month)
    snapshot = (
        payroll_month.active_snapshot
        if payroll_month is not None
        and payroll_month.calculation_state == CalculationState.APPROVED
        else None
    )
    if snapshot is not None:
        return (
            (snapshot.payload_json or {}).get("commission_rate_bp"),
            counted_states_for(policy_of(snapshot)),
            snapshot,
        )
    terms = terms_for(db, affiliate, month)
    return (
        terms.commission_rate_bp if terms else None,
        counted_states_for(PENDING_INCLUSIVE),
        None,
    )


def _order_commission(
    base: int, rate_bp: int | None, state: str, counted: tuple[str, ...]
) -> int | None:
    """What one counted order was worth in commission, to the whole piastre.

    **Counted is the month's own rule** (F02, ADR 0040): delivered and pending
    under the live policy, delivered only on a month agreed before it. An
    order on its way is paid with its month, so its row says what it is
    worth - the owner asked for exactly that.

    `None` where there is no answer: a void order never earned anything (its
    struck-through figure is `_forgone_commission`), a pending order on a
    delivered-only agreement was not counted there, and a month nobody has set
    a rate for cannot be answered at all. **Zero is an answer**, not an
    absence: a counted order the customer paid nothing for earned exactly
    nothing, and says `EGP 0.00` rather than a dash.

    **A worked example, not a ledger line.** The month's commission is one
    numerator divided once (ADR 0004); these are the same arithmetic applied
    to a single order so somebody can check a row against their own record.
    Summed, they can miss the month's rounded total by up to half a pound -
    which is why the screen showing them says what the total is, rather than
    inviting an addition.
    """
    if state not in counted or not rate_bp:
        return None
    exact = exact_commission_piastres(commission_numerator(max(base, 0), rate_bp))
    return int(exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def my_orders(db: Session, affiliate: AffiliateProfile, month: str) -> list[dict]:
    """The orders behind the figure, so they can count them against their own list.

    Order number, date, what it was worth to them, whether it counts, and which
    payroll paid it. **No customer appears** - not because anything is filtered
    here, but because §10.2's index never stored a name, an address or a phone
    number in the first place.

    Joined to `order_index` for the number and the date: the attributed row
    carries neither, and `shopify_order_id` is an internal identifier that
    means nothing to anybody outside the database.
    """
    parse_month(month)
    settled = _settled_months(db, affiliate, month)

    # **The rate that month was on, not the rate they are on now.** An order
    # sold in July is worth July's percentage even when it is read in
    # September, which is the same rule §11.4 applies to a carried order.
    #
    # An agreed month answers from its snapshot - the rate it was approved at
    # and the counting rule it was approved under - so nothing about a frozen
    # month is read from anything that can still be edited.
    rate_bp, counted, snapshot = month_rule(db, affiliate, month)

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

    # **What was in each order** (07A, owner 11 September 2026).
    #
    # One query for the whole month, keyed by order, rather than a lookup per
    # row - a month with sixty orders would otherwise cost sixty round trips
    # for a list nobody scrolls, which is the shape that made the products
    # screen slow in 03D.
    #
    # `contents` is **empty rather than absent** where nothing has been read.
    # Line items are fetched only for orders that earned somebody commission,
    # and only from the moment 07A started asking for them, so an older order
    # legitimately has none - and the screen says *not recorded* rather than
    # implying the order was empty.
    contents: dict[str, list[dict]] = {}
    if rows:
        for line in db.scalars(
            select(OrderLineItem)
            .where(
                OrderLineItem.shopify_order_id.in_(
                    [order.shopify_order_id for order, _ in rows]
                )
            )
            .order_by(OrderLineItem.title)
        ):
            contents.setdefault(line.shopify_order_id, []).append(
                {
                    "title": line.title,
                    "variant": line.variant_title,
                    "quantity": line.quantity,
                    # What the customer paid for the line, after the discount -
                    # the approved row prints a price beside each product.
                    "price_piastres": line.discounted_total_piastres,
                    "price": format_egp(line.discounted_total_piastres),
                }
            )

    detail = []
    for order, index in rows:
        commission = _order_commission(
            order.commission_base_piastres, rate_bp, order.commission_state, counted
        )
        status = order_status(
            state=order.commission_state,
            delivery_state=index.delivery_state,
            cancelled_at=index.cancelled_at,
            financial_status=index.financial_status,
        )
        placed = _placed_value(order, index)
        forgone = _forgone_commission(
            placed or order.commission_base_piastres,
            rate_bp,
            order.commission_state,
        )
        detail.append(
        {
            "order_number": index.order_number,
            # The index's own key, so a staff view of these rows can open the
            # order. It identifies an order, not a customer, and her own
            # screen simply does not use it.
            "shopify_order_id": index.shopify_order_id,
            "placed_at": index.placed_at.isoformat(),
            # What was in it. Empty where nothing has been read - which is an
            # older order, not an empty one, and the screen says so.
            "contents": contents.get(order.shopify_order_id, []),
            "base_piastres": order.commission_base_piastres,
            "base": format_egp(order.commission_base_piastres),
            "state": order.commission_state,
            # What happened to it, in the approved words - and a void order
            # split by why: only a courier's failure reads *Failed delivery*.
            "status": status,
            "state_text": ORDER_STATUS_TEXT[status],
            # The month's own rate, for the sentence *Commission is 10% of
            # EGP X* - the percentage the server already used, never a second
            # calculation.
            "rate_bp": rate_bp,
            # A void order its month's agreement had counted: it failed after
            # approval, and the difference is settled as a correction (05C)
            # rather than by restating the month.
            "failed_after_approval": (
                snapshot is not None
                and order.commission_state == CommissionState.VOID
                and counted_in_snapshot(snapshot, order.shopify_order_id)
            ),
            "delivered_at": (
                order.delivered_at.isoformat() if order.delivered_at else None
            ),
            # **What this one order was worth to them**, computed here because
            # nothing about money is calculated in the browser - a second
            # implementation would be a second answer waiting to disagree in
            # front of the one person guaranteed to check.
            #
            # Counted orders, under the month's own rule: delivered and
            # pending since ADR 0040. A void one never earns, and shows what
            # it would have been instead (`forgone`, struck through).
            #
            # **A worked example, not a ledger line**: ADR 0004 rounds once,
            # on the month's total, so these rows can miss it by up to half a
            # pound when summed, and the screen says what the total is.
            "commission_piastres": commission,
            "commission": format_egp(commission) if commission is not None else None,
            # Whether this order counts in this month's figure under the rule
            # the month is on. False for a void order, and for one still on
            # its way in a month agreed delivered-only - that one is paid by
            # the payroll after it arrives, at this month's rate (§11.4).
            "counted": order.commission_state in counted,
            # **No rate, so no answer** - not zero. Nobody has set terms for
            # the month, so a screen says *not available* rather than
            # inventing an amount.
            "rate_missing": rate_bp is None,
            # **What the order was placed at**, where the base no longer says.
            #
            # Shopify zeroes a cancelled order's totals, so `base_piastres` is
            # the truth about what it is worth *now* and says nothing about
            # what it was. A model matching a cancelled row against their own
            # record needs the second figure, and only the second.
            #
            # `None` where the base already carries it - offering the same
            # number twice invites a screen to show both - and `None` on rows
            # indexed before the columns existed, which a re-import fills in.
            "placed_piastres": placed,
            "placed": format_egp(placed) if placed is not None else None,
            # **What it would have been worth**, on a row that earned
            # nothing. The business asked for the figure to stay visible
            # rather than be replaced by the words "nothing earned" - struck
            # through, so it reads as what was lost rather than what is owed.
            #
            # Never added to anything. It is the same arithmetic as a counted
            # order applied to a sale that did not complete, and it exists so
            # a model can match a cancelled row against her own record.
            "forgone_piastres": forgone,
            "forgone": format_egp(forgone) if forgone is not None else None,
            # §11.4. Named only when a *different* month paid it - an order
            # settled by its own month needs no explanation, and labelling
            # every row would bury the two that matter.
            "paid_in_month": (
                settled.get(order.shopify_order_id)
                if settled.get(order.shopify_order_id) != month
                else None
            ),
        }
        )
    return detail


def _targets(
    db: Session, affiliate: AffiliateProfile, month: str, figures: dict
) -> dict | None:
    """What was asked of them, what was recorded, and whether it changes their pay.

    §15, and the last clause is the one that matters. Targets are
    **informational** on a commission or salary-plus-commission arrangement and
    decide money only on a guaranteed minimum. A model on commission who sees a
    target they missed should not think they have lost anything, because they have
    not - and a screen that cannot tell the two apart teaches them to read every
    shortfall as money gone.

    `None` when nothing was ever recorded for the month. There is no sentence
    worth writing about a target that does not exist on an arrangement it would
    not affect; where it *would* affect them, `_guarantee` is already saying so
    in the one place they are looking.

    **Nothing here is editable and no route offers to change it** (§6.5). They
    see what was recorded; recording is somebody else's job.
    """
    target = get_target(db, affiliate, month)
    if target is None:
        return None

    return {
        # All four are `null` on a month from before the platform (ADR 0036).
        # The card shows an em dash and says the numbers were not kept, which
        # is the truth: the old dashboard recorded whether a target was met and
        # not what was counted to decide it.
        #
        # **This is the one place a month before go-live reads differently from
        # a new one, and it reads differently because it is different.** Filling
        # these in to match the outcome would be inventing evidence for a figure
        # that decides money.
        "required_videos": target.required_videos,
        "required_stories": target.required_stories,
        "actual_videos": target.actual_videos,
        "actual_stories": target.actual_stories,
        "numbers_kept": not target.is_backfilled,
        # Three answers, not two. `null` is *nobody has recorded what you
        # produced*, which is a different thing from missing the target and is
        # the only one of the three that stops a month closing (§11.3).
        "achieved": target.is_achieved,
        "verified": bool(target.is_verified),
        "determines_pay": (
            figures.get("compensation_type") == CompensationType.BASE_GUARANTEE
        ),
        "recorded_at": (
            target.recorded_at.isoformat() if target.recorded_at else None
        ),
    }


#: What a credit or a write-off means to the person it was made about. §11.5
#: requires these to be visible to them: *a credit they cannot see is a credit they
#: cannot check.*
#:
#: Each says which direction the money went, because "adjustment" on its own is
#: the kind of word that makes somebody assume the worse reading.
ADJUSTMENT_TEXT = {
    AdjustmentType.CREDIT: "Carried into a later month",
    AdjustmentType.WRITEOFF: "Written off by HBA",
    AdjustmentType.CORRECTION: "A correction",
    # R4, F2. HBA took the difference and the agreed figure stands, so what she
    # is owed has not moved. Worded to say that rather than to say "absorbed",
    # which reads from her side as money going somewhere.
    AdjustmentType.ACCEPTED: "HBA covered the difference; your agreed total is unchanged",
    # R1. A deduction a month could not take, gone back to where it came from.
    AdjustmentType.RELEASE: "Returned to an earlier month",
}


def _settled_by(db: Session, affiliate: AffiliateProfile) -> dict[int, list[dict]]:
    """Which months each of their payments settled, keyed by payment id.

    A transfer can cover more than one month, and can arrive before anybody has
    decided which - `record_payment` allows an empty allocation on purpose, so
    a payment with no months against it is an ordinary state and not a gap.
    """
    rows = db.execute(
        select(
            PaymentAllocation.payment_transaction_id,
            PayrollMonth.month,
            PaymentAllocation.allocated_piastres,
        )
        .join(
            PayrollSnapshot,
            PayrollSnapshot.id == PaymentAllocation.payroll_snapshot_id,
        )
        .join(PayrollMonth, PayrollMonth.id == PayrollSnapshot.payroll_month_id)
        .join(
            PaymentTransaction,
            PaymentTransaction.id == PaymentAllocation.payment_transaction_id,
        )
        .where(PaymentTransaction.affiliate_id == affiliate.id)
        .order_by(PayrollMonth.month)
    ).all()

    by_payment: dict[int, list[dict]] = {}
    for payment_id, month, piastres in rows:
        by_payment.setdefault(payment_id, []).append(
            {"month": month, "piastres": piastres, "amount": format_egp(piastres)}
        )
    return by_payment


def _month_of(db: Session, payroll_month_id: int | None) -> str | None:
    if payroll_month_id is None:
        return None
    return db.scalar(
        select(PayrollMonth.month).where(PayrollMonth.id == payroll_month_id)
    )


def my_payments(db: Session, affiliate: AffiliateProfile) -> dict:
    """What has arrived, when, and what is still outstanding.

    §14. Deliberately a different screen from their earnings, and they stay
    different: *what I have earned* and *what has arrived* have different
    answers for most of any month, and merging them is how a model ends up
    believing they have been paid twice, or not at all.

    Three lists, and each answers a question they actually asks.

    **Per month** - what was agreed, what has been paid against it, what is
    left. The settlement state is derived from the ledger every time it is
    asked, so it cannot disagree with the payments it came from.

    **Every payment** - the amount, the date, the reference, which months it
    covered, and whether there is a screenshot. A transfer with no months
    against it is normal: money can arrive before anybody has decided what it
    covers.

    **Every adjustment** - §11.5 requires these to be visible to them, with the
    reason that was written at the time.

    Their payout destination appears **masked**, exactly as it does everywhere
    else. They supplied it, so it tells them nothing they do not know, and a
    screen printing an account number in full is one worth photographing over
    their shoulder.
    """
    months = []
    settled_outside = []
    for month in months_for(db, affiliate):
        if is_historical(month):
            # ADR 0036. The month is agreed and shown in full on every other
            # screen; what it never has is a *balance*. HBA paid it outside
            # this platform, so there is no transfer to list, nothing
            # outstanding, and a row here reading "unpaid, nothing" would be a
            # debt that never existed.
            #
            # Collected rather than merely skipped, because the list starting
            # in September with no explanation is its own question - and it is
            # the one place the old dashboard is still worth naming.
            settled_outside.append(month)
            continue
        balance = balance_for(db, affiliate, month)
        if balance["state"] == SettlementState.NOT_APPROVED:
            # Nothing agreed yet. That belongs on their earnings screen, which
            # says the month is still moving; here it would read as an unpaid
            # bill.
            continue
        months.append(
            {
                "month": month,
                "state": balance["state"],
                "obligation_piastres": balance["obligation_piastres"],
                "obligation": format_egp(balance["obligation_piastres"]),
                "paid_piastres": balance["paid_piastres"],
                "paid": format_egp(balance["paid_piastres"]),
                # Without these their arithmetic does not close. A month agreed
                # at 2,400 and settled by a transfer of 2,340 reads as sixty
                # pounds short unless the row itself says the rest was written
                # off - and the adjustment panel further down is not something
                # they will connect to this line on their own.
                "adjusted_piastres": balance["adjusted_piastres"],
                "adjusted": format_egp(balance["adjusted_piastres"]),
                # §11.5. An overpayment from an earlier month, applied here.
                # It raises what this month settles against, so a row showing
                # only the agreed figure would understate what it took to
                # clear.
                "credited_piastres": balance["credited_piastres"],
                "credited": format_egp(balance["credited_piastres"]),
                "balance_piastres": balance["balance_piastres"],
                "balance": format_egp(balance["balance_piastres"]),
            }
        )

    settled_by = _settled_by(db, affiliate)

    payments = [
        {
            "id": payment.id,
            "amount_piastres": payment.amount_piastres,
            "amount": format_egp(payment.amount_piastres),
            "occurred_at": payment.occurred_at.isoformat(),
            "reference": payment.reference,
            "destination": payment.destination_snapshot_json,
            # §14 and ADR 0017. Visible proof removes an entire category of
            # "did you send it?" messages, which is the whole reason it is kept
            # at all.
            "has_proof": payment.proof_file_id is not None,
            "settles": settled_by.get(payment.id, []),
        }
        for payment in payments_for(db, affiliate)
    ]

    adjustments = [
        {
            "kind": adjustment.type,
            "kind_text": ADJUSTMENT_TEXT.get(adjustment.type, adjustment.type),
            "amount_piastres": adjustment.amount_piastres,
            "amount": format_egp(adjustment.amount_piastres),
            # The reason somebody wrote at the time, shown as written. §11.5
            # makes it mandatory precisely so this line exists.
            "reason": adjustment.reason,
            "created_at": adjustment.created_at.isoformat(),
            "from_month": _month_of(db, adjustment.source_payroll_month_id),
            "to_month": _month_of(db, adjustment.destination_payroll_month_id),
        }
        for adjustment in adjustments_for(db, affiliate)
    ]

    outstanding = sum(
        row["balance_piastres"] for row in months if row["balance_piastres"] > 0
    )

    return {
        "months": months,
        "payments": payments,
        "adjustments": adjustments,
        "outstanding_piastres": outstanding,
        "outstanding": format_egp(outstanding),
        # ADR 0036. **One line, on this screen only, and only for somebody who
        # has such a month.** A model who joins in October never learns there
        # was an old dashboard, because there is nothing about it she needs to
        # know - and telling her invites a question about records she has no
        # reason to doubt.
        #
        # It says where the money went, not that the months are lesser. Every
        # other screen shows them in full.
        "settled_outside": (
            {
                "months": settled_outside,
                "since": settled_outside[0],
                "text": (
                    f"HBA paid you for the months up to "
                    f"{_month_words(settled_outside[-1])} before this page "
                    "existed, so those payments are not listed here. What you "
                    "earned in them is on your Earnings and Year screens."
                ),
            }
            if settled_outside
            else None
        ),
    }


def my_year(db: Session, affiliate: AffiliateProfile) -> dict:
    """Every month they have, as two series and a summary.

    The fifth screen. Nothing here is new arithmetic - each month is the same
    `my_month` the Earnings screen shows, gathered.

    **Two series that measure different things**, which is the whole design
    constraint. The business caught the first attempt reporting the same facts
    twice with a different y-axis, and was right: what they earned and what they
    sold move together on a commission arrangement, so drawing both is drawing
    one thing.

    So one is money and the other is a count:

    - `earned` — what reached them. A trend, drawn as a line, because the
      question is *am I going up?* and the eye answers that from a slope.
    - `orders` — how many arrived. A tally, drawn as bars, because you can
      compare bar heights exactly in a way you cannot compare points.

    Sales stay off the charts and travel with the order count instead, where
    they make a bar mean something rather than repeating the line.

    **A month before go-live has no `earned` figure** and says so with `null`
    rather than a zero. Its sales and orders are real (ADR 0014); the
    commission was agreed elsewhere, and a zero on a chart is a claim that they
    earned nothing.
    """
    months = months_for(db, affiliate)
    series = []
    working = working_month()

    for month in reversed(months):  # oldest first: a chart reads left to right
        figures = my_month(db, affiliate, month)
        series.append(
            {
                "month": month,
                # **The month in progress is marked, not hidden here.**
                #
                # A part-month plotted beside finished ones reads as a
                # collapse: September at EGP 503 next to August at EGP 3,829
                # drew a line falling off a cliff, when September was three
                # days old. The charts drop it; this screen still returns it,
                # because the Month tab is where a live figure belongs and one
                # service answering two questions differently is how they
                # come to disagree.
                "in_progress": month == working,
                # 1-12, because an axis wants a number and a number needs no
                # translating.
                "number": int(month.split("-")[1]),
                "label": _month_words(month),
                "state": figures["state"],
                # `None` on a month the platform did not pay for.
                "earned_piastres": figures["amount_piastres"],
                "earned": figures["amount"],
                # F02, R3. The same *counted sales* her month card shows -
                # delivered and pending. The chart plotted the delivered part
                # while the card beside it was about to say something else.
                "sales_piastres": figures["sales"]["counted_piastres"],
                "sales": figures["sales"]["counted"],
                "orders": figures["orders"]["counted"],
                # A08. **The chart asked for this and nothing sent it.** Home
                # said *37 uses* and the Uses tab beside it said *this history
                # is not available yet*, because `my_year` returned `orders`
                # and the chart reads `uses`.
                #
                # It is the month card's own figure, not a second count: a
                # use is a **delivery** outcome (D03) and the order counts
                # beside it are *commission* states.
                #
                # Where they part company is **before** delivery. An order
                # refunded or cancelled while still in transit voids the
                # commission, and the courier never reported a failure - so
                # her code was used and no sale completed. A parcel refused at
                # the door is neither a use nor a sale.
                #
                # **After** delivery they agree and stay agreed: ADR 0025 is
                # that delivery is final, so a refund, a return or an exchange
                # leaves a delivered order earning exactly what it earned. An
                # earlier draft of this comment said such an order "pays
                # nothing", which is the opposite of the rule HBA runs.
                "uses": figures["orders"].get("uses"),
            }
        )

    # **Closed months only, for every summary on the screen.**
    #
    # The total has to agree with the chart, and the chart drops the month in
    # progress. A headline that included it would be a figure nobody could
    # reach by adding up the points in front of them - and "best month" could
    # be won by a month that is three days old.
    paid_months = [
        row
        for row in series
        if row["earned_piastres"] is not None and not row["in_progress"]
    ]
    best = max(paid_months, key=lambda r: r["earned_piastres"], default=None)
    total = sum(row["earned_piastres"] for row in paid_months)

    return {
        "months": series,
        "total_earned_piastres": total,
        "total_earned": format_egp(total),
        "best_month": best["month"] if best else None,
        "best_month_label": best["label"] if best else None,
        "best_month_piastres": best["earned_piastres"] if best else None,
        # **Orders are counted across every month**, including the one in
        # progress. An order that counted, counted - it is a tally of things
        # that happened, not a figure still being decided, so leaving today's
        # out would be under-reporting her own work.
        "total_orders": sum(row["orders"] for row in series),
        "closed_months": len(paid_months),
    }


def _month_words(month: str) -> str:
    names = (
        "January February March April May June July August September October "
        "November December"
    ).split()
    year, _, index = month.partition("-")
    try:
        return f"{names[int(index) - 1]} {year}"
    except (ValueError, IndexError):
        return month


def my_targets(db: Session, affiliate: AffiliateProfile) -> dict:
    """What has been asked of her, month by month, and how each one ended.

    UI24, and **read-only in the strongest sense**: there is no route that lets
    a model change any of this, not a disabled control and not a permission
    check. Recording is somebody else's job (§6.5), and the absence of a write
    path is what enforces it rather than a rule somebody has to remember.

    ## Three answers, never two

    Every month is one of *nothing recorded*, *missed*, or *met* - and the
    first is not the second. A model shown "missed" for a month nobody has
    counted yet has been told something untrue about her own work, and she has
    been told it about the month that is blocking her pay (§11.3).

    ## A month from before the platform says so

    ADR 0036: the old dashboard kept whether a target was met and not what was
    counted to decide it. Those months carry an outcome and no numbers, and the
    screen says the numbers were not kept rather than drawing a bar against a
    figure nobody ever set (H02). Filling them in to match the outcome would be
    inventing evidence for something that decides money.

    ## Which months are about money

    §15: targets are informational on commission and on salary-plus-commission,
    and decide pay only on a guaranteed minimum. A model on commission who sees
    a target she missed has not lost anything, and a screen that cannot tell
    the two apart teaches her to read every shortfall as money gone. So
    `determines_pay` is computed per month from the arrangement she was on
    *then*, not from the one she is on now - she may have moved between them.

    Two queries however long her history is, not two per month.
    """
    months = months_for(db, affiliate)
    if not months:
        return {"months": []}

    targets = {
        row.month: row
        for row in db.scalars(
            select(MonthlyTarget).where(MonthlyTarget.affiliate_id == affiliate.id)
        )
    }

    # `months` is newest first, so `months[0]` is the last month she can see.
    # An open-ended arrangement runs to there and no further, and a recorded
    # end month is clamped to it as well: a period ending next year must not
    # walk this loop through months that have not happened.
    horizon = months[0]
    deciding: set[str] = set()
    for period in all_terms(db, affiliate):
        if period.compensation_type != CompensationType.BASE_GUARANTEE:
            continue
        cursor = period.start_month
        last = min(period.end_month or horizon, horizon)
        while cursor <= last:
            deciding.add(cursor)
            cursor = month_add(cursor, 1)

    rows = []
    for month in months:
        target = targets.get(month)
        rows.append(
            {
                "month": month,
                "determines_pay": month in deciding,
                # `None` throughout for a month nobody has set anything for.
                # No target and a target of zero are different facts, and the
                # difference is the one that fails a guaranteed minimum.
                "required_videos": target.required_videos if target else None,
                "required_stories": target.required_stories if target else None,
                "actual_videos": target.actual_videos if target else None,
                "actual_stories": target.actual_stories if target else None,
                # Three-valued for the same reason `achieved` is: *nothing was
                # asked of you* is not *the numbers were lost*.
                "numbers_kept": None if target is None else not target.is_backfilled,
                "achieved": target.is_achieved if target else None,
                "verified": bool(target and target.is_verified),
                "recorded_at": (
                    target.recorded_at.isoformat()
                    if target and target.recorded_at
                    else None
                ),
            }
        )

    return {"months": rows}
