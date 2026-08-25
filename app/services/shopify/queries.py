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
