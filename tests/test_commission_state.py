"""Does this order count? §9.4, ADR 0012, ADR 0025.

The old dashboard applied the commission rate to every order in the month
regardless of status. Failed deliveries were neutralised only by a Shopify
automation living outside the codebase, which would disappear silently if
anyone switched it off. For a brand shipping cash-on-delivery through Bosta,
where refusals are material, that is money paid on goods nobody received.

**Delivery is the end of the story (ADR 0025).** Returns, exchanges, refunds and
edits after delivery are ignored - not mis-handled, deliberately not acted on.
Every state below is written against what HBA's live shop actually reports.
"""

from datetime import datetime, timezone

import pytest

from app.models.attributed_orders import CommissionState
from app.services.commission.state import (
    commission_state,
    counts_toward_payout,
    is_final,
)
from app.services.shopify.fulfilment import DELIVERED, FAILED, IN_FLIGHT

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


# ── The one that pays ──────────────────────────────────────────────────────────


def test_a_delivered_order_is_earned():
    """ADR 0012. Earned on delivery, not after the return window closes -
    waiting the full window would delay every affiliate's earnings by ten days
    to recover a small number of reversals.
    """
    assert commission_state(delivery_state=DELIVERED) == CommissionState.EARNED


def test_only_earned_counts_toward_a_payout():
    assert counts_toward_payout(CommissionState.EARNED) is True
    assert counts_toward_payout(CommissionState.PENDING) is False
    assert counts_toward_payout(CommissionState.VOID) is False


# ── Delivery is final ──────────────────────────────────────────────────────────


def test_nothing_after_delivery_takes_the_sale_back():
    """ADR 0025. The customer has the goods; what happens next is between them
    and HBA. Cancellation, refund and return are all read, stored, and not
    acted on.
    """
    assert (
        commission_state(delivery_state=DELIVERED, cancelled_at=NOW)
        == CommissionState.EARNED
    )
    assert (
        commission_state(delivery_state=DELIVERED, financial_status="refunded")
        == CommissionState.EARNED
    )


def test_delivery_is_checked_before_anything_else():
    """The order of the checks **is** the rule. Reading cancellation first would
    let a refund processed as a cancellation quietly reverse a delivered order,
    which is exactly the behaviour ADR 0025 removed.
    """
    assert (
        commission_state(
            delivery_state=DELIVERED, cancelled_at=NOW, financial_status="refunded"
        )
        == CommissionState.EARNED
    )


@pytest.mark.parametrize(
    "state,final",
    [
        (CommissionState.EARNED, True),
        (CommissionState.VOID, True),
        (CommissionState.PENDING, False),
    ],
)
def test_only_a_pending_order_can_still_change(state, final):
    """A finished order is never recalculated and never re-read from Shopify,
    which is what stops a late webhook rewriting a figure a payroll has been
    approved on.
    """
    assert is_final(state) is final


# ── Still travelling ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("state", [IN_FLIGHT, None])
def test_an_order_that_has_not_arrived_is_pending(state):
    """Including one Shopify has told us nothing about. Not delivered is not
    the same as failed, and an order indexed before the platform ever asked
    about delivery must not read as a failure.
    """
    assert commission_state(delivery_state=state) == CommissionState.PENDING


# ── Void: the sale never completed ─────────────────────────────────────────────


def test_a_failed_delivery_is_void():
    """The customer refused it at the door. This is the loss ADR 0012 was
    written to prevent, and the old dashboard only avoided it by way of an
    external automation.
    """
    assert commission_state(delivery_state=FAILED) == CommissionState.VOID


def test_an_order_cancelled_before_it_shipped_is_void():
    assert (
        commission_state(delivery_state=IN_FLIGHT, cancelled_at=NOW)
        == CommissionState.VOID
    )


@pytest.mark.parametrize("status", ["refunded", "voided", "REFUNDED", " Voided "])
def test_money_returned_before_delivery_voids_the_order(status):
    """Refunded while still in transit means the sale never completed - a
    different thing from a customer sending goods back afterwards.
    """
    assert (
        commission_state(delivery_state=IN_FLIGHT, financial_status=status)
        == CommissionState.VOID
    )


# ── What HBA's live shop actually reports ──────────────────────────────────────


@pytest.mark.parametrize(
    "financial_status",
    [
        # Every financial status present across 537 real orders, with its count.
        "paid",  # 328
        "pending",  # 118 - cash on delivery, uncollected
        "voided",  # 60
        "partially_paid",  # 25
        "partially_refunded",  # 5
        "refunded",  # 1
    ],
)
def test_a_delivered_order_earns_whatever_the_money_says(financial_status):
    """For cash on delivery, delivery **is** payment and Shopify's financial
    status lags the courier. 118 of 537 orders sit at `pending`, so a payment
    condition would park most of the shop.
    """
    assert (
        commission_state(delivery_state=DELIVERED, financial_status=financial_status)
        == CommissionState.EARNED
    )


def test_partly_paid_needs_no_rule_of_its_own():
    """§9.1 names it as something the old system handled nowhere. HBA has
    confirmed it only appears on orders an exchange has touched - and an
    exchange cannot change a delivered order's value at all - so there is
    nothing left for a rule about the status to do.
    """
    partly = commission_state(
        delivery_state=DELIVERED, financial_status="partially_paid"
    )
    plain = commission_state(delivery_state=DELIVERED, financial_status="paid")
    assert partly == plain == CommissionState.EARNED
