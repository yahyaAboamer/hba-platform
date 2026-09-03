"""GraphQL documents, kept in one place so the API surface is reviewable.

Fields are chosen to match order_index exactly. Anything attribution does not
need is deliberately not requested: a smaller query costs less against
Shopify's cost-based rate limit, and no customer field can leak into the
platform by accident if it was never asked for.

**The delivery, return and refund fields were not guessed.** GraphQL rejects an
entire document when one field is wrong, and this query runs on every webhook -
a mistaken field name here stops order ingestion outright. Each expression below
is the one HBA's live shop accepted when
``GET /api/operations/order-facts`` asked it, including the ``(first: 10)``
argument shapes, which differ between API versions.
"""

ORDER_FIELDS = """
    id
    legacyResourceId
    name
    createdAt
    updatedAt
    cancelledAt
    displayFinancialStatus
    displayFulfillmentStatus
    discountCodes
    currentSubtotalPriceSet { shopMoney { amount currencyCode } }
    currentTotalPriceSet { shopMoney { amount currencyCode } }
    # **The order as it was placed**, kept for display only.
    #
    # Shopify zeroes the `current*` sets when an order is cancelled, which is
    # correct for commission - §9.3 pays on what the customer actually paid -
    # and left a model's Orders screen printing a struck-through E£0.00 for a
    # cancelled order, because the value it wanted no longer existed anywhere.
    #
    # These two must never reach `calculate.py`. Paying on them would pay for
    # parcels that were cancelled.
    subtotalPriceSet { shopMoney { amount currencyCode } }
    totalPriceSet { shopMoney { amount currencyCode } }
    totalShippingPriceSet { shopMoney { amount currencyCode } }
    currentTotalTaxSet { shopMoney { amount currencyCode } }
    returnStatus
    fulfillments(first: 10) { displayStatus status deliveredAt inTransitAt updatedAt }
    refunds(first: 10) {
      id
      createdAt
      totalRefundedSet { shopMoney { amount currencyCode } }
      refundLineItems(first: 50) { nodes { subtotalSet { shopMoney { amount currencyCode } } } }
    }
"""

SINGLE_ORDER = f"""
query SingleOrder($id: ID!) {{
  order(id: $id) {{
    {ORDER_FIELDS}
  }}
}}
"""

ORDERS_PAGE = f"""
query OrdersPage($first: Int!, $after: String, $query: String) {{
  orders(first: $first, after: $after, query: $query, sortKey: UPDATED_AT) {{
    pageInfo {{ hasNextPage endCursor }}
    nodes {{
      {ORDER_FIELDS}
    }}
  }}
}}
"""

#: Cheapest possible query. Used to prove the credentials work.
SHOP_NAME = "query { shop { name myshopifyDomain } }"


#: The same fields, minus what a bulk operation refuses.
#:
#: Shopify's bulk export rejects the whole document for two reasons at once
#: here: a **connection inside a list field** is unsupported, and `nodes` may
#: not be used to select one - it insists on `edges { node }`. `refunds` is a
#: list and `refundLineItems` is a connection inside it, so no spelling of it
#: is accepted.
#:
#: The import therefore brings back the refund *total* and not its line items,
#: and `refunded_merchandise_piastres` stays 0 on an imported row until the
#: ordinary per-order sync fills it in - which it does through `SINGLE_ORDER`,
#: where the field is allowed.
#:
#: **That gap matters and is bounded.** Refunded merchandise reduces a
#: commission base (§9.3), so an imported month could over-report sales until
#: the reconcile sweep catches up. It is corrected rather than permanent, and
#: the alternative was an import that fails outright - which is what it did.
BULK_ORDER_FIELDS = "\n".join(
    line for line in ORDER_FIELDS.splitlines() if "refundLineItems" not in line
)
