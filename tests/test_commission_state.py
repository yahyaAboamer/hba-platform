"""Does this order count yet? §9.4 and ADR 0012.

The old dashboard applied the commission rate to every order in the month
regardless of status. Failed deliveries were neutralised only by a Shopify
automation living outside the codebase, which would disappear silently if
anyone switched it off. For a brand shipping cash-on-delivery through Bosta,
where refusals are material, that is money paid on goods nobody received.

Every state below is written against what HBA's live shop actually reports.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.attributed_orders import CommissionState
from app.services.commission.state import (
    RETURN_WINDOW_DAYS,
    commission_state,
    counts_toward_payout,
    is_finalised,
)
from app.services.shopify.fulfilment import DELIVERED, FAILED, IN_FLIGHT

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


# ── The one that pays ──────────────────────────────────────────────────────────


def test_a_delivered_order_with_nothing_open_is_earned():
    """ADR 0012. Earned on delivery, not after the return window closes -
    waiting the full window would delay every affiliate's earnings by ten days
    to recover a small number of reversals.
    """
    assert (
        commission_state(delivery_state=DELIVERED) == CommissionState.EARNED
    )


def test_only_earned_counts_toward_a_payout():
    assert counts_toward_payout(CommissionState.EARNED) is True
    assert counts_toward_payout(CommissionState.PENDING) is False
    assert counts_toward_payout(CommissionState.VOID) is False


# ── Still travelling ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("state", [IN_FLIGHT, None])
def test_an_order_that_has_not_arrived_is_pending(state):
    """Including one Shopify has told us nothing about. Not delivered is not
    the same as failed, and an order indexed before the platform ever asked
    about delivery must not read as a failure.
    """
    assert commission_state(delivery_state=state) == CommissionState.PENDING


def test_a_return_being_decided_takes_a_delivered_order_back_out_of_earned():
    """§9.4: earned means delivered **with no open return or exchange**. The
    parcel arrived, then the customer opened a return - it is not hers to be
    paid for until that resolves.
    """
    assert (
        commission_state(delivery_state=DELIVERED, return_unresolved=True)
        == CommissionState.PENDING
    )


def test_a_finished_return_no_longer_blocks():
    """`return_unresolved` is false once the return completes. Passing "any
    return activity" here instead would park every completed return and every
    completed exchange in pending for ever.
    """
    assert (
        commission_state(delivery_state=DELIVERED, return_unresolved=False)
        == CommissionState.EARNED
    )


# ── Void, and the order the checks run in ──────────────────────────────────────


def test_a_failed_delivery_is_void():
    """The customer refused it at the door. This is the loss ADR 0012 was
    written to prevent, and the old dashboard only avoided it by way of an
    external automation.
    """
    assert commission_state(delivery_state=FAILED) == CommissionState.VOID


@pytest.mark.parametrize("status", ["refunded", "voided", "REFUNDED", " Voided "])
def test_money_that_went_back_voids_the_order(status):
    assert (
        commission_state(financial_status=status, delivery_state=DELIVERED)
        == CommissionState.VOID
    )


def test_a_cancelled_order_is_void_even_if_it_was_delivered():
    """The order of the checks is the rule, not an implementation detail.
    Reading delivery first would pay for a cancelled order that happened to
    arrive.
    """
    assert (
        commission_state(cancelled_at=NOW, delivery_state=DELIVERED)
        == CommissionState.VOID
    )


def test_a_void_order_stays_void_while_a_return_is_open():
    """Void is checked before the return. An order already cancelled does not
    become merely pending because somebody also opened a return on it.
    """
    assert (
        commission_state(
            cancelled_at=NOW, delivery_state=DELIVERED, return_unresolved=True
        )
        == CommissionState.VOID
    )


# ── What HBA's live shop actually reports ──────────────────────────────────────


@pytest.mark.parametrize(
    "financial_status,expected",
    [
        # Every financial status present across 537 real orders, with its count.
        ("paid", CommissionState.EARNED),  # 328
        ("pending", CommissionState.EARNED),  # 118 - cash on delivery, uncollected
        ("voided", CommissionState.VOID),  # 60
        ("partially_paid", CommissionState.EARNED),  # 25
        ("partially_refunded", CommissionState.EARNED),  # 5 - base reduces, Task 3
        ("refunded", CommissionState.VOID),  # 1
    ],
)
def test_every_live_financial_status_on_a_delivered_order(financial_status, expected):
    assert (
        commission_state(financial_status=financial_status, delivery_state=DELIVERED)
        == expected
    )


def test_an_unpaid_delivery_still_earns():
    """Cash on delivery: delivery **is** payment, and Shopify's financial
    status lags the courier by hours or days. Requiring `paid` would park every
    delivered order until the money cleared - 118 of 537 live orders sit at
    `pending`.
    """
    assert (
        commission_state(financial_status="pending", delivery_state=DELIVERED)
        == CommissionState.EARNED
    )


def test_partly_paid_is_not_treated_worse_than_not_paid_at_all():
    """§9.1 flags `partially_paid` as a mid-exchange marker the old system
    handled nowhere. The mid-exchange case is caught by the return being
    unresolved; special-casing the status here would make "some money" worse
    than "no money", which is backwards. Watched in docs/limits.md.
    """
    partly = commission_state(financial_status="partially_paid", delivery_state=DELIVERED)
    unpaid = commission_state(financial_status="pending", delivery_state=DELIVERED)
    assert partly == unpaid


def test_a_partial_refund_does_not_void_the_order():
    """The customer kept some of it. §9.3 reduces the base, which is Task 3's
    job - voiding here would pay her nothing for goods she genuinely sold.
    """
    assert (
        commission_state(
            financial_status="partially_refunded", delivery_state=DELIVERED
        )
        == CommissionState.EARNED
    )


# ── Finalised: can this ever change again? ─────────────────────────────────────


def test_earned_is_not_the_same_as_finished_with():
    """An order delivered yesterday pays this month, but a return in the next
    nine days can still void it while the month is draft. Collapsing the two
    would either delay everyone's pay by ten days or pretend an outcome is
    fixed when it is not.
    """
    yesterday = NOW - timedelta(days=1)

    assert (
        commission_state(delivery_state=DELIVERED) == CommissionState.EARNED
    )
    assert (
        is_finalised(
            state=CommissionState.EARNED, delivered_at=yesterday, now=NOW
        )
        is False
    )


def test_the_window_closing_finishes_the_order():
    long_ago = NOW - timedelta(days=RETURN_WINDOW_DAYS)

    assert (
        is_finalised(state=CommissionState.EARNED, delivered_at=long_ago, now=NOW)
        is True
    )


def test_the_last_day_of_the_window_is_not_yet_finished():
    """Off by one here is a real return arriving on day ten and being ignored."""
    almost = NOW - timedelta(days=RETURN_WINDOW_DAYS, seconds=-1)

    assert (
        is_finalised(state=CommissionState.EARNED, delivered_at=almost, now=NOW)
        is False
    )


def test_an_exchange_finishes_the_order_at_the_original_sale():
    """ADR 0024. She keeps her commission in full; any price difference is
    HBA's, in both directions, because she sold the first item and not the
    replacement. Everything unreliable about exchange money - the fees, the
    refunds settled outside E-stebdal, the "refund needed" flag Shopify is left
    showing - falls after this point and cannot reach the calculation.
    """
    assert (
        is_finalised(
            state=CommissionState.EARNED, delivered_at=NOW, exchange_resolved=True, now=NOW
        )
        is True
    )


def test_a_void_order_is_finished_with():
    """Nothing left to reverse."""
    assert is_finalised(state=CommissionState.VOID, now=NOW) is True


def test_an_order_paid_in_an_approved_payroll_is_finished_with():
    """§9.3 absorbs later movement either way, so re-reading it could only
    produce a figure that disagrees with what was paid."""
    assert (
        is_finalised(
            state=CommissionState.EARNED,
            delivered_at=NOW,
            settled_in_snapshot=True,
            now=NOW,
        )
        is True
    )


def test_a_pending_order_is_never_finished_with():
    """Whatever else is true of it, something has yet to happen."""
    assert (
        is_finalised(state=CommissionState.PENDING, delivered_at=None, now=NOW) is False
    )


def test_a_delivered_order_with_no_date_never_finalises_on_the_window():
    """Some couriers report the status without a timestamp. Without a delivery
    date the window cannot be measured, and inventing one would either finalise
    the order early or leave it open for ever - so it stays open, visibly.
    """
    assert (
        is_finalised(state=CommissionState.EARNED, delivered_at=None, now=NOW) is False
    )
