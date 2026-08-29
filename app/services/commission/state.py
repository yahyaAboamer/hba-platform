"""Does this order count? — §9.4, ADR 0012, and ADR 0025.

Three states, and only one of them pays:

    pending   still travelling
    earned    delivered. **This is the one that pays, and it is final.**
    void      the delivery failed, or it was cancelled before it shipped

The old dashboard had none of this: `_with_commission()` applied the rate to
every order in the month regardless of status, and failed deliveries were
neutralised only by a Shopify automation living outside the codebase. For a
brand shipping cash-on-delivery through Bosta, where refusals are material, that
is money paid on goods nobody received.

## Delivery is the end of the story (ADR 0025)

Returns, exchanges, refunds and order edits **after delivery are ignored** - not
mis-handled, not held for a person, deliberately not acted on. The facts are
still stored on `order_index`; the engine does not read them.

That decision is recorded in full in ADR 0025 and rests on three findings:
Shopify's refund figures are not what HBA actually refunds, Shopify will not say
whether a return was an exchange, and an exchange can swap any number of items
for any other number - so "a replacement appeared" identifies *that* an exchange
happened while saying nothing about what the customer ended up holding.

The measured exposure is **1.1% of orders** - six of 537 showed money going back.
It is reversible: the data keeps arriving.

## Pending is shown, never hidden

A model should be able to see what is coming. Hiding an undelivered order makes
their month look smaller than it is and produces exactly the question this platform
exists to stop their having to ask.

## What this deliberately does not do

**It does not look at whether HBA has been paid.** For cash on delivery, delivery
*is* payment, and Shopify's financial status lags the courier - 118 of 537 live
orders sit at `pending`. Requiring `paid` would park most of the shop.

`partially_paid` is therefore not special-cased either. HBA has confirmed it only
appears on orders an exchange has touched, and an exchange cannot change a
delivered order's value at all, so there is nothing left for a rule about the
status to do.
"""

from datetime import datetime

from app.models.attributed_orders import CommissionState
from app.services.shopify.fulfilment import DELIVERED, FAILED

#: Shopify financial statuses meaning the money went back **before** the parcel
#: arrived - an order voided or refunded while it was still in transit. After
#: delivery they are ignored like everything else (ADR 0025).
REVERSED_FINANCIAL_STATUSES = frozenset({"refunded", "voided"})


def commission_state(
    *,
    delivery_state: str | None = None,
    cancelled_at: datetime | None = None,
    financial_status: str | None = None,
) -> str:
    """§9.4. Which of the three states this order is in.

    **Delivery is checked first, and that is the rule.** Once the customer has
    the goods, nothing later - a cancellation, a refund, a return - takes the
    sale back (ADR 0025). Checking cancellation first would let a refund
    processed as a cancellation quietly reverse a delivered order, which is the
    behaviour this ADR removed.
    """
    if delivery_state == DELIVERED:
        return CommissionState.EARNED

    if delivery_state == FAILED:
        return CommissionState.VOID

    # Not delivered, and something stopped it. Both of these mean the sale never
    # completed rather than that it was undone.
    if cancelled_at is not None:
        return CommissionState.VOID

    if str(financial_status or "").strip().lower() in REVERSED_FINANCIAL_STATUSES:
        return CommissionState.VOID

    # Includes a delivery_state of None - an order Shopify has told us nothing
    # about. Not delivered is not the same as failed, and an order indexed
    # before the platform ever asked about delivery must not read as a failure.
    return CommissionState.PENDING


def is_final(state: str) -> bool:
    """ADR 0025. Can this order still change?

    Only `pending` can. Both other states are terminal, so a finished order is
    never recalculated and never re-read from Shopify - which is what stops a
    late webhook rewriting a figure a payroll has been approved on.
    """
    return state in (CommissionState.EARNED, CommissionState.VOID)


def counts_toward_payout(state: str) -> bool:
    """§9.4. Only earned does."""
    return state == CommissionState.EARNED
