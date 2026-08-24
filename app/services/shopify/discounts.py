"""Discount code verification.

Approving an affiliate is blocked until their code is confirmed to exist in
Shopify. That removes the mistyped-code failure at source: a code that does not
exist attributes nothing, silently, until somebody notices the sales are
missing months later.

**What is deliberately absent: any inference of a commission rate.** The
customer discount and the affiliate's commission are different commercial
things - a creator may give customers 10% off while earning 5% - so this
returns the discount Shopify holds and lets the caller compare it against what
was agreed. Guessing one from the other would be wrong roughly whenever it
mattered.
"""

from app.services.shopify.client import ShopifyClient

#: The scope this needs. Named here so a missing grant produces a message that
#: says what to add, rather than an opaque access error.
REQUIRED_SCOPE = "read_discounts"

CODE_LOOKUP = """
query CodeByCode($code: String!) {
  codeDiscountNodeByCode(code: $code) {
    id
    codeDiscount {
      __typename
      ... on DiscountCodeBasic {
        title
        status
        usageLimit
        asyncUsageCount
        customerGets {
          value {
            __typename
            ... on DiscountPercentage { percentage }
            ... on DiscountAmount { amount { amount currencyCode } }
          }
        }
      }
    }
  }
}
"""


def _not_found(code: str) -> dict:
    return {
        "exists": False,
        "code": code,
        "status": None,
        "discount_bp": None,
        "usage_count": None,
        "title": None,
    }


def verify_discount_code(client: ShopifyClient, code: str) -> dict:
    """Look a code up in Shopify.

    A missing code is a normal answer, not an exception: it is the likeliest
    result of a typo, and the caller needs to show it rather than crash.

    The same six keys come back in every branch, so a caller never has to guard
    for a missing field.
    """
    normalised = str(code or "").strip().upper()
    data = client.execute(CODE_LOOKUP, {"code": normalised})
    node = data.get("codeDiscountNodeByCode")

    if not node:
        return _not_found(normalised)

    discount = node.get("codeDiscount") or {}
    value = ((discount.get("customerGets") or {}).get("value")) or {}

    discount_bp = None
    if value.get("__typename") == "DiscountPercentage":
        percentage = value.get("percentage")
        if percentage is not None:
            # Shopify expresses 10% as 0.1. Basis points keep it an integer,
            # which is how every rate is stored here (ADR 0002).
            discount_bp = int(round(float(percentage) * 10_000))

    return {
        "exists": True,
        "code": normalised,
        "status": discount.get("status"),
        "discount_bp": discount_bp,
        "usage_count": discount.get("asyncUsageCount"),
        "title": discount.get("title"),
    }
