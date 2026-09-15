"""How a model is doing: how often her code was used, and where she stands.

Phase 07A. M01 and M02, and D03 answered on 11 September 2026.

## A use is a delivery outcome, not a financial one

> If it was delivered, we count it. If the status was failed delivery, it
> doesn't count. If it's anything in between, it's counted as pending and
> accounted in the uses until it's either delivered, then it permanently
> counts, or failed, so we remove it from the counts.

**The obvious field is the wrong one.** `commission_state` folds three
different endings into one `void` — cancelled before shipping, fully refunded,
and failed delivery — and reading it here would silently drop cancellations and
refunds out of the count. A refund is a financial event; it says nothing about
whether her code was used and the parcel arrived.

So this reads `delivery_state` and excludes exactly one value. An order Shopify
has not told us about yet is "anything in between" and counts until it
resolves.

## Ranking is by sales; uses only break a tie

M02: the order is decided server-side by **sales**, and the peer values shown
are **uses** — never another model's sales, commission or salary. Uses break a
tie, and a tie on both gives equal rank with the places used up skipped:
`1, 1, 3`, never `1, 1, 2`.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.businesstime import parse_month
from app.models.affiliates import AccountKind, AffiliateProfile
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.orders import OrderIndex
from app.services.shopify.fulfilment import FAILED


@dataclass(frozen=True)
class Standing:
    """One model's line on the board."""

    affiliate_id: int
    name: str
    sales_piastres: int
    uses: int
    rank: int


def _use_count() -> object:
    """The count of orders that count as a use.

    Everything except a failed delivery. `is_distinct_from` rather than `!=`
    so a `NULL` delivery state — an order Shopify has not resolved yet — is
    counted rather than dropped: SQL comparison with NULL is neither true nor
    false, and `!= 'failed'` would quietly exclude exactly the orders D03 says
    to include.
    """
    return func.count(AttributedOrder.shopify_order_id).filter(
        OrderIndex.delivery_state.is_distinct_from(FAILED)
    )


def month_performance(db: Session, month: str) -> list[Standing]:
    """Every payable model's sales and uses for one month, ranked.

    One query for the whole board rather than one per model: this is the screen
    that shows twenty of them at once, and a loop here is the shape that made
    the products screen slow (03D).
    """
    month = parse_month(month)

    rows = db.execute(
        select(
            AffiliateProfile.id,
            AffiliateProfile.name,
            # Sales are what pays: delivered orders only, which is the live
            # rule. 05A's pending-inclusive policy is a preview and is not
            # what a rank is decided on.
            func.coalesce(
                func.sum(AttributedOrder.commission_base_piastres).filter(
                    AttributedOrder.commission_state == CommissionState.EARNED
                ),
                0,
            ),
            _use_count(),
        )
        .select_from(AffiliateProfile)
        .join(
            AttributedOrder,
            (AttributedOrder.affiliate_id == AffiliateProfile.id)
            & (AttributedOrder.business_month == month),
            isouter=True,
        )
        .join(
            OrderIndex,
            OrderIndex.shopify_order_id == AttributedOrder.shopify_order_id,
            isouter=True,
        )
        # **A house code is not a model** (§8, §17). It has real sales and no
        # payee, so it must not appear on a board of people, take a place from
        # somebody, or enter a count of models. Filtered in the query rather
        # than after it, so no caller can forget.
        .where(AffiliateProfile.account_kind != AccountKind.HOUSE)
        .group_by(AffiliateProfile.id, AffiliateProfile.name)
    ).all()

    payable = [
        (affiliate_id, name, int(sales or 0), int(uses or 0))
        for affiliate_id, name, sales, uses in rows
    ]
    return rank(payable)


def rank(rows: list[tuple[int, str, int, int]]) -> list[Standing]:
    """Order by sales, break ties on uses, and share a rank where both match.

    **Competition ranking**, which is what the owner described: two models tied
    at the top are both first and the next is third, because two places have
    been used up. `1, 1, 2` would say three models occupy two places.

    Sorted by name last so a board with several identical rows does not
    reshuffle itself between page loads for no reason. That is display order,
    not standing - the shared rank is what says they are level.
    """
    ordered = sorted(rows, key=lambda row: (-row[2], -row[3], row[1]))

    standings: list[Standing] = []
    for index, (affiliate_id, name, sales, uses) in enumerate(ordered):
        if index and (sales, uses) == (ordered[index - 1][2], ordered[index - 1][3]):
            place = standings[-1].rank
        else:
            # The number of models strictly ahead, plus one. This is what
            # produces the skip: after two firsts the next is third.
            place = index + 1
        standings.append(
            Standing(
                affiliate_id=affiliate_id,
                name=name,
                sales_piastres=sales,
                uses=uses,
                rank=place,
            )
        )
    return standings


def uses_for(db: Session, affiliate: AffiliateProfile, month: str) -> int:
    """How often her code was used in one month. D03.

    Her own figure, for her own card. **It will not move in step with her
    sales**, and that is correct rather than a fault: an order in transit is a
    use and is not yet a sale, so a parcel going out raises one and not the
    other. The card says so, because two numbers that disagree without
    explanation are a support message.
    """
    month = parse_month(month)
    return int(
        db.scalar(
            select(_use_count())
            .select_from(AttributedOrder)
            .join(
                OrderIndex,
                OrderIndex.shopify_order_id == AttributedOrder.shopify_order_id,
                isouter=True,
            )
            .where(AttributedOrder.affiliate_id == affiliate.id)
            .where(AttributedOrder.business_month == month)
        )
        or 0
    )


