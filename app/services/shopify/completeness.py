"""Is the order import complete? Shopify's order IDs against ours. Read-only.

`order_import_report.py` reads only what was imported, so it can show clues
and never proof. This is the proof: every order Shopify lists for a period,
by ID, against every order the platform indexed for the same period - with
the listing's pagination accounted for page by page, and anything that limits
what Shopify would show recorded beside the result rather than discovered
later.

**It reads, and never writes** - neither to Shopify (the queries are reads, and
the app holds no write scope, ADR 0015) nor to the database.

What counts as *complete* here, and only here:

- every page of Shopify's listing was fetched, ending on `hasNextPage: false`,
  with no page repeating an order already seen;
- nothing limits the window: `read_all_orders` is granted (without it Shopify
  answers only the last 60 days, silently);
- every Shopify order ID for the period is in the index.

The verdict is one of three, never two:

- **shown complete** - all three hold;
- **incomplete** - Shopify's listing was read in full, with nothing limiting
  it, and orders it lists are missing from the index;
- **inconclusive** - the listing could not be read in full or something
  limited it (an error, a page never reached, a repeated page, a missing or
  unknown scope). Missing orders found within what *was* read are still
  listed, but nothing here can say the import is complete - or how incomplete.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orders import OrderIndex
from app.services.shopify.client import ShopifyClient, ShopifyError

PAGE_SIZE = 250

ORDER_IDS = """
query OrderIds($query: String!, $after: String) {
  orders(first: 250, after: $after, query: $query, sortKey: CREATED_AT) {
    edges { node { legacyResourceId name createdAt } }
    pageInfo { hasNextPage endCursor }
  }
}
"""

#: Shopify's plain `read_orders` reaches back this far; older needs
#: `read_all_orders`.
PLAIN_SCOPE_WINDOW = timedelta(days=60)


@dataclass
class Comparison:
    start: datetime
    end: datetime
    shopify: dict[str, tuple[str, str]] = field(default_factory=dict)
    imported: dict[str, str] = field(default_factory=dict)
    pages: int = 0
    last_page_reached: bool = False
    repeated_on_later_page: list[str] = field(default_factory=list)
    limits: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def not_imported(self) -> list[str]:
        return sorted(set(self.shopify) - set(self.imported), key=_numeric)

    @property
    def not_in_shopify(self) -> list[str]:
        return sorted(set(self.imported) - set(self.shopify), key=_numeric)

    @property
    def access_complete(self) -> bool:
        """Shopify's listing for the period was read in full, unlimited."""
        return (
            self.error is None
            and self.last_page_reached
            and not self.repeated_on_later_page
            and not self.limits
        )

    @property
    def verdict(self) -> str:
        if not self.access_complete:
            return "inconclusive"
        return "incomplete" if self.not_imported else "shown complete"

    @property
    def shown_complete(self) -> bool:
        return (
            self.error is None
            and self.last_page_reached
            and not self.repeated_on_later_page
            and not self.limits
            and not self.not_imported
        )


def _numeric(order_id: str) -> tuple[int, str]:
    return (int(order_id), "") if order_id.isdigit() else (0, order_id)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compare(
    db: Session,
    client: ShopifyClient,
    start: datetime,
    end: datetime,
    *,
    now: datetime | None = None,
    max_pages: int = 10_000,
) -> Comparison:
    """Shopify's orders created in `[start, end)` against the index's."""
    result = Comparison(start=start, end=end)
    now = now or datetime.now(timezone.utc)

    granted = client.granted_scopes()
    if not granted:
        result.limits.append(
            "The scopes Shopify granted are unknown (a static token reports none), "
            "so it cannot be shown that orders older than 60 days are visible."
        )
    elif "read_all_orders" not in granted and start < now - PLAIN_SCOPE_WINDOW:
        result.limits.append(
            "read_all_orders is not granted: Shopify returns only the last 60 days, "
            f"so orders before {_iso(now - PLAIN_SCOPE_WINDOW)[:10]} are not visible "
            "to this comparison."
        )

    query = f"created_at:>='{_iso(start)}' created_at:<'{_iso(end)}'"
    after: str | None = None
    try:
        while result.pages < max_pages:
            data = client.execute(ORDER_IDS, {"query": query, "after": after})
            orders = data["orders"]
            result.pages += 1
            for edge in orders["edges"]:
                node = edge["node"]
                order_id = str(node["legacyResourceId"])
                if order_id in result.shopify:
                    result.repeated_on_later_page.append(order_id)
                result.shopify[order_id] = (node.get("name") or "", node.get("createdAt") or "")
            if not orders["pageInfo"]["hasNextPage"]:
                result.last_page_reached = True
                break
            after = orders["pageInfo"]["endCursor"]
        else:
            result.limits.append(f"Stopped after {max_pages} pages without reaching the last.")
    except ShopifyError as exc:
        # Our own text only: the client never puts a credential in a message.
        result.error = str(exc)

    result.imported = {
        row.shopify_order_id: row.order_number
        for row in db.execute(
            select(OrderIndex.shopify_order_id, OrderIndex.order_number)
            .where(OrderIndex.placed_at >= start)
            .where(OrderIndex.placed_at < end)
        )
    }
    return result


def render(result: Comparison, environment: str) -> str:
    """The comparison as Markdown, for the owner."""
    lines = [
        "# Order-import comparison with Shopify",
        "",
        f"Environment: **{environment}**. Orders created from {_iso(result.start)} "
        f"to before {_iso(result.end)}. Read-only.",
        "",
        f"**Result: {result.verdict}.**",
        "",
        {
            "shown complete": "Every page of Shopify's listing was read, nothing limited it, "
            "and every order it lists for the period is imported.",
            "incomplete": "Every page of Shopify's listing was read and nothing limited it; "
            "the orders below are in Shopify and not imported.",
            "inconclusive": "Shopify's listing could not be read in full for this period "
            "(see *Access limits* and the listing below), so this cannot show the import "
            "complete. Any order listed as not imported is missing; others may be too.",
        }[result.verdict],
        "",
        "## Shopify's listing",
        "",
        f"- {len(result.shopify):,} orders in {result.pages} page"
        f"{'s' if result.pages != 1 else ''} of up to {PAGE_SIZE}.",
        f"- Last page reached: **{'yes' if result.last_page_reached else 'no'}**.",
    ]
    if result.repeated_on_later_page:
        lines.append(
            f"- {len(result.repeated_on_later_page)} order(s) appeared on more than one page "
            "- the listing moved while it was read; run it again."
        )
    if result.error:
        lines.append(f"- **Stopped by an error:** {result.error}")
    lines += ["", "## Access limits", ""]
    lines += [f"- {limit}" for limit in result.limits] or ["- None found."]
    lines += [
        "",
        "## Against the index",
        "",
        f"- {len(result.imported):,} orders imported for the same period.",
        f"- **In Shopify, not imported: {len(result.not_imported):,}**",
        f"- Imported, not in Shopify's listing: {len(result.not_in_shopify):,} "
        "(deleted in Shopify since, or placed outside the period by a clock difference)",
    ]
    if result.not_imported:
        lines += ["", "| Shopify order ID | Order | Created |", "|---|---|---|"]
        for order_id in result.not_imported[:200]:
            name, created = result.shopify[order_id]
            lines.append(f"| {order_id} | {name} | {created} |")
        if len(result.not_imported) > 200:
            lines.append(f"| ... {len(result.not_imported) - 200} more | | |")
    return "\n".join(lines) + "\n"
