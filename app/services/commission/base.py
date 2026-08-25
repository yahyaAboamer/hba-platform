"""What is this order worth? — §9.3, ADR 0011, ADR 0025.

> **Commission base = total the customer pays − shipping − tax**, after all
> discounts.

Order `#29115` is the worked example and the acceptance test. The customer paid
**E£1,157**, of which E£95 was shipping, so the base is **E£1,062**. Mid-exchange
Shopify reported three items totalling E£1,675 — E-stebdal had added the
replacement without removing the returned one — and the old dashboard calculated
on roughly E£1,557. **About 47% too much, on one order.**

## The base moves until delivery, and then it stops

Before the parcel arrives, the base follows Shopify, so a genuine pre-shipment
edit is reflected. **Once the order is delivered the figure is fixed** and
Shopify is never read for it again (ADR 0025).

That is what keeps the `#29115` inflation out, and it does so without depending
on *when* anything happened. The earlier design froze on the first sign of return
activity, which needed the return to be visible before the replacement item was —
an ordering nobody at HBA can observe, because it happens inside E-stebdal. Since
an exchange can only happen to a parcel the customer already has, freezing on
delivery is strictly earlier and needs no timing assumption at all.

## What is deliberately not here

No refund reduction, no exchange detection, no held orders. ADR 0025 records why:
Shopify's refund figures are not what HBA actually refunds, Shopify will not say
whether a return was an exchange, and an exchange can swap any number of items for
any other number — so no rule expressible from this data would be reliably right.

The exposure is measured at **1.1% of orders** and the facts are still stored on
`order_index`, so the decision can be revisited with a year of evidence.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BaseDecision:
    """What the order is worth, and whether that figure can still move."""

    piastres: int

    #: Delivered, therefore fixed. Nothing after this is read.
    is_final: bool = False


def commission_base(
    total_piastres: int, shipping_piastres: int, tax_piastres: int
) -> int:
    """§9.3. What the customer paid for the goods.

    Shipping and tax are HBA's, not the model's. Both are already net of every
    discount the customer received, so no percentage is needed anywhere - a
    E£1,000 jacket on a 10% code arrives here inside a total of E£900.

    Never negative. A refund larger than the order would otherwise produce one,
    and a negative base would quietly subtract from everything else she earned
    that month.
    """
    goods = int(total_piastres) - int(shipping_piastres) - int(tax_piastres)
    return max(goods, 0)


def base_for_order(
    *,
    total_piastres: int,
    shipping_piastres: int,
    tax_piastres: int,
    delivered: bool = False,
    stored_base_piastres: int | None = None,
) -> BaseDecision:
    """Decide this order's base, given what it was worth last time we looked.

    ``stored_base_piastres`` is the row as it stands. Passing it is what makes
    "delivery is final" mean anything: without the previous value there is
    nothing to hold on to, and the figure would follow Shopify wherever
    E-stebdal took it.
    """
    live = commission_base(total_piastres, shipping_piastres, tax_piastres)

    if not delivered:
        # Still travelling. A genuine edit before it ships should be reflected.
        return BaseDecision(piastres=live)

    # Delivered. Whatever it was worth on arrival is what it stays. Only an
    # order first seen *after* delivery has no stored value to keep, and takes
    # the live figure - see docs/limits.md.
    return BaseDecision(
        piastres=stored_base_piastres if stored_base_piastres is not None else live,
        is_final=True,
    )
