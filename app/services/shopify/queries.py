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


# ── The catalogue ────────────────────────────────────────────────────────────
#
# Needs `read_products`, which is a **separate grant** from the order scopes
# above. `client.REQUIRED_SCOPES` carries it, and `/api/operations/shopify-scopes`
# is what proves it is actually granted rather than merely typed into the Dev
# Dashboard - the two are not the same thing, and an already-issued token never
# gains a scope retroactively.
#
# Deliberately small. One image, not a gallery: the roster shows a thumbnail
# and storing every media node would be storing what nothing reads. No
# description, no SEO block, no metafields - the same rule the order query
# follows, that a field never asked for cannot leak.

PRODUCT_FIELDS = """
    id
    legacyResourceId
    title
    handle
    status
    updatedAt
    featuredMedia {
      ... on MediaImage {
        image { url altText }
      }
    }
    variants(first: 100) {
      nodes {
        id
        legacyResourceId
        title
        sku
        position
      }
    }
"""

PRODUCTS_PAGE = f"""
query ProductsPage($first: Int!, $after: String) {{
  products(first: $first, after: $after, sortKey: UPDATED_AT) {{
    pageInfo {{ hasNextPage endCursor }}
    nodes {{
      {PRODUCT_FIELDS}
    }}
  }}
}}
"""

# ── What was in an order ─────────────────────────────────────────────────────
#
# Its own document rather than fields bolted onto `ORDER_FIELDS`, for one
# reason: **GraphQL rejects an entire document when one field is wrong.**
# `ORDER_FIELDS` runs on every webhook, and adding an unproven selection to it
# would risk stopping commission ingestion outright to gain a wardrobe.
#
# That is 03A's requirement in as many words - *new recipient field denial
# cannot break existing commission sync* - and keeping the documents apart is
# what makes it structural rather than careful.
#
# `discountedTotalSet` is after the customer's discounts, which is the basis
# W11 asks for. `originalTotalSet` is kept beside it because their difference
# is the only evidence a discount applied at all.

ORDER_LINE_ITEMS = """
query OrderLineItems($id: ID!) {
  order(id: $id) {
    id
    legacyResourceId
    lineItems(first: 100) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        title
        sku
        quantity
        variantTitle
        product { id legacyResourceId }
        variant { id legacyResourceId }
        discountedTotalSet { shopMoney { amount currencyCode } }
        originalTotalSet { shopMoney { amount currencyCode } }
      }
    }
  }
}
"""


# ── Who a parcel was sent to ─────────────────────────────────────────────────
#
# **The narrowest document in this file, on purpose.** W03 matches on the
# shipping-address phone and nothing else, so nothing else is asked for: no
# customer block, no name, no address lines, no email. A field never requested
# cannot leak, and this one runs across the whole shop's history.
#
# `shippingAddress.phone` is **protected customer data**. Shopify gates it on
# an app-level approval that is separate from any scope, so a shop that grants
# every scope may still return `null` here. That is why matching records a
# reason rather than assuming a null means "no phone was on the order" -
# `no_phone` and "we are not allowed to see it" look identical from here, and
# `/api/operations/order-facts` is what tells them apart against the real shop.
#
# Its own document rather than fields added to `ORDER_FIELDS`, for the reason
# 03A established: GraphQL rejects an entire document when one field is
# refused, and `ORDER_FIELDS` runs on every webhook. A denial here must cost a
# wardrobe, never commission.

ORDERS_RECIPIENT_PAGE = """
query OrdersRecipientPage($first: Int!, $after: String, $query: String) {
  orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      legacyResourceId
      shippingAddress { phone }
    }
  }
}
"""


#: One order's shipping phone, for matching a parcel that arrived live.
#:
#: The page query above walks history; this asks about a single order, which is
#: what a webhook gives us. Same protected field, same reason it is its own
#: document rather than fields added to `ORDER_FIELDS`: a denial must cost a
#: wardrobe, never commission.
ORDER_RECIPIENT = """
query OrderRecipient($id: ID!) {
  order(id: $id) {
    id
    legacyResourceId
    shippingAddress { phone }
  }
}
"""
