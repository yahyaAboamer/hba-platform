"""What is this order worth? — §9.3 and ADR 0011 as code.

> **Commission base = total the customer pays − shipping − tax**, after all
> discounts.

Order `#29115` is the worked example and the acceptance test. The customer paid
**E£1,157**, of which E£95 was shipping, so the base is **E£1,062**. Mid-exchange
Shopify reported three items totalling E£1,675 — E-stebdal had added the
replacement without removing the returned one — and the old dashboard calculated
on roughly E£1,557. **About 47% too much, on one order.**

## The freeze is the whole defence

The base tracks Shopify while the order is travelling and nothing has come back,
so a genuine pre-shipment edit is reflected. **The moment any return or exchange
activity appears, the stored value stops moving — permanently.** Because it is
never re-read, the inflation above cannot reach the calculation.

Freezing is not the same as ignoring what came back. A customer who buys a
jacket and genuinely returns the pants should be worth the jacket. That is the
reduction below, and it is the part this module cannot yet finish.

## Why a resolved return is held rather than guessed

HBA's rule, in their words: **the base after a return is the value of the
products the customer kept.** Applying it means telling a plain return from an
exchange, because they resolve to opposite outcomes — an exchange finalises the
order at the full base (ADR 0024), a return reduces it.

E-stebdal opens an identical Shopify return for both, and Shopify refused
`Order.returns`: `read_returns` is not granted. So the platform **says it cannot
decide** rather than picking one. A held order pays nothing until a person or a
scope resolves it, which is the same shape as the multi-code hold in §9.2.

The alternative is worse in both directions. Assume exchange and a genuine
return pays full commission on goods that came back; assume return and every
exchange underpays a model who sold the item and had no part in the swap.

## What this module deliberately does not do

**It does not read the order total to work out what was kept.** That total
carries return shipping and the manual balance corrections HBA does by hand, so
subtracting from it inherits every one of them. The kept-items rule reads the
product lines instead — see `docs/limits.md`.
"""

from dataclasses import dataclass
from datetime import datetime

#: Why a base cannot be trusted as final. ``None`` means it can.
NEEDS_RETURN_DECISION = "return_resolved_but_exchange_is_indistinguishable"


@dataclass(frozen=True)
class BaseDecision:
    """What the order is worth, and whether that figure can be relied on."""

    piastres: int

    #: When the base stopped tracking Shopify. ``None`` means it still does.
    frozen_at: datetime | None = None

    #: Set when the figure is a placeholder rather than an answer. An order
    #: carrying this **must not pay** - see the module docstring.
    needs_decision: str | None = None

    @property
    def is_frozen(self) -> bool:
        return self.frozen_at is not None

    @property
    def is_decided(self) -> bool:
        return self.needs_decision is None


def commission_base(
    total_piastres: int, shipping_piastres: int, tax_piastres: int
) -> int:
    """§9.3. What the customer paid for the goods.

    Shipping and tax are HBA's, not the model's. Both are already excluded from
    every discount the customer received, so no percentage is needed anywhere -
    a E£1,000 jacket on a 10% code arrives here inside a total of E£900.

    Never negative. A refund larger than the order would otherwise produce a
    negative base, which would quietly subtract from everything else she earned
    that month.
    """
    goods = int(total_piastres) - int(shipping_piastres) - int(tax_piastres)
    return max(goods, 0)


def base_for_order(
    *,
    total_piastres: int,
    shipping_piastres: int,
    tax_piastres: int,
    return_activity: bool = False,
    return_unresolved: bool = False,
    stored_base_piastres: int | None = None,
    base_frozen_at: datetime | None = None,
    now: datetime | None = None,
) -> BaseDecision:
    """Decide this order's base, given what it was worth last time we looked.

    ``stored_base_piastres`` and ``base_frozen_at`` are the row as it stands.
    Passing them is what makes the freeze mean anything: without the previous
    value there is nothing to hold on to, and the figure would follow Shopify
    straight into the exchange inflation.
    """
    live = commission_base(total_piastres, shipping_piastres, tax_piastres)

    if not return_activity:
        # Nothing has come back. The base follows Shopify, so an edit made
        # before the parcel ships is reflected.
        return BaseDecision(piastres=live)

    # Something came back. Whatever the base was at that moment is what it
    # stays - the subtotal from here on has an added replacement in it.
    if base_frozen_at is not None:
        frozen_value = stored_base_piastres if stored_base_piastres is not None else live
        frozen_at = base_frozen_at
    else:
        frozen_value = stored_base_piastres if stored_base_piastres is not None else live
        frozen_at = now or _utcnow()

    if return_unresolved:
        # Still being decided. The order is `pending` anyway (§9.4), so this
        # figure pays nobody yet - but it is frozen now, before E-stebdal's
        # edits land, rather than when the return finishes.
        return BaseDecision(piastres=frozen_value, frozen_at=frozen_at)

    # Resolved, and the platform cannot tell which way. Held.
    return BaseDecision(
        piastres=frozen_value,
        frozen_at=frozen_at,
        needs_decision=NEEDS_RETURN_DECISION,
    )


def _utcnow() -> datetime:
    from app.core.businesstime import utcnow

    return utcnow()
