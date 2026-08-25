"""Does this order count yet? — §9.4 and ADR 0012 as code.

Three states, and only one of them pays:

    pending   in transit, or a return is still being decided
    earned    delivered, nothing open. **This is the one that pays.**
    void      cancelled, fully refunded, or the delivery failed

The old dashboard had none of this: `_with_commission()` applied the rate to
every order in the month regardless of status, and failed deliveries were
neutralised only by a Shopify automation living outside the codebase. For a
brand shipping cash-on-delivery through Bosta, where refusals are material, that
is money paid on goods nobody received.

## Pending is shown, never hidden

A model should be able to see what is coming. Hiding an undelivered order makes
her month look smaller than it is and produces the question this platform exists
to stop her having to ask.

## Finalised is a different question from earned

An order delivered yesterday is `earned` and pays this month. It is **not**
finalised - a return in the next nine days can still void it while the month is
draft. Collapsing the two would either delay every model's pay by ten days
(rejected in ADR 0012) or pretend an outcome is fixed when it is not.

``is_finalised`` answers *can this ever change again?* — ADR 0024.

## What this deliberately does not do

**It does not look at whether HBA has been paid.** ADR 0012 makes delivery the
condition, and for cash-on-delivery delivery *is* payment; Shopify's financial
status lags it. Requiring `paid` would park every delivered order until the
courier's money cleared. Only the two statuses that mean the money went **back**
- `refunded` and `voided` - are read here.

`partially_paid` is therefore not special-cased, and §9.1 flags it as a
mid-exchange marker the old system handled nowhere. Treating "some money" as
worse than "no money" would be backwards, and the case §9.1 actually worries
about is caught by the return being unresolved. It is watched in
`docs/limits.md` rather than guessed at.
"""

from datetime import datetime, timedelta

from app.models.attributed_orders import CommissionState
from app.services.shopify.fulfilment import DELIVERED, FAILED

#: Shopify financial statuses meaning the money went back. Only these two void
#: an order; every other status is about money not yet arriving, which is
#: ordinary for cash on delivery.
REVERSED_FINANCIAL_STATUSES = frozenset({"refunded", "voided"})

#: §9.4. HBA accepts this exposure deliberately (ADR 0012): an order delivered
#: on 31 August and approved on 5 September still carries six days of it, and a
#: return afterwards is absorbed rather than clawed back.
RETURN_WINDOW_DAYS = 10


def commission_state(
    *,
    cancelled_at: datetime | None = None,
    financial_status: str | None = None,
    delivery_state: str | None = None,
    return_unresolved: bool = False,
) -> str:
    """§9.4. Which of the three states this order is in.

    The order of these checks is the rule, not an implementation detail. A
    cancelled order that happens to have been delivered is void, not earned;
    reading delivery first would pay for it.
    """
    if cancelled_at is not None:
        return CommissionState.VOID

    if str(financial_status or "").strip().lower() in REVERSED_FINANCIAL_STATUSES:
        return CommissionState.VOID

    if delivery_state == FAILED:
        return CommissionState.VOID

    # Checked **after** the void cases and **before** delivery. A return being
    # decided on a delivered order takes it back out of earned - §9.4 says
    # earned means delivered *with no open return or exchange*.
    if return_unresolved:
        return CommissionState.PENDING

    if delivery_state == DELIVERED:
        return CommissionState.EARNED

    # Includes delivery_state of None - an order Shopify has told us nothing
    # about. Not delivered is not the same as failed, and an order indexed
    # before the platform ever asked for delivery must not read as a failure.
    return CommissionState.PENDING


def is_finalised(
    *,
    state: str,
    delivered_at: datetime | None = None,
    exchange_resolved: bool = False,
    settled_in_snapshot: bool = False,
    now: datetime | None = None,
) -> bool:
    """ADR 0024. Can this order ever change again?

    Four things finish an order. Three are decidable here; the fourth belongs
    to Phase 6, which owns the snapshots.

    ``void``                    - nothing left to reverse
    an exchange resolved on it  - finalised at the original sale
    delivered + window elapsed  - the customer can no longer send it back
    paid in an approved payroll - §9.3 absorbs later movement either way

    A finalised order is not recalculated and not re-read from Shopify. It is
    also a fact the model's dashboard can show: *this one is settled*, as
    against *this may still change*.
    """
    if state == CommissionState.VOID:
        return True

    if exchange_resolved:
        # She keeps her commission on the original sale in full. Any price
        # difference is HBA's, in both directions - she sold the first item,
        # not the replacement.
        return True

    if settled_in_snapshot:
        return True

    if state == CommissionState.EARNED and delivered_at is not None:
        moment = now or _utcnow()
        return moment - delivered_at >= timedelta(days=RETURN_WINDOW_DAYS)

    return False


def _utcnow() -> datetime:
    from app.core.businesstime import utcnow

    return utcnow()


def counts_toward_payout(state: str) -> bool:
    """§9.4. Only earned does."""
    return state == CommissionState.EARNED
