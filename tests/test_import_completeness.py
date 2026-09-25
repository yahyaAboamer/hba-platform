"""The order-import comparison: Shopify's IDs against ours, read-only.

A fake Shopify stands in for the real one; nothing here reaches a shop.
"""
from datetime import datetime, timezone

from app.models.orders import OrderIndex
from app.services.shopify.client import ShopifyError
from app.services.shopify.completeness import compare, render

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 9, 1, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)


class FakeShopify:
    """Pages of order IDs, and the scopes the app was granted."""

    def __init__(self, pages, scopes=("read_orders", "read_all_orders"), fail_on=None):
        self.pages = pages
        self.scopes = set(scopes)
        self.fail_on = fail_on
        self.calls = []

    def granted_scopes(self):
        return set(self.scopes)

    def execute(self, document, variables=None):
        self.calls.append(variables)
        index = len(self.calls) - 1
        if self.fail_on == index:
            raise ShopifyError("Shopify returned 503")
        ids = self.pages[index]
        return {
            "orders": {
                "edges": [
                    {"node": {"legacyResourceId": i, "name": f"#{i}", "createdAt": "2026-03-01T10:00:00Z"}}
                    for i in ids
                ],
                "pageInfo": {"hasNextPage": index + 1 < len(self.pages), "endCursor": f"c{index}"},
            }
        }


def _indexed(db, *ids):
    for i in ids:
        db.add(
            OrderIndex(
                shopify_order_id=str(i),
                order_number=f"#{i}",
                placed_at=datetime(2026, 3, 1, 10, tzinfo=timezone.utc),
                business_month="2026-03",
                discount_codes=[],
                subtotal_piastres=0,
                total_piastres=0,
                shipping_piastres=0,
                tax_piastres=0,
                currency="EGP",
            )
        )
    db.flush()


def test_every_page_read_and_every_id_imported_is_shown_complete(db):
    _indexed(db, 1, 2, 3)
    shop = FakeShopify([[1, 2], [3]])

    result = compare(db, shop, START, END, now=NOW)

    assert result.pages == 2 and result.last_page_reached
    assert shop.calls[1]["after"] == "c0"  # the second page asked for by cursor
    assert result.not_imported == [] and result.shown_complete
    assert result.verdict == "shown complete"
    assert "**Result: shown complete.**" in render(result, "test")


def test_an_order_shopify_has_and_the_index_lacks_is_named(db):
    _indexed(db, 1, 3)
    result = compare(db, FakeShopify([[1, 2], [3]]), START, END, now=NOW)

    assert result.not_imported == ["2"]
    assert not result.shown_complete
    # Read in full and unlimited, so this is a finding, not a doubt.
    assert result.verdict == "incomplete"
    report = render(result, "test")
    assert "In Shopify, not imported: 1" in report and "| 2 | #2 |" in report


def test_without_read_all_orders_an_old_window_is_a_recorded_limit(db):
    _indexed(db, 1)
    result = compare(db, FakeShopify([[1]], scopes=("read_orders",)), START, END, now=NOW)

    assert not result.shown_complete
    assert any("read_all_orders is not granted" in limit for limit in result.limits)
    # Limited access is inconclusive - never "complete", never a count of what is missing.
    assert result.verdict == "inconclusive"
    assert "**Result: inconclusive.**" in render(result, "test")


def test_unknown_scopes_are_a_limit_not_an_assumption(db):
    result = compare(db, FakeShopify([[]], scopes=()), START, END, now=NOW)
    assert any("unknown" in limit for limit in result.limits)
    assert not result.shown_complete


def test_a_failed_page_stops_the_claim(db):
    _indexed(db, 1, 2)
    result = compare(db, FakeShopify([[1], [2]], fail_on=1), START, END, now=NOW)

    assert result.error == "Shopify returned 503"
    assert not result.last_page_reached and not result.shown_complete
    assert result.verdict == "inconclusive"
    assert "Stopped by an error" in render(result, "test")


def test_an_order_repeated_across_pages_is_reported(db):
    _indexed(db, 1, 2)
    result = compare(db, FakeShopify([[1, 2], [2]]), START, END, now=NOW)

    assert result.repeated_on_later_page == ["2"]
    assert not result.shown_complete
    assert result.verdict == "inconclusive"


def test_missing_orders_under_limited_access_are_listed_but_the_verdict_stays_inconclusive(db):
    """What was read and is missing is real; how much else is missing is
    unknown. So the orders are named and the result is not *incomplete*."""
    _indexed(db, 1)
    result = compare(db, FakeShopify([[1, 2]], scopes=("read_orders",)), START, END, now=NOW)

    assert result.not_imported == ["2"]
    assert result.verdict == "inconclusive"
    report = render(result, "test")
    assert "**Result: inconclusive.**" in report and "others may be too" in report
