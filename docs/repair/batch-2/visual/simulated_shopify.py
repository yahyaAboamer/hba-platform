"""The application, with Shopify replaced by a simulated shop.

For exercising *Refresh now* in the browser without a shop. Everything is the
real application - the route, the worker, the reconciliation sweep, the order
index - except the HTTP transport under the Shopify client, which answers from
here. Nothing leaves the machine.

What the shop answers is read, on every request, from the file named by
``SIMULATED_SHOPIFY_MODE`` (default ``$TMPDIR/simulated-shopify-mode``):

    ok      two orders, updated today
    429     Too Many Requests, every time
    401     the credentials refused
    slow    two orders, after a five-second wait (to see *Refreshing*)

Run it like uvicorn, against the throwaway database only (README.md):

    DATABASE_URL=...hba_browser APP_ENV=development GO_LIVE_MONTH=2026-06 \\
      SESSION_SECRET=browser-review-only \\
      SHOPIFY_SHOP_DOMAIN=simulated.myshopify.com SHOPIFY_ACCESS_TOKEN=simulated \\
      .venv/Scripts/python.exe docs/repair/batch-2/visual/simulated_shopify.py
"""

import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

MODE_FILE = Path(
    os.environ.get(
        "SIMULATED_SHOPIFY_MODE",
        Path(tempfile.gettempdir()) / "simulated-shopify-mode",
    )
)


def _mode() -> str:
    try:
        return MODE_FILE.read_text().strip() or "ok"
    except FileNotFoundError:
        return "ok"


def _order(order_id: str) -> dict:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    money = lambda amount: {"shopMoney": {"amount": amount, "currencyCode": "EGP"}}  # noqa: E731
    return {
        "id": f"gid://shopify/Order/{order_id}",
        "legacyResourceId": order_id,
        "name": f"#{order_id}",
        "createdAt": now,
        "updatedAt": now,
        "cancelledAt": None,
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "FULFILLED",
        "discountCodes": [],
        "currentSubtotalPriceSet": money("100.00"),
        "currentTotalPriceSet": money("110.00"),
        "totalShippingPriceSet": money("10.00"),
        "currentTotalTaxSet": money("0.00"),
    }


def _answer(request: httpx.Request) -> httpx.Response:
    body = request.read().decode()
    if "mutation" in body:
        # The refresh reads. A write reaching here is a defect, loudly.
        return httpx.Response(400, json={"errors": [{"message": "no writes"}]})
    mode = _mode()
    if mode == "429":
        return httpx.Response(429, json={"errors": "Too Many Requests"})
    if mode == "401":
        return httpx.Response(401, json={"errors": "Unauthorized"})
    if mode == "slow":
        time.sleep(5)
    return httpx.Response(200, json={"data": {"orders": {
        "pageInfo": {"hasNextPage": False, "endCursor": None},
        "nodes": [_order("990001"), _order("990002")],
    }}})


def main() -> None:
    import app.services.shopify.sync as sync
    from app.services.shopify.client import ShopifyClient

    def build_client() -> ShopifyClient:
        client = ShopifyClient(
            shop_domain="simulated.myshopify.com",
            access_token="simulated",
            transport=httpx.MockTransport(_answer),
        )
        client.retry_base_seconds = 0
        return client

    sync.build_client = build_client
    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8123")))


if __name__ == "__main__":
    main()