@dataclass(frozen=True)
class ProductSales:
    """One product, and what it sold through models' codes."""

    shopify_product_id: str | None
    title: str
    quantity: int
    sales_piastres: int


def top_products(db: Session, month: str, *, limit: int = 10) -> dict:
    """Which products sell through the models' codes. W11.

    ## Three different questions, and this answers only one

    W11 separates **selling through a code**, **owning something from the
    wardrobe** and **being asked to feature it**. They look alike and they are
    not: *a model can sell products she never received.* This counts what was
    actually bought through a code, and says nothing about who has what.

    ## Real line items, discounts and quantities

    W11 again, and it rules out the easy version: summing item names against
    undiscounted prices. So this reads `order_line_item` — the lines actually
    attributed to somebody's code — and uses **`discounted_total_piastres`**,
    which is what the customer paid after the model's own discount, times the
    quantity already baked into that total.

    Using the undiscounted price would credit a model with money the shop never
    took, and on a ten-percent code that is a ten-percent lie on every row.

    ## Grouped by product id, not by name

    A renamed product is the same product, and two products can share a name.
    The id is the stable identity (the prompt asks for exactly that), and the
    title is carried along for display from the line as it was written.

    **Lines whose product was deleted from Shopify have no id.** They are not
    dropped — that would make the totals disagree with the payroll figures
    beside them — but they cannot be grouped either, so they are reported
    together as their own figure and left out of the ranking.
    """
    from app.models.catalogue import OrderLineItem

    month = parse_month(month)

    rows = db.execute(
        select(
            OrderLineItem.shopify_product_id,
            func.min(OrderLineItem.title),
            func.sum(OrderLineItem.quantity),
            func.sum(OrderLineItem.discounted_total_piastres),
        )
        .select_from(OrderLineItem)
        .join(
            AttributedOrder,
            AttributedOrder.shopify_order_id == OrderLineItem.shopify_order_id,
        )
        .where(AttributedOrder.business_month == month)
        # Counted sales only, matching the figure every other screen calls
        # sales. A pending order has not sold anything yet and a failed one
        # never will.
        .where(AttributedOrder.commission_state == CommissionState.EARNED)
        .group_by(OrderLineItem.shopify_product_id)
    ).all()

    known = [
        ProductSales(
            shopify_product_id=product_id,
            title=title or "Untitled",
            quantity=int(quantity or 0),
            sales_piastres=int(sales or 0),
        )
        for product_id, title, quantity, sales in rows
        if product_id is not None
    ]
    gone = sum(
        int(sales or 0) for product_id, _, _, sales in rows if product_id is None
    )

    known.sort(key=lambda row: (-row.sales_piastres, -row.quantity, row.title))
    return {
        "month": month,
        "products": known[:limit],
        # Reported rather than dropped, so the totals on this screen still
        # reconcile with the sales figures elsewhere.
        "no_longer_in_shopify_piastres": gone,
        "total_piastres": sum(row.sales_piastres for row in known) + gone,
    }


def best_sellers_for(db: Session, affiliate_id: int) -> list[ProductSales]:
    """What sold through **her** code, all time, best first. W11.

    The approved portal's Wardrobe opens on *Your best sellers*, and the one
    thing it must never be is the programme's list with her name above it -
    a model shown what other people's codes sold would be told something
    untrue about her own work. So this is `top_products` asked about one
    affiliate and every month, and it reads the same lines the same way:
    what the customer paid after her discount.

    **Delivered orders only**, which is the live rule. The export counts
    pending orders too; that is 05A's pending-inclusive policy, which is still
    a preview and is not what anything shown to a model is decided on. A
    product whose Shopify record was deleted has no id to group by and is left
    out of the ranking, as it is on the admin list.
    """
    from app.models.catalogue import OrderLineItem

    rows = db.execute(
        select(
            OrderLineItem.shopify_product_id,
            func.min(OrderLineItem.title),
            func.sum(OrderLineItem.quantity),
            func.sum(OrderLineItem.discounted_total_piastres),
        )
        .select_from(OrderLineItem)
        .join(
            AttributedOrder,
            AttributedOrder.shopify_order_id == OrderLineItem.shopify_order_id,
        )
        .where(AttributedOrder.affiliate_id == affiliate_id)
        .where(AttributedOrder.commission_state == CommissionState.EARNED)
        .where(OrderLineItem.shopify_product_id.is_not(None))
        .group_by(OrderLineItem.shopify_product_id)
    ).all()

    found = [
        ProductSales(
            shopify_product_id=product_id,
            title=title or "Untitled",
            quantity=int(quantity or 0),
            sales_piastres=int(sales or 0),
        )
        for product_id, title, quantity, sales in rows
    ]
    found.sort(key=lambda row: (-row.sales_piastres, -row.quantity, row.title))
    return found
