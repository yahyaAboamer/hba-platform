"""Discount code verification.

Spec section 10.4. The gate that stops a mistyped code reaching production,
where it would silently attribute nothing until someone noticed the sales were
missing.
"""

import httpx
import pytest

from app.services.shopify.client import ShopifyClient, ShopifyMissingScope
from app.services.shopify.discounts import verify_discount_code

PERCENTAGE_NODE = {
    "id": "gid://shopify/DiscountCodeNode/1",
    "codeDiscount": {
        "__typename": "DiscountCodeBasic",
        "title": "NOUR10",
        "status": "ACTIVE",
        "usageLimit": None,
        "asyncUsageCount": 47,
        "customerGets": {
            "value": {"__typename": "DiscountPercentage", "percentage": 0.1}
        },
    },
}

EXPECTED_KEYS = {"exists", "code", "status", "discount_bp", "usage_count", "title"}


def _client(node, capture: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture["body"] = request.read().decode()
        return httpx.Response(200, json={"data": {"codeDiscountNodeByCode": node}})

    return ShopifyClient(
        shop_domain="s.myshopify.com",
        access_token="t",
        api_version="2026-07",
        transport=httpx.MockTransport(handler),
    )


def _node(value, *, status="ACTIVE", title="X", usage=1):
    return {
        "codeDiscount": {
            "__typename": "DiscountCodeBasic",
            "title": title,
            "status": status,
            "asyncUsageCount": usage,
            "customerGets": {"value": value},
        }
    }


# ── Finding a code ─────────────────────────────────────────────────────────────


def test_an_existing_code_is_reported_with_its_details():
    result = verify_discount_code(_client(PERCENTAGE_NODE), "NOUR10")
    assert result["exists"] is True
    assert result["status"] == "ACTIVE"
    assert result["usage_count"] == 47
    assert result["title"] == "NOUR10"
    assert result["discount_bp"] == 1000  # 10%


def test_a_missing_code_is_reported_not_raised():
    """A typo is an expected answer, not an exception."""
    result = verify_discount_code(_client(None), "NOUR1O")
    assert result["exists"] is False
    assert result["code"] == "NOUR1O"


def test_both_answers_carry_the_same_keys():
    """So a caller never has to guard for a field that is only sometimes there."""
    found = verify_discount_code(_client(PERCENTAGE_NODE), "NOUR10")
    missing = verify_discount_code(_client(None), "NOPE")
    assert set(found) == set(missing) == EXPECTED_KEYS


def test_the_code_is_normalised_before_lookup():
    """Codes are stored and compared upper-case; a lookup must match."""
    capture: dict = {}
    verify_discount_code(_client(PERCENTAGE_NODE, capture), "  nour10  ")
    assert "NOUR10" in capture["body"]


def test_the_normalised_code_is_what_comes_back():
    result = verify_discount_code(_client(None), "  nour10  ")
    assert result["code"] == "NOUR10"


# ── Statuses and shapes ────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["ACTIVE", "EXPIRED", "SCHEDULED"])
def test_a_code_is_reported_as_existing_whatever_its_status(status):
    """Existing-but-inactive is a different problem from not existing, and the
    person approving an affiliate needs to be able to tell them apart.
    """
    node = _node(
        {"__typename": "DiscountPercentage", "percentage": 0.1}, status=status
    )
    result = verify_discount_code(_client(node), "OLD10")
    assert result["exists"] is True
    assert result["status"] == status


def test_a_fixed_amount_discount_reports_no_percentage():
    """A fixed-amount code is valid; it simply has no percentage to compare."""
    node = _node(
        {
            "__typename": "DiscountAmount",
            "amount": {"amount": "50.00", "currencyCode": "EGP"},
        },
        title="FLAT50",
    )
    result = verify_discount_code(_client(node), "FLAT50")
    assert result["exists"] is True
    assert result["discount_bp"] is None


def test_a_percentage_of_zero_is_not_confused_with_absent():
    node = _node({"__typename": "DiscountPercentage", "percentage": 0.0})
    assert verify_discount_code(_client(node), "ZERO")["discount_bp"] == 0


@pytest.mark.parametrize(
    ("percentage", "expected_bp"),
    [(0.1, 1000), (0.05, 500), (0.15, 1500), (0.075, 750), (1.0, 10000)],
)
def test_percentages_convert_to_basis_points(percentage, expected_bp):
    node = _node({"__typename": "DiscountPercentage", "percentage": percentage})
    assert verify_discount_code(_client(node), "X")["discount_bp"] == expected_bp


def test_a_node_with_no_discount_body_does_not_crash():
    """Shopify returning a shape we do not expect must not take the page down."""
    result = verify_discount_code(_client({"id": "gid://x/1"}), "ODD")
    assert result["exists"] is True
    assert result["discount_bp"] is None
    assert set(result) == EXPECTED_KEYS


# ── What it must never do ──────────────────────────────────────────────────────


def test_verification_never_infers_a_commission_rate():
    """Spec 10.4: the customer discount and the commission are different.

    A creator may give customers 10% off while earning 5%. The result carries
    the discount only - anything named like a commission here would be a guess
    that is wrong precisely when it matters.
    """
    result = verify_discount_code(_client(PERCENTAGE_NODE), "NOUR10")
    assert "commission" not in " ".join(result).lower()
    assert "rate" not in " ".join(result).lower()


def test_a_missing_scope_is_raised_not_reported_as_a_missing_code():
    """The failure that would otherwise look identical to a typo.

    Without read_discounts every lookup returns nothing. Reporting that as
    "code does not exist" would have someone re-typing a perfectly good code
    while the real problem is an ungranted scope.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "errors": [
                    {
                        "message": "Access denied for codeDiscountNodeByCode field",
                        "extensions": {"code": "ACCESS_DENIED"},
                    }
                ]
            },
        )

    client = ShopifyClient(
        shop_domain="s.myshopify.com",
        access_token="t",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ShopifyMissingScope):
        verify_discount_code(client, "NOUR10")
