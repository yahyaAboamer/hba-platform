# Phase 2: Shopify Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring every Shopify order into the platform — historically and continuously — with a durability model that survives restarts, plus the discount-code verification that Phase 3's affiliate onboarding depends on.

**Architecture:** A thin GraphQL client over Shopify's Admin API with cost-aware retry. Every order lands in `order_index`, a deliberately small row holding only what attribution needs. Historical loading uses Shopify's Bulk Operations API rather than pagination. Live updates arrive by webhook, whose only job is to verify the signature, record an immutable receipt, and enqueue work — processing happens in a worker that leases jobs from Postgres, so nothing is lost to a restart. A reconciliation sweep catches whatever webhooks miss.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, psycopg 3, httpx, Shopify Admin GraphQL API (pinned version), pytest.

**Spec:** `docs/superpowers/specs/2026-08-22-hba-platform-v1-design.md` — §10 in particular.

**Repository:** `hba-platform`, branching from `main` as in Phase 1: one branch per task, PR, review, merge.

## Global Constraints

Everything from Phase 1 still applies. These matter most here:

- **The business month is derived in `Africa/Cairo`, never a fixed offset.** (Spec §7) Every order's `business_month` comes from `app.core.businesstime.business_month`. An order placed at 21:30 UTC on 31 August belongs to September.
- **All money is integer piastres.** Shopify returns decimal strings like `"1157.00"`; they are converted once, at the boundary, and never held as floats. (Spec §4.7)
- **Append-only tables reject UPDATE, DELETE and TRUNCATE** via the existing `reject_mutation()` trigger. `integration_event` joins that set. (Spec §4.8)
- **No extra infrastructure.** No Redis, no queue service. Postgres provides the queue. One Railway service, one replica. (Spec §19)
- **Secrets never enter the repository, logs, or audit records.** The Shopify token is masked by the existing audit masking (`api_key`, `token` patterns), and no log line prints it.
- **Timeouts on every outbound call.** A hung request must fail, not block the worker. Found the hard way in Phase 1.
- **Permissions are enforced server-side** using `require_permission`. (Spec §6.3)

## What is deliberately NOT in this phase

- **`attributed_order`** — it needs affiliates and discount-code periods, which arrive in Phase 3. Phase 2 records *which codes an order used*; deciding *whose* they are comes later.
- **`notification_outbox`** — nothing sends email yet. Failures surface in the operational view instead, which is what §10.5 asks for. The outbox arrives with the phase that first sends a message.
- **Backfill on code registration** — triggered by registering a code, which is Phase 3.

---

## File Structure

```
app/
├── config.py                      # extended with Shopify settings
├── worker.py                      # background worker loop, started with the app
├── models/
│   ├── orders.py                  # order_index
│   └── integration.py             # integration_event, background_job
├── services/
│   ├── jobs.py                    # enqueue, lease, complete, fail
│   ├── reconcile.py               # sweep for missed orders
│   └── shopify/
│       ├── __init__.py
│       ├── client.py              # GraphQL transport, auth, retry
│       ├── queries.py             # GraphQL documents, in one place
│       ├── normalise.py           # Shopify order node -> order_index values
│       ├── bulk.py                # Bulk Operations import
│       ├── webhooks.py            # HMAC verification
│       └── discounts.py           # codeDiscountNodeByCode
└── api/
    ├── webhooks.py                # POST /api/webhooks/shopify
    └── operations.py              # sync status, failed jobs, unregistered codes
```

`services/shopify/` stays a boundary: everything that knows Shopify's shape lives there, and nothing outside it parses a Shopify payload.

---

## Task 1: Shopify configuration and GraphQL client

**Files:**
- Modify: `app/config.py`
- Create: `app/services/shopify/__init__.py`, `app/services/shopify/client.py`, `app/services/shopify/queries.py`
- Test: `tests/test_shopify_client.py`

**Interfaces:**
- Consumes: `app.config.settings`
- Produces:
  - `ShopifyError`, `ShopifyThrottled`, `ShopifyNotConfigured` exceptions
  - `ShopifyMissingScope` exception
  - `ShopifyClient(shop_domain, client_id="", client_secret="", access_token="", api_version=..., timeout_seconds=...)` with `.execute(document, variables) -> dict`, `.granted_scopes() -> set[str]`
  - `REQUIRED_SCOPES: frozenset[str]`
  - `settings.shopify_shop_domain`, `.shopify_client_id`, `.shopify_client_secret`, `.shopify_access_token`, `.shopify_api_version`, `.shopify_webhook_secret`, `.shopify_timeout_seconds`, `.shopify_configured`

**Authentication.** HBA's app is a Dev Dashboard app, so there is no permanent
token: one is exchanged from the client credentials against
`/admin/oauth/access_token` and expires. The client caches it until shortly
before expiry and re-exchanges on a 401, so an expired token mid-request costs
one retry rather than a failed job.

The token response reports the scopes actually granted. The client keeps them,
which lets the platform report a missing scope as a clear message instead of an
opaque Shopify permission error hours later.

- [ ] **Step 1: Add httpx and Shopify settings**

Add to `pyproject.toml` dependencies:

```toml
    "httpx>=0.27,<1",
```

Then extend `app/config.py`, inside `Settings`:

```python
    # Shopify. Blank by default so the platform runs without it - Phase 1's
    # health checks and auth must keep working on a machine with no credentials.
    shopify_shop_domain: str = ""
    # HBA's app is a Dev Dashboard app, so tokens are short-lived and exchanged
    # from the client credentials rather than configured statically. The static
    # token remains supported for an older admin-created app.
    shopify_client_id: str = ""
    shopify_client_secret: str = ""
    shopify_access_token: str = ""
    shopify_webhook_secret: str = ""
    # Pinned deliberately. Shopify deprecates versions on a schedule, and an
    # unpinned client would change behaviour without a deploy.
    shopify_api_version: str = "2026-07"
    shopify_timeout_seconds: float = 20.0

    @property
    def shopify_configured(self) -> bool:
        has_credentials = bool(self.shopify_client_id and self.shopify_client_secret)
        return bool(self.shopify_shop_domain and (has_credentials or self.shopify_access_token))
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_shopify_client.py`:

```python
"""Shopify GraphQL transport."""

import httpx
import pytest

from app.services.shopify.client import (
    ShopifyClient,
    ShopifyError,
    ShopifyNotConfigured,
    ShopifyThrottled,
)


def _client(handler) -> ShopifyClient:
    transport = httpx.MockTransport(handler)
    return ShopifyClient(
        shop_domain="hbawear.myshopify.com",
        access_token="shpat_test",
        api_version="2026-07",
        transport=transport,
    )


def test_a_successful_query_returns_the_data_block():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"shop": {"name": "HBA"}}})

    assert _client(handler).execute("{ shop { name } }", {}) == {"shop": {"name": "HBA"}}


def test_the_token_is_sent_in_the_shopify_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("X-Shopify-Access-Token")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"data": {}})

    _client(handler).execute("{ shop { name } }", {})
    assert seen["token"] == "shpat_test"
    # The API version is pinned into the path, not negotiated.
    assert seen["url"] == (
        "https://hbawear.myshopify.com/admin/api/2026-07/graphql.json"
    )


def test_graphql_errors_are_raised_not_returned():
    """A 200 with an errors block is still a failure.

    GraphQL reports errors inside a successful HTTP response, so checking the
    status code alone would treat a failed query as valid empty data.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"errors": [{"message": "Field 'nope' doesn't exist"}]}
        )

    with pytest.raises(ShopifyError) as caught:
        _client(handler).execute("{ nope }", {})
    assert "doesn't exist" in str(caught.value)


def test_throttling_raises_a_distinct_error():
    """Throttling is retryable; a malformed query is not. They must differ."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "errors": [
                    {"message": "Throttled", "extensions": {"code": "THROTTLED"}}
                ]
            },
        )

    with pytest.raises(ShopifyThrottled):
        _client(handler).execute("{ shop { name } }", {})


def test_throttling_is_retried_and_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(
                200,
                json={
                    "errors": [
                        {"message": "Throttled", "extensions": {"code": "THROTTLED"}}
                    ]
                },
            )
        return httpx.Response(200, json={"data": {"ok": True}})

    client = _client(handler)
    client.retry_base_seconds = 0  # keep the test fast
    assert client.execute("{ ok }", {}) == {"ok": True}
    assert calls["n"] == 3


def test_retries_give_up_rather_than_looping_forever():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "errors": [
                    {"message": "Throttled", "extensions": {"code": "THROTTLED"}}
                ]
            },
        )

    client = _client(handler)
    client.retry_base_seconds = 0
    with pytest.raises(ShopifyThrottled):
        client.execute("{ ok }", {})


def test_a_server_error_is_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="upstream boom")
        return httpx.Response(200, json={"data": {"ok": True}})

    client = _client(handler)
    client.retry_base_seconds = 0
    assert client.execute("{ ok }", {}) == {"ok": True}


def test_an_auth_failure_is_not_retried():
    """A bad token will not fix itself; retrying only wastes the rate limit."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, text="Invalid API key or access token")

    client = _client(handler)
    client.retry_base_seconds = 0
    with pytest.raises(ShopifyError):
        client.execute("{ ok }", {})
    assert calls["n"] == 1


def test_a_non_json_response_fails_clearly():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    with pytest.raises(ShopifyError):
        _client(handler).execute("{ ok }", {})


def test_missing_credentials_raise_a_distinct_error():
    with pytest.raises(ShopifyNotConfigured):
        ShopifyClient(shop_domain="", access_token="", api_version="2026-07")


def test_the_token_never_appears_in_an_error_message():
    """Errors are logged and surfaced; a token in one would leak it."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = _client(handler)
    client.retry_base_seconds = 0
    with pytest.raises(ShopifyError) as caught:
        client.execute("{ ok }", {})
    assert "shpat_test" not in str(caught.value)
```

- [ ] **Step 3: Run it to verify it fails**

```bash
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
./.venv/Scripts/python.exe -m pytest tests/test_shopify_client.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.services.shopify'`

- [ ] **Step 4: Write the client**

Create `app/services/shopify/__init__.py`:

```python
"""Everything that knows Shopify's shape lives behind this boundary."""
```

Create `app/services/shopify/client.py`:

```python
"""Shopify Admin GraphQL transport.

Two things make this more than a thin HTTP wrapper.

GraphQL reports failures inside a 200 response, so the status code alone says
nothing - a failed query would otherwise look like valid empty data. Every
response is therefore inspected for an errors block.

Shopify rate-limits by query cost rather than request count, returning a
THROTTLED error rather than a 429. That is retryable, while a malformed query
or a bad token is not, so they are raised as different exceptions and only the
retryable ones are retried.
"""

import time
from typing import Any

import httpx


class ShopifyError(RuntimeError):
    """A Shopify request failed in a way that will not fix itself."""


class ShopifyThrottled(ShopifyError):
    """Rate limited. Retryable."""


class ShopifyNotConfigured(ShopifyError):
    """No shop domain or access token is configured."""


MAX_ATTEMPTS = 4
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class ShopifyClient:
    def __init__(
        self,
        shop_domain: str,
        access_token: str,
        api_version: str,
        timeout_seconds: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not shop_domain or not access_token:
            raise ShopifyNotConfigured(
                "Shopify is not configured: set SHOPIFY_SHOP_DOMAIN and "
                "SHOPIFY_ACCESS_TOKEN"
            )
        self.shop_domain = shop_domain
        self._access_token = access_token
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds
        self.retry_base_seconds = 1.0
        self._transport = transport

    @property
    def endpoint(self) -> str:
        return f"https://{self.shop_domain}/admin/api/{self.api_version}/graphql.json"

    def _post(self, document: str, variables: dict) -> httpx.Response:
        with httpx.Client(
            transport=self._transport, timeout=self.timeout_seconds
        ) as http:
            return http.post(
                self.endpoint,
                json={"query": document, "variables": variables or {}},
                headers={
                    "X-Shopify-Access-Token": self._access_token,
                    "Content-Type": "application/json",
                },
            )

    def execute(self, document: str, variables: dict | None = None) -> dict[str, Any]:
        """Run a GraphQL document and return its data block.

        Retries throttling and transient server errors with exponential
        backoff. Never retries an authentication or query error: a bad token
        will not fix itself, and retrying only burns the rate limit.
        """
        last_error: ShopifyError | None = None

        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                time.sleep(self.retry_base_seconds * (2 ** (attempt - 1)))

            try:
                response = self._post(document, variables or {})
            except httpx.TimeoutException as exc:
                last_error = ShopifyError(f"Shopify request timed out: {exc!s}")
                continue
            except httpx.HTTPError as exc:
                last_error = ShopifyError(f"Shopify request failed: {type(exc).__name__}")
                continue

            if response.status_code in RETRYABLE_STATUS:
                last_error = ShopifyError(
                    f"Shopify returned {response.status_code}"
                )
                continue
            if response.status_code >= 400:
                # 401/403/404 and friends: not retryable. The body may echo
                # request details, so only the status is surfaced.
                raise ShopifyError(f"Shopify returned {response.status_code}")

            try:
                payload = response.json()
            except ValueError:
                raise ShopifyError(
                    "Shopify returned a non-JSON response"
                ) from None

            errors = payload.get("errors")
            if errors:
                codes = {
                    str((item.get("extensions") or {}).get("code", "")).upper()
                    for item in errors
                    if isinstance(item, dict)
                }
                messages = "; ".join(
                    str(item.get("message", "")) for item in errors if isinstance(item, dict)
                )
                if "THROTTLED" in codes:
                    last_error = ShopifyThrottled(f"Shopify throttled: {messages}")
                    continue
                raise ShopifyError(f"Shopify GraphQL error: {messages}")

            return payload.get("data") or {}

        raise last_error or ShopifyError("Shopify request failed")
```

- [ ] **Step 5: Create the query module**

Create `app/services/shopify/queries.py`:

```python
"""GraphQL documents, kept in one place so the API surface is reviewable."""

# Fields are chosen to match order_index exactly. Anything not needed for
# attribution is deliberately not requested: a smaller query costs less
# against Shopify's cost-based rate limit and cannot leak customer data by
# accident.
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

SHOP_NAME = "query { shop { name myshopifyDomain } }"
```

- [ ] **Step 6: Run the tests**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_shopify_client.py -v
```

Expected: all 11 PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml app/config.py app/services/shopify tests/test_shopify_client.py
git commit -m "feat: Shopify GraphQL client with cost-aware retry"
```

---

## Task 2: The order index and normalisation

**Files:**
- Create: `app/models/orders.py`, `app/services/shopify/normalise.py`
- Modify: `app/models/__init__.py`
- Create: an Alembic migration
- Test: `tests/test_shopify_normalise.py`, `tests/test_order_index.py`

**Interfaces:**
- Consumes: `app.core.businesstime.business_month`, `app.db.Base`
- Produces:
  - `OrderIndex` model
  - `normalise_order(node: dict) -> dict` returning keys matching `OrderIndex` columns
  - `money_to_piastres(amount: str | None) -> int`
  - `upsert_order_index(db, values: dict) -> OrderIndex`

- [ ] **Step 1: Write the failing normalisation test**

Create `tests/test_shopify_normalise.py`:

```python
"""Turning a Shopify order node into an order_index row."""

import pytest

from app.services.shopify.normalise import money_to_piastres, normalise_order


def _node(**overrides) -> dict:
    node = {
        "id": "gid://shopify/Order/5123456789",
        "legacyResourceId": "5123456789",
        "name": "#29115",
        "createdAt": "2026-08-18T16:36:00Z",
        "updatedAt": "2026-08-20T09:00:00Z",
        "cancelledAt": None,
        "displayFinancialStatus": "PARTIALLY_PAID",
        "displayFulfillmentStatus": "FULFILLED",
        "discountCodes": ["HBA10"],
        "currentSubtotalPriceSet": {"shopMoney": {"amount": "1675.00", "currencyCode": "EGP"}},
        "currentTotalPriceSet": {"shopMoney": {"amount": "1752.00", "currencyCode": "EGP"}},
        "totalShippingPriceSet": {"shopMoney": {"amount": "95.00", "currencyCode": "EGP"}},
        "currentTotalTaxSet": {"shopMoney": {"amount": "0.00", "currencyCode": "EGP"}},
    }
    node.update(overrides)
    return node


# ── Money ──────────────────────────────────────────────────────────────────────


def test_money_becomes_integer_piastres():
    assert money_to_piastres("1157.00") == 115_700
    assert money_to_piastres("0.05") == 5
    assert money_to_piastres("1675") == 167_500


def test_money_never_goes_through_a_float():
    """0.07 is not exactly representable in binary; Decimal keeps it exact."""
    assert money_to_piastres("1234.07") == 123_407
    assert money_to_piastres("0.29") == 29


def test_money_rounds_a_third_decimal_rather_than_truncating():
    # Shopify can return more precision on multi-currency shops.
    assert money_to_piastres("10.005") == 1001
    assert money_to_piastres("10.004") == 1000


def test_absent_money_is_zero_not_an_error():
    assert money_to_piastres(None) == 0
    assert money_to_piastres("") == 0


def test_a_float_is_refused():
    with pytest.raises(TypeError):
        money_to_piastres(1157.00)


# ── Normalisation ──────────────────────────────────────────────────────────────


def test_identifiers_are_taken_from_the_node():
    row = normalise_order(_node())
    assert row["shopify_order_id"] == "5123456789"
    assert row["shopify_order_gid"] == "gid://shopify/Order/5123456789"
    assert row["order_number"] == "#29115"


def test_the_business_month_is_derived_in_cairo():
    """Spec section 7. This decides which payroll month the order belongs to."""
    # 21:30 UTC on 31 August is 00:30 on 1 September in Cairo (UTC+3).
    row = normalise_order(_node(createdAt="2026-08-31T21:30:00Z"))
    assert row["business_month"] == "2026-09"

    # 20:00 UTC the same evening is still 31 August in Cairo.
    row = normalise_order(_node(createdAt="2026-08-31T20:00:00Z"))
    assert row["business_month"] == "2026-08"


def test_the_winter_boundary_differs_from_the_summer_one():
    # December is UTC+2, so 21:30 UTC is still the same day.
    row = normalise_order(_node(createdAt="2026-12-31T21:30:00Z"))
    assert row["business_month"] == "2026-12"


def test_discount_codes_are_normalised_to_uppercase():
    row = normalise_order(_node(discountCodes=["hba10", " Nour10 ", "SUMMER"]))
    assert row["discount_codes"] == ["HBA10", "NOUR10", "SUMMER"]


def test_blank_discount_codes_are_dropped():
    row = normalise_order(_node(discountCodes=["HBA10", "", None, "   "]))
    assert row["discount_codes"] == ["HBA10"]


def test_an_order_with_no_codes_is_still_indexed():
    """Most orders have no affiliate code. They are still recorded.

    Without them, "was this code used before it was registered?" could only be
    answered by re-scanning all of Shopify.
    """
    row = normalise_order(_node(discountCodes=[]))
    assert row["discount_codes"] == []
    assert row["shopify_order_id"] == "5123456789"


def test_money_fields_are_piastres():
    row = normalise_order(_node())
    assert row["subtotal_piastres"] == 167_500
    assert row["total_piastres"] == 175_200
    assert row["shipping_piastres"] == 9_500
    assert row["tax_piastres"] == 0


def test_statuses_are_lowercased():
    row = normalise_order(_node())
    assert row["financial_status"] == "partially_paid"
    assert row["fulfillment_status"] == "fulfilled"


def test_a_cancelled_order_records_when():
    row = normalise_order(_node(cancelledAt="2026-08-19T10:00:00Z"))
    assert row["cancelled_at"] is not None


def test_currency_is_captured():
    row = normalise_order(_node())
    assert row["currency"] == "EGP"


def test_a_missing_money_block_does_not_crash():
    """Shopify omits fields the token lacks scope for."""
    row = normalise_order(_node(totalShippingPriceSet=None, currentTotalTaxSet=None))
    assert row["shipping_piastres"] == 0
    assert row["tax_piastres"] == 0


def test_a_node_without_an_id_is_refused():
    with pytest.raises(ValueError):
        normalise_order(_node(legacyResourceId=None, id=None))
```

- [ ] **Step 2: Run it to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_shopify_normalise.py -q
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write the normaliser**

Create `app/services/shopify/normalise.py`:

```python
"""Converting a Shopify order node into order_index values.

Two rules from the specification are enforced here, at the boundary, because
this is the only place raw Shopify data enters the system.

Money becomes integer piastres immediately, via Decimal. Shopify returns
amounts as decimal strings, and parsing one into a float would introduce the
imprecision the whole money design exists to avoid.

The business month is derived in Africa/Cairo, never from the UTC prefix of the
timestamp. An order placed at 21:30 UTC on 31 August belongs to September.
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.core.businesstime import business_month

PIASTRES_PER_POUND = 100


def money_to_piastres(amount: str | None) -> int:
    """Convert a Shopify decimal string to integer piastres.

    Floats are refused outright. Accepting one would mean the value had already
    lost precision before it arrived.
    """
    if amount is None or amount == "":
        return 0
    if isinstance(amount, float):
        raise TypeError("Money must arrive as a string, never a float")
    try:
        value = Decimal(str(amount))
    except InvalidOperation as exc:
        raise ValueError(f"Unparseable money value: {amount!r}") from exc
    return int(
        (value * PIASTRES_PER_POUND).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def _money(block: dict | None) -> tuple[int, str | None]:
    shop_money = ((block or {}).get("shopMoney")) or {}
    return money_to_piastres(shop_money.get("amount")), shop_money.get("currencyCode")


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def normalise_order(node: dict) -> dict:
    """Map a Shopify order node onto order_index columns."""
    gid = str(node.get("id") or "")
    legacy = node.get("legacyResourceId")
    order_id = str(legacy) if legacy else (gid.rsplit("/", 1)[-1] if gid else "")
    if not order_id:
        raise ValueError("Shopify order node has no identifier")

    created_at = _timestamp(node.get("createdAt"))
    if created_at is None:
        raise ValueError(f"Shopify order {order_id} has no createdAt")

    subtotal, currency = _money(node.get("currentSubtotalPriceSet"))
    total, total_currency = _money(node.get("currentTotalPriceSet"))
    shipping, _ = _money(node.get("totalShippingPriceSet"))
    tax, _ = _money(node.get("currentTotalTaxSet"))

    codes = []
    for code in node.get("discountCodes") or []:
        cleaned = str(code or "").strip().upper()
        if cleaned:
            codes.append(cleaned)

    return {
        "shopify_order_id": order_id,
        "shopify_order_gid": gid or None,
        "order_number": str(node.get("name") or ""),
        "placed_at": created_at,
        # Derived in Cairo. This decides the payroll month.
        "business_month": business_month(created_at),
        "updated_at_shopify": _timestamp(node.get("updatedAt")),
        "cancelled_at": _timestamp(node.get("cancelledAt")),
        "financial_status": str(node.get("displayFinancialStatus") or "").lower() or None,
        "fulfillment_status": str(node.get("displayFulfillmentStatus") or "").lower()
        or None,
        "discount_codes": codes,
        "subtotal_piastres": subtotal,
        "total_piastres": total,
        "shipping_piastres": shipping,
        "tax_piastres": tax,
        "currency": currency or total_currency or "EGP",
    }
```

- [ ] **Step 4: Run the normalisation tests**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_shopify_normalise.py -v
```

Expected: all 17 PASS.

- [ ] **Step 5: Write the model**

Create `app/models/orders.py`:

```python
"""The order index.

Every Shopify order gets a row here, whether or not it used an affiliate code.
The row is deliberately small - roughly 150 bytes - because the point is
breadth, not depth.

Keeping unattributed orders is what makes two things possible: registering a
code later and instantly finding the orders that already used it, and alerting
on a code that is live in Shopify but belongs to no affiliate. Discarding them
would leave both questions answerable only by re-scanning all of Shopify.
"""

from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class OrderIndex(Base):
    __tablename__ = "order_index"
    __table_args__ = (
        Index("order_index_business_month_idx", "business_month"),
        # GIN over the code array: "which orders used NOUR10?" is the question
        # this table exists to answer quickly.
        Index(
            "order_index_discount_codes_idx",
            "discount_codes",
            postgresql_using="gin",
        ),
    )

    shopify_order_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    shopify_order_gid: Mapped[str | None] = mapped_column(String(120))
    order_number: Mapped[str] = mapped_column(String(40), nullable=False)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    business_month: Mapped[str] = mapped_column(String(7), nullable=False)
    updated_at_shopify: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    financial_status: Mapped[str | None] = mapped_column(String(40))
    fulfillment_status: Mapped[str | None] = mapped_column(String(40))
    discount_codes: Mapped[list[str]] = mapped_column(
        ARRAY(String(120)), nullable=False, server_default="{}"
    )
    subtotal_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    shipping_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tax_piastres: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, server_default="EGP")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
```

Money columns are `BigInteger`: piastres are 100x the pound figure, and a
32-bit column would overflow at about E£21 million of cumulative value.

- [ ] **Step 6: Write the upsert helper**

Append to `app/services/shopify/normalise.py`:

```python
def upsert_order_index(db, values: dict):
    """Insert or update one order by its Shopify id.

    Orders arrive more than once - a webhook, then a reconciliation sweep, then
    perhaps a re-import - so writing must be idempotent.
    """
    from sqlalchemy.dialects.postgresql import insert

    from app.core.businesstime import utcnow
    from app.models.orders import OrderIndex

    payload = {**values, "last_synced_at": utcnow()}
    statement = insert(OrderIndex).values(**payload)
    statement = statement.on_conflict_do_update(
        index_elements=[OrderIndex.shopify_order_id],
        # first_seen_at is deliberately absent: it records when the platform
        # first saw the order and must not move on a later update.
        set_={
            key: statement.excluded[key]
            for key in payload
            if key != "shopify_order_id" and key != "first_seen_at"
        },
    )
    db.execute(statement)
    return db.get(OrderIndex, values["shopify_order_id"])
```

- [ ] **Step 7: Register the model and migrate**

Replace `app/models/__init__.py`:

```python
"""Model registry. Every model module must be imported here for Alembic autogenerate."""

from app.models import audit, identity, orders  # noqa: F401
```

```bash
./.venv/Scripts/python.exe -m alembic revision --autogenerate -m "order index"
./.venv/Scripts/python.exe -m alembic upgrade head
```

Open the generated migration and confirm the GIN index appears as
`postgresql_using='gin'`. If autogenerate omitted it, add:

```python
op.create_index(
    "order_index_discount_codes_idx",
    "order_index",
    ["discount_codes"],
    postgresql_using="gin",
)
```

- [ ] **Step 8: Write the persistence test**

Create `tests/test_order_index.py`:

```python
"""order_index persistence."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.models.orders import OrderIndex
from app.services.shopify.normalise import normalise_order, upsert_order_index


def _node(order_id="5123456789", **overrides) -> dict:
    node = {
        "id": f"gid://shopify/Order/{order_id}",
        "legacyResourceId": order_id,
        "name": "#29115",
        "createdAt": "2026-08-18T16:36:00Z",
        "updatedAt": "2026-08-18T16:36:00Z",
        "cancelledAt": None,
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "FULFILLED",
        "discountCodes": ["HBA10"],
        "currentSubtotalPriceSet": {"shopMoney": {"amount": "1062.00", "currencyCode": "EGP"}},
        "currentTotalPriceSet": {"shopMoney": {"amount": "1157.00", "currencyCode": "EGP"}},
        "totalShippingPriceSet": {"shopMoney": {"amount": "95.00", "currencyCode": "EGP"}},
        "currentTotalTaxSet": {"shopMoney": {"amount": "0.00", "currencyCode": "EGP"}},
    }
    node.update(overrides)
    return node


def test_an_order_is_stored(db):
    row = upsert_order_index(db, normalise_order(_node()))
    db.flush()
    assert row.shopify_order_id == "5123456789"
    assert row.discount_codes == ["HBA10"]
    assert row.total_piastres == 115_700


def test_writing_the_same_order_twice_updates_rather_than_duplicates(db):
    upsert_order_index(db, normalise_order(_node()))
    db.flush()
    upsert_order_index(
        db, normalise_order(_node(displayFinancialStatus="REFUNDED"))
    )
    db.flush()
    rows = db.scalars(select(OrderIndex)).all()
    assert len(rows) == 1
    assert rows[0].financial_status == "refunded"


def test_first_seen_does_not_move_on_a_later_update(db):
    """It records when the platform first saw the order, not the latest touch."""
    row = upsert_order_index(db, normalise_order(_node()))
    db.flush()
    original = row.first_seen_at

    db.execute(
        text("UPDATE order_index SET first_seen_at = :t WHERE shopify_order_id = :i"),
        {"t": original - timedelta(days=5), "i": "5123456789"},
    )
    db.flush()
    upsert_order_index(db, normalise_order(_node(displayFinancialStatus="REFUNDED")))
    db.flush()
    db.expire_all()

    refreshed = db.get(OrderIndex, "5123456789")
    assert refreshed.first_seen_at < refreshed.last_synced_at


def test_orders_can_be_found_by_discount_code(db):
    """The question this table exists to answer."""
    upsert_order_index(db, normalise_order(_node("1", discountCodes=["NOUR10"])))
    upsert_order_index(db, normalise_order(_node("2", discountCodes=["SALMA10"])))
    upsert_order_index(db, normalise_order(_node("3", discountCodes=["NOUR10", "FREESHIP"])))
    upsert_order_index(db, normalise_order(_node("4", discountCodes=[])))
    db.flush()

    found = db.execute(
        text(
            "SELECT shopify_order_id FROM order_index "
            "WHERE :code = ANY(discount_codes) ORDER BY shopify_order_id"
        ),
        {"code": "NOUR10"},
    ).scalars().all()
    assert found == ["1", "3"]


def test_orders_can_be_counted_by_business_month(db):
    upsert_order_index(db, normalise_order(_node("1", createdAt="2026-08-31T20:00:00Z")))
    upsert_order_index(db, normalise_order(_node("2", createdAt="2026-08-31T21:30:00Z")))
    db.flush()
    months = db.execute(
        text("SELECT business_month FROM order_index ORDER BY shopify_order_id")
    ).scalars().all()
    # The second crosses into September in Cairo.
    assert months == ["2026-08", "2026-09"]


def test_large_totals_do_not_overflow(db):
    """Piastres are 100x the pound figure; a 32-bit column would overflow."""
    big = "20000000.00"  # E£20 million
    upsert_order_index(
        db,
        normalise_order(
            _node("9", currentTotalPriceSet={"shopMoney": {"amount": big, "currencyCode": "EGP"}})
        ),
    )
    db.flush()
    assert db.get(OrderIndex, "9").total_piastres == 2_000_000_000
```

- [ ] **Step 9: Run everything**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add app/models app/services/shopify/normalise.py migrations tests
git commit -m "feat: order index with Cairo business months and piastre money"
```

---

## Task 3: Durable background jobs

**Files:**
- Create: `app/models/integration.py`, `app/services/jobs.py`
- Modify: `app/models/__init__.py`
- Create: two Alembic migrations (tables, then the append-only trigger)
- Test: `tests/test_jobs.py`

**Interfaces:**
- Consumes: `app.core.businesstime.utcnow`
- Produces:
  - `IntegrationEvent`, `BackgroundJob` models
  - `record_event(db, source, external_id, topic, payload) -> tuple[IntegrationEvent, bool]` where the bool is "newly recorded"
  - `enqueue(db, kind, payload, run_after=None) -> BackgroundJob`
  - `lease_job(db, worker_id, lease_seconds=60) -> BackgroundJob | None`
  - `complete_job(db, job)`, `fail_job(db, job, error: str)`
  - `JobStatus` constants: `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`

- [ ] **Step 1: Write the failing test**

Create `tests/test_jobs.py`:

```python
"""Durable background work.

Spec section 10.5. "No queues" means no extra infrastructure, not that
background work may vanish when the service restarts. Postgres is the queue.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.core.businesstime import utcnow
from app.services.jobs import (
    MAX_ATTEMPTS,
    JobStatus,
    complete_job,
    enqueue,
    fail_job,
    lease_job,
    record_event,
)
from datetime import timedelta


# ── Idempotent event receipts ──────────────────────────────────────────────────


def test_an_event_is_recorded_once(db):
    event, created = record_event(db, "shopify", "evt-1", "orders/create", {"id": 1})
    db.flush()
    assert created is True
    assert event.id is not None


def test_a_duplicate_delivery_is_detected_not_reprocessed(db):
    """Shopify retries webhooks. Processing twice would double-count."""
    record_event(db, "shopify", "evt-1", "orders/create", {"id": 1})
    db.flush()
    event, created = record_event(db, "shopify", "evt-1", "orders/create", {"id": 1})
    db.flush()
    assert created is False
    assert event is not None


def test_the_same_id_from_a_different_source_is_a_different_event(db):
    record_event(db, "shopify", "evt-1", "orders/create", {})
    db.flush()
    _, created = record_event(db, "estebdal", "evt-1", "returns/create", {})
    db.flush()
    assert created is True


def test_event_receipts_cannot_be_altered(db):
    """An immutable receipt is the whole point: it proves what arrived."""
    event, _ = record_event(db, "shopify", "evt-9", "orders/create", {})
    db.flush()
    with pytest.raises(DatabaseError):
        db.execute(
            text("UPDATE integration_event SET topic = 'x' WHERE id = :i"),
            {"i": event.id},
        )


def test_event_receipts_cannot_be_deleted(db):
    event, _ = record_event(db, "shopify", "evt-10", "orders/create", {})
    db.flush()
    with pytest.raises(DatabaseError):
        db.execute(text("DELETE FROM integration_event WHERE id = :i"), {"i": event.id})


def test_the_event_table_cannot_be_truncated(db):
    with pytest.raises(DatabaseError):
        db.execute(text("TRUNCATE integration_event"))


# ── Queue mechanics ────────────────────────────────────────────────────────────


def test_an_enqueued_job_can_be_leased(db):
    enqueue(db, "sync_order", {"order_id": "1"})
    db.flush()
    job = lease_job(db, worker_id="worker-a")
    assert job is not None
    assert job.kind == "sync_order"
    assert job.status == JobStatus.RUNNING


def test_a_leased_job_is_not_handed_to_a_second_worker(db):
    enqueue(db, "sync_order", {"order_id": "1"})
    db.flush()
    assert lease_job(db, worker_id="worker-a") is not None
    assert lease_job(db, worker_id="worker-b") is None


def test_an_expired_lease_is_reclaimed(db):
    """A crashed worker must not strand its job forever."""
    enqueue(db, "sync_order", {"order_id": "1"})
    db.flush()
    job = lease_job(db, worker_id="worker-a", lease_seconds=60)
    job.leased_until = utcnow() - timedelta(seconds=1)
    db.flush()

    reclaimed = lease_job(db, worker_id="worker-b")
    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.leased_by == "worker-b"


def test_completing_a_job_removes_it_from_the_queue(db):
    enqueue(db, "sync_order", {"order_id": "1"})
    db.flush()
    job = lease_job(db, worker_id="worker-a")
    complete_job(db, job)
    db.flush()
    assert job.status == JobStatus.SUCCEEDED
    assert lease_job(db, worker_id="worker-b") is None


def test_a_failed_job_is_retried_with_backoff(db):
    enqueue(db, "sync_order", {"order_id": "1"})
    db.flush()
    job = lease_job(db, worker_id="worker-a")
    fail_job(db, job, "Shopify timed out")
    db.flush()

    assert job.status == JobStatus.PENDING
    assert job.attempts == 1
    assert job.last_error == "Shopify timed out"
    # Backoff: not runnable immediately.
    assert lease_job(db, worker_id="worker-b") is None


def test_a_job_gives_up_after_the_attempt_limit_and_stays_visible(db):
    """A silently dropped job is worse than a visible failed one."""
    enqueue(db, "sync_order", {"order_id": "1"})
    db.flush()
    for _ in range(MAX_ATTEMPTS):
        job = db.query(type(  # noqa: SLF001 - direct fetch, bypassing backoff
            enqueue(db, "noop", {})
        )).first()
        break

    job = db.execute(
        text("SELECT id FROM background_job WHERE kind = 'sync_order'")
    ).scalar()
    for attempt in range(MAX_ATTEMPTS):
        db.execute(
            text(
                "UPDATE background_job SET status='pending', run_after=now(), "
                "leased_until=NULL WHERE id=:i"
            ),
            {"i": job},
        )
        db.flush()
        leased = lease_job(db, worker_id="w")
        fail_job(db, leased, f"attempt {attempt}")
        db.flush()

    final = db.execute(
        text("SELECT status FROM background_job WHERE id=:i"), {"i": job}
    ).scalar()
    assert final == JobStatus.FAILED


def test_a_job_scheduled_for_later_is_not_leased_yet(db):
    enqueue(db, "sync_order", {"order_id": "1"}, run_after=utcnow() + timedelta(hours=1))
    db.flush()
    assert lease_job(db, worker_id="worker-a") is None


def test_jobs_are_leased_oldest_first(db):
    enqueue(db, "first", {})
    enqueue(db, "second", {})
    db.flush()
    assert lease_job(db, worker_id="w").kind == "first"


def test_the_payload_survives_a_round_trip(db):
    enqueue(db, "sync_order", {"order_id": "5123456789", "reason": "webhook"})
    db.flush()
    job = lease_job(db, worker_id="w")
    assert job.payload["order_id"] == "5123456789"
    assert job.payload["reason"] == "webhook"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_jobs.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.services.jobs'`

- [ ] **Step 3: Write the models**

Create `app/models/integration.py`:

```python
"""Durability for inbound events and background work.

integration_event is an immutable receipt of everything that arrived. It is
append-only, enforced by the same database trigger as the audit log, because a
receipt you can edit proves nothing.

background_job is the queue. Postgres provides it, so there is no Redis and no
queue service to pay for or operate. A lease with an expiry is what makes it
safe: a worker that crashes mid-job loses its lease, and the job is picked up
again rather than vanishing.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class IntegrationEvent(Base):
    """Proof that an external system sent us something. Append-only."""

    __tablename__ = "integration_event"
    __table_args__ = (
        # The idempotency key. A redelivered webhook collides here and is
        # recognised as a duplicate rather than processed twice.
        UniqueConstraint("source", "external_id", name="integration_event_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    topic: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), index=True
    )


class BackgroundJob(Base):
    __tablename__ = "background_job"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="background_job_status_valid",
        ),
        Index("background_job_runnable_idx", "status", "run_after"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    leased_by: Mapped[str | None] = mapped_column(String(80))
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 4: Write the queue service**

Create `app/services/jobs.py`:

```python
"""The job queue, backed by Postgres.

Leasing uses SELECT ... FOR UPDATE SKIP LOCKED, which is what makes this safe
without a queue server: two workers asking at the same moment get different
rows rather than the same one.

A job that exhausts its attempts is marked failed and left in place. It is not
deleted and not retried forever - a silently dropped job is worse than a
visible failed one, because nobody learns that the work never happened.
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.models.integration import BackgroundJob, IntegrationEvent

MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 30
LEASE_SECONDS = 60
ERROR_LIMIT = 2000


class JobStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def record_event(
    db: Session,
    source: str,
    external_id: str,
    topic: str,
    payload: dict | None = None,
) -> tuple[IntegrationEvent, bool]:
    """Record an inbound event. Returns (event, newly_recorded).

    A repeated delivery returns the original receipt and False, so the caller
    can skip processing rather than doing it twice.
    """
    statement = (
        insert(IntegrationEvent)
        .values(source=source, external_id=external_id, topic=topic, payload=payload)
        .on_conflict_do_nothing(constraint="integration_event_identity")
        .returning(IntegrationEvent.id)
    )
    inserted_id = db.execute(statement).scalar()
    if inserted_id is not None:
        return db.get(IntegrationEvent, inserted_id), True

    existing = db.scalar(
        select(IntegrationEvent).where(
            IntegrationEvent.source == source,
            IntegrationEvent.external_id == external_id,
        )
    )
    return existing, False


def enqueue(
    db: Session,
    kind: str,
    payload: dict[str, Any],
    run_after: datetime | None = None,
) -> BackgroundJob:
    job = BackgroundJob(
        kind=kind,
        payload=payload,
        status=JobStatus.PENDING,
        run_after=run_after or utcnow(),
    )
    db.add(job)
    return job


def lease_job(
    db: Session, worker_id: str, lease_seconds: int = LEASE_SECONDS
) -> BackgroundJob | None:
    """Claim the oldest runnable job, or return None.

    SKIP LOCKED means concurrent workers never contend for the same row. A job
    whose lease has expired is runnable again, which is how a crashed worker's
    work gets picked up instead of stalling.
    """
    now = utcnow()
    row_id = db.execute(
        text(
            """
            SELECT id FROM background_job
            WHERE run_after <= :now
              AND (
                    status = 'pending'
                 OR (status = 'running' AND leased_until IS NOT NULL AND leased_until < :now)
              )
            ORDER BY run_after, id
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        ),
        {"now": now},
    ).scalar()
    if row_id is None:
        return None

    job = db.get(BackgroundJob, row_id)
    job.status = JobStatus.RUNNING
    job.leased_by = worker_id
    job.leased_until = now + timedelta(seconds=lease_seconds)
    db.flush()
    return job


def complete_job(db: Session, job: BackgroundJob) -> None:
    job.status = JobStatus.SUCCEEDED
    job.leased_by = None
    job.leased_until = None
    job.finished_at = utcnow()


def fail_job(db: Session, job: BackgroundJob, error: str) -> None:
    """Record a failure, and either schedule a retry or give up visibly."""
    job.attempts += 1
    job.last_error = (error or "")[:ERROR_LIMIT]
    job.leased_by = None
    job.leased_until = None

    if job.attempts >= MAX_ATTEMPTS:
        job.status = JobStatus.FAILED
        job.finished_at = utcnow()
        return

    job.status = JobStatus.PENDING
    job.run_after = utcnow() + timedelta(
        seconds=BACKOFF_BASE_SECONDS * (2 ** (job.attempts - 1))
    )
```

- [ ] **Step 5: Register the models and migrate**

Replace `app/models/__init__.py`:

```python
"""Model registry. Every model module must be imported here for Alembic autogenerate."""

from app.models import audit, identity, integration, orders  # noqa: F401
```

```bash
./.venv/Scripts/python.exe -m alembic revision --autogenerate -m "integration event and background job"
./.venv/Scripts/python.exe -m alembic revision -m "integration event append only"
./.venv/Scripts/python.exe -m alembic upgrade head
```

In the second migration, reuse the function written in Phase 1:

```python
def upgrade() -> None:
    """Make integration_event append-only.

    reject_mutation() already exists from Phase 1. Both triggers are needed:
    a row-level trigger does not fire on TRUNCATE.
    """
    op.execute(
        """
        CREATE TRIGGER integration_event_no_update_or_delete
        BEFORE UPDATE OR DELETE ON integration_event
        FOR EACH ROW EXECUTE FUNCTION reject_mutation();

        CREATE TRIGGER integration_event_no_truncate
        BEFORE TRUNCATE ON integration_event
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS integration_event_no_truncate ON integration_event;"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS integration_event_no_update_or_delete ON integration_event;"
    )
```

- [ ] **Step 6: Simplify the give-up test**

The give-up test written in Step 1 is convoluted. Replace it with a direct version:

```python
def test_a_job_gives_up_after_the_attempt_limit_and_stays_visible(db):
    """A silently dropped job is worse than a visible failed one."""
    job = enqueue(db, "sync_order", {"order_id": "1"})
    db.flush()

    for attempt in range(MAX_ATTEMPTS):
        job.status = JobStatus.PENDING
        job.run_after = utcnow()
        db.flush()
        leased = lease_job(db, worker_id="w")
        fail_job(db, leased, f"attempt {attempt}")
        db.flush()

    assert job.status == JobStatus.FAILED
    assert job.attempts == MAX_ATTEMPTS
    assert job.finished_at is not None
    # Still present, so the operational view can show it.
    assert db.get(BackgroundJob, job.id) is not None
```

Add `from app.models.integration import BackgroundJob` to the test imports.

- [ ] **Step 7: Run the tests**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_jobs.py -v
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add app/models app/services/jobs.py migrations tests/test_jobs.py
git commit -m "feat: durable job queue and immutable event receipts in Postgres"
```

---

## Task 4: The worker

**Files:**
- Create: `app/worker.py`
- Modify: `app/main.py`, `app/config.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `app.services.jobs`
- Produces:
  - `HANDLERS: dict[str, Callable[[Session, dict], None]]`
  - `register_handler(kind)` decorator
  - `run_one(db, worker_id) -> bool` — process at most one job, returns whether it did
  - `worker_loop()` — async loop started with the app
  - `settings.worker_enabled`, `settings.worker_poll_seconds`

- [ ] **Step 1: Add worker settings**

In `app/config.py`:

```python
    # The worker runs inside the API process. With one replica that is simpler
    # and cheaper than a second service, and the lease mechanism keeps it
    # correct if that ever changes.
    worker_enabled: bool = True
    worker_poll_seconds: float = 2.0
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_worker.py`:

```python
"""The background worker."""

import pytest

from app.core.businesstime import utcnow
from app.models.integration import BackgroundJob
from app.services.jobs import JobStatus, enqueue
from app.worker import HANDLERS, register_handler, run_one


@pytest.fixture(autouse=True)
def _isolated_handlers():
    """Never let a test's handler leak into another test."""
    original = dict(HANDLERS)
    yield
    HANDLERS.clear()
    HANDLERS.update(original)


def test_run_one_reports_when_there_is_nothing_to_do(db):
    assert run_one(db, worker_id="w") is False


def test_a_job_is_handled_and_marked_succeeded(db):
    seen = []

    @register_handler("test_kind")
    def handle(session, payload):
        seen.append(payload["value"])

    job = enqueue(db, "test_kind", {"value": 42})
    db.flush()

    assert run_one(db, worker_id="w") is True
    db.flush()
    assert seen == [42]
    assert job.status == JobStatus.SUCCEEDED


def test_a_handler_that_raises_marks_the_job_for_retry(db):
    @register_handler("boom")
    def handle(session, payload):
        raise RuntimeError("the API was down")

    job = enqueue(db, "boom", {})
    db.flush()

    assert run_one(db, worker_id="w") is True
    db.flush()
    assert job.status == JobStatus.PENDING
    assert job.attempts == 1
    assert "the API was down" in job.last_error


def test_an_unknown_kind_fails_loudly_rather_than_silently(db):
    """A job nobody can handle must be visible, not quietly dropped."""
    job = enqueue(db, "no_such_handler", {})
    db.flush()

    assert run_one(db, worker_id="w") is True
    db.flush()
    assert job.attempts == 1
    assert "no handler" in job.last_error.lower()


def test_a_handler_failure_does_not_lose_the_failure_record(db):
    """The rollback that undoes a handler's writes must not undo the retry state."""
    @register_handler("writes_then_fails")
    def handle(session, payload):
        session.add(BackgroundJob(kind="side_effect", payload={}))
        session.flush()
        raise RuntimeError("failed after writing")

    job = enqueue(db, "writes_then_fails", {})
    db.flush()
    run_one(db, worker_id="w")
    db.flush()

    assert job.attempts == 1
    assert job.last_error is not None


def test_registering_two_handlers_for_one_kind_is_refused(db):
    @register_handler("dup")
    def first(session, payload):
        pass

    with pytest.raises(ValueError):
        @register_handler("dup")
        def second(session, payload):
            pass
```

- [ ] **Step 3: Run it to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_worker.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.worker'`

- [ ] **Step 4: Write the worker**

Create `app/worker.py`:

```python
"""The background worker.

It runs inside the API process. With a single replica that is simpler and
cheaper than operating a second service, and because jobs are leased rather
than assigned, splitting it out later needs no change here.

A handler runs inside the caller's transaction. If it raises, that transaction
is rolled back so no half-finished work is committed - and the failure is then
recorded in a fresh transaction, so the retry state survives the rollback that
discarded the work.
"""

import asyncio
import logging
import os
import socket
from typing import Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.services.jobs import complete_job, fail_job, lease_job

logger = logging.getLogger(__name__)

Handler = Callable[[Session, dict], None]
HANDLERS: dict[str, Handler] = {}


def register_handler(kind: str):
    """Attach a handler to a job kind.

    Refuses a duplicate registration: two handlers for one kind means one of
    them silently never runs, which is the kind of bug that hides for months.
    """

    def decorator(function: Handler) -> Handler:
        if kind in HANDLERS:
            raise ValueError(f"A handler is already registered for {kind!r}")
        HANDLERS[kind] = function
        return function

    return decorator


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def run_one(db: Session, worker_id: str) -> bool:
    """Process at most one job. Returns whether there was one."""
    job = lease_job(db, worker_id)
    if job is None:
        return False

    handler = HANDLERS.get(job.kind)
    if handler is None:
        fail_job(db, job, f"No handler registered for job kind {job.kind!r}")
        db.commit()
        return True

    job_id = job.id
    try:
        handler(db, job.payload or {})
    except Exception as exc:  # noqa: BLE001 - any failure must be recorded
        # Discard whatever the handler wrote, then record the failure
        # separately so the retry state is not rolled back with it.
        db.rollback()
        failed = db.get(type(job), job_id)
        fail_job(db, failed, f"{type(exc).__name__}: {exc}")
        db.commit()
        logger.warning("job %s (%s) failed: %s", job_id, failed.kind, exc)
        return True

    complete_job(db, job)
    db.commit()
    return True


async def worker_loop() -> None:
    """Poll for work until cancelled."""
    worker_id = worker_identity()
    logger.info("background worker %s started", worker_id)
    while True:
        try:
            with SessionLocal() as db:
                did_work = run_one(db, worker_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the loop must outlive any single error
            logger.exception("worker iteration failed")
            did_work = False
        # Sleep only when idle, so a backlog drains at full speed.
        if not did_work:
            await asyncio.sleep(settings.worker_poll_seconds)
```

- [ ] **Step 5: Start the worker with the app**

In `app/main.py`, add above the router includes:

```python
import asyncio
import contextlib
from contextlib import asynccontextmanager

from app.config import settings
from app.worker import worker_loop


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = None
    if settings.worker_enabled:
        task = asyncio.create_task(worker_loop())
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
```

and pass it to the app:

```python
app = FastAPI(
    title="HBA Platform",
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
    lifespan=lifespan,
)
```

- [ ] **Step 6: Disable the worker during tests**

In `tests/conftest.py`, add at the top:

```python
import os

# The worker must not race the tests for jobs. Set before app import.
os.environ.setdefault("WORKER_ENABLED", "false")
```

- [ ] **Step 7: Run the tests**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_worker.py -v
./.venv/Scripts/python.exe -m pytest tests/ -q
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add app/worker.py app/main.py app/config.py tests
git commit -m "feat: background worker running inside the API process"
```

---

## Task 5: Webhook receiver

**Files:**
- Create: `app/services/shopify/webhooks.py`, `app/api/webhooks.py`
- Modify: `app/main.py`
- Test: `tests/test_shopify_webhooks.py`

**Interfaces:**
- Consumes: `app.services.jobs`, `app.config.settings`
- Produces:
  - `verify_shopify_hmac(raw_body: bytes, header_value: str, secret: str) -> bool`
  - `POST /api/webhooks/shopify`
  - Job kind `"shopify_sync_order"`

- [ ] **Step 1: Write the failing test**

Create `tests/test_shopify_webhooks.py`:

```python
"""Shopify webhook receipt.

The endpoint does as little as possible: verify the signature, record an
immutable receipt, enqueue the work, return 200. Everything slow happens in
the worker, because Shopify retries a webhook that does not answer quickly.
"""

import base64
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine
from app.main import app
from app.services.shopify.webhooks import verify_shopify_hmac

SECRET = "test-webhook-secret"


def _sign(body: bytes, secret: str = SECRET) -> str:
    return base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode()


@pytest.fixture()
def client(fresh_database, monkeypatch):
    monkeypatch.setattr("app.config.settings.shopify_webhook_secret", SECRET)
    with TestClient(app) as test_client:
        yield test_client


def _post(client, payload: dict, *, event_id="evt-1", topic="orders/create", secret=SECRET):
    body = json.dumps(payload).encode()
    return client.post(
        "/api/webhooks/shopify",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Shopify-Hmac-Sha256": _sign(body, secret),
            "X-Shopify-Webhook-Id": event_id,
            "X-Shopify-Topic": topic,
        },
    )


# ── Signature ──────────────────────────────────────────────────────────────────


def test_a_correct_signature_verifies():
    body = b'{"id":1}'
    assert verify_shopify_hmac(body, _sign(body), SECRET) is True


def test_a_wrong_signature_is_rejected():
    assert verify_shopify_hmac(b'{"id":1}', _sign(b'{"id":2}'), SECRET) is False


def test_verification_uses_the_raw_body_not_reserialised_json():
    """Re-serialising changes the bytes and breaks the signature.

    Shopify signs exactly what it sent, whitespace included.
    """
    original = b'{"id": 1,  "name":  "spaced"}'
    signature = _sign(original)
    reserialised = json.dumps(json.loads(original)).encode()
    assert verify_shopify_hmac(original, signature, SECRET) is True
    assert verify_shopify_hmac(reserialised, signature, SECRET) is False


def test_a_missing_or_malformed_signature_is_rejected_not_crashed():
    for bad in ["", "not-base64!!", None]:
        assert verify_shopify_hmac(b"{}", bad, SECRET) is False


def test_verification_fails_closed_without_a_secret():
    assert verify_shopify_hmac(b"{}", _sign(b"{}"), "") is False


# ── The endpoint ───────────────────────────────────────────────────────────────


def test_a_signed_webhook_is_accepted(client):
    response = _post(client, {"id": 5123456789})
    assert response.status_code == 200


def test_an_unsigned_webhook_is_rejected(client):
    response = client.post(
        "/api/webhooks/shopify",
        content=b'{"id":1}',
        headers={"X-Shopify-Webhook-Id": "evt-x", "X-Shopify-Topic": "orders/create"},
    )
    assert response.status_code == 401


def test_a_forged_webhook_is_rejected(client):
    response = _post(client, {"id": 1}, secret="the-wrong-secret")
    assert response.status_code == 401


def test_a_rejected_webhook_records_nothing(client):
    _post(client, {"id": 1}, secret="the-wrong-secret")
    with engine.connect() as connection:
        events = connection.execute(
            text("SELECT count(*) FROM integration_event")
        ).scalar()
        jobs = connection.execute(text("SELECT count(*) FROM background_job")).scalar()
    assert events == 0
    assert jobs == 0


def test_an_accepted_webhook_records_a_receipt_and_a_job(client):
    _post(client, {"id": 5123456789})
    with engine.connect() as connection:
        event = connection.execute(
            text("SELECT source, topic, external_id FROM integration_event")
        ).one()
        job = connection.execute(text("SELECT kind, payload FROM background_job")).one()
    assert event == ("shopify", "orders/create", "evt-1")
    assert job[0] == "shopify_sync_order"
    assert job[1]["order_id"] == "5123456789"


def test_a_redelivered_webhook_is_acknowledged_but_not_requeued(client):
    """Shopify retries. Processing twice would double-count an order."""
    _post(client, {"id": 5123456789}, event_id="evt-dup")
    _post(client, {"id": 5123456789}, event_id="evt-dup")

    with engine.connect() as connection:
        events = connection.execute(
            text("SELECT count(*) FROM integration_event")
        ).scalar()
        jobs = connection.execute(text("SELECT count(*) FROM background_job")).scalar()
    assert events == 1
    assert jobs == 1


def test_a_webhook_without_an_id_is_still_processed(client):
    """Absent an id, fall back to a content hash rather than dropping it."""
    body = json.dumps({"id": 42}).encode()
    response = client.post(
        "/api/webhooks/shopify",
        content=body,
        headers={
            "X-Shopify-Hmac-Sha256": _sign(body),
            "X-Shopify-Topic": "orders/updated",
        },
    )
    assert response.status_code == 200
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM integration_event")).scalar() == 1


def test_an_unrecognised_topic_is_recorded_but_not_queued(client):
    """Acknowledge it so Shopify stops retrying; do not invent work for it."""
    response = _post(client, {"id": 1}, event_id="evt-t", topic="app/uninstalled")
    assert response.status_code == 200
    with engine.connect() as connection:
        events = connection.execute(text("SELECT count(*) FROM integration_event")).scalar()
        jobs = connection.execute(text("SELECT count(*) FROM background_job")).scalar()
    assert events == 1
    assert jobs == 0


def test_the_webhook_endpoint_needs_no_session(client):
    """Shopify has no cookie. Its signature is its authentication."""
    assert "hba_session" not in client.cookies
    assert _post(client, {"id": 1}).status_code == 200
```

- [ ] **Step 2: Run it to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_shopify_webhooks.py -q
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write the verifier**

Create `app/services/shopify/webhooks.py`:

```python
"""Shopify webhook signature verification.

Shopify signs the raw request body with the app secret and sends the result
base64-encoded in X-Shopify-Hmac-Sha256. The signature covers the exact bytes
sent, so verification must use the raw body: re-serialising the parsed JSON
changes whitespace and key order and the signature will not match.
"""

import base64
import binascii
import hashlib
import hmac

# Topics worth acting on. Anything else is acknowledged and recorded, but
# generates no work.
ORDER_TOPICS = frozenset(
    {
        "orders/create",
        "orders/updated",
        "orders/cancelled",
        "orders/fulfilled",
        "orders/partially_fulfilled",
        "refunds/create",
    }
)


def verify_shopify_hmac(raw_body: bytes, header_value: str | None, secret: str) -> bool:
    """Constant-time signature check. Fails closed on anything unexpected."""
    if not secret or not header_value:
        return False
    try:
        provided = base64.b64decode(header_value, validate=True)
    except (binascii.Error, ValueError, TypeError):
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    return hmac.compare_digest(provided, expected)
```

- [ ] **Step 4: Write the endpoint**

Create `app/api/webhooks.py`:

```python
"""Inbound webhooks.

The handler does as little as possible: verify, record, enqueue, return 200.
Shopify retries any webhook that does not answer promptly, so slow work here
would turn into duplicate deliveries.
"""

import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.services.jobs import enqueue, record_event
from app.services.shopify.webhooks import ORDER_TOPICS, verify_shopify_hmac

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhooks")


@router.post("/shopify", include_in_schema=False)
async def shopify_webhook(
    request: Request, db: Session = Depends(get_session)
) -> dict:
    raw_body = await request.body()
    signature = request.headers.get("X-Shopify-Hmac-Sha256")

    if not verify_shopify_hmac(raw_body, signature, settings.shopify_webhook_secret):
        # Nothing is recorded for an unverified request: an attacker must not
        # be able to fill the event table.
        logger.warning("rejected a Shopify webhook with an invalid signature")
        raise HTTPException(401, "Invalid signature")

    topic = request.headers.get("X-Shopify-Topic", "")
    # Shopify's own delivery id is the natural idempotency key. If it is
    # missing, hash the body rather than dropping the event.
    external_id = request.headers.get("X-Shopify-Webhook-Id") or hashlib.sha256(
        raw_body
    ).hexdigest()

    try:
        payload = await request.json()
    except ValueError:
        payload = {}

    _event, newly_recorded = record_event(
        db, source="shopify", external_id=external_id, topic=topic, payload=payload
    )
    if not newly_recorded:
        # A redelivery. Acknowledge so Shopify stops retrying, but do not
        # queue the work a second time.
        db.commit()
        return {"status": "duplicate"}

    order_id = str(payload.get("id") or "").strip()
    if topic in ORDER_TOPICS and order_id:
        enqueue(db, "shopify_sync_order", {"order_id": order_id, "reason": topic})

    db.commit()
    return {"status": "accepted"}
```

- [ ] **Step 5: Mount the router**

In `app/main.py`, alongside the other includes:

```python
from app.api import auth, health, webhooks
...
app.include_router(webhooks.router)
```

Add it **before** the SPA catch-all, as with the other routers.

- [ ] **Step 6: Run the tests**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_shopify_webhooks.py -v
```

Expected: all 14 PASS.

- [ ] **Step 7: Commit**

```bash
git add app/services/shopify/webhooks.py app/api/webhooks.py app/main.py tests/test_shopify_webhooks.py
git commit -m "feat: signed, idempotent Shopify webhook receiver"
```

---

## Task 6: The order sync handler

**Files:**
- Create: `app/services/shopify/sync.py`
- Test: `tests/test_shopify_sync.py`

**Interfaces:**
- Consumes: `ShopifyClient`, `normalise_order`, `upsert_order_index`, `register_handler`
- Produces:
  - `build_client() -> ShopifyClient`
  - `sync_one_order(db, order_id) -> OrderIndex | None`
  - handler registered for `"shopify_sync_order"`

- [ ] **Step 1: Write the failing test**

Create `tests/test_shopify_sync.py`:

```python
"""Fetching one order from Shopify and indexing it."""

import httpx
import pytest

from app.models.orders import OrderIndex
from app.services.shopify.client import ShopifyClient, ShopifyError
from app.services.shopify.sync import sync_one_order

ORDER_NODE = {
    "id": "gid://shopify/Order/5123456789",
    "legacyResourceId": "5123456789",
    "name": "#29115",
    "createdAt": "2026-08-18T16:36:00Z",
    "updatedAt": "2026-08-18T16:36:00Z",
    "cancelledAt": None,
    "displayFinancialStatus": "PAID",
    "displayFulfillmentStatus": "FULFILLED",
    "discountCodes": ["HBA10"],
    "currentSubtotalPriceSet": {"shopMoney": {"amount": "1062.00", "currencyCode": "EGP"}},
    "currentTotalPriceSet": {"shopMoney": {"amount": "1157.00", "currencyCode": "EGP"}},
    "totalShippingPriceSet": {"shopMoney": {"amount": "95.00", "currencyCode": "EGP"}},
    "currentTotalTaxSet": {"shopMoney": {"amount": "0.00", "currencyCode": "EGP"}},
}


def _client(node):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"order": node}})

    return ShopifyClient(
        shop_domain="hbawear.myshopify.com",
        access_token="shpat_test",
        api_version="2026-07",
        transport=httpx.MockTransport(handler),
    )


def test_an_order_is_fetched_and_indexed(db):
    row = sync_one_order(db, "5123456789", client=_client(ORDER_NODE))
    db.flush()
    assert row.shopify_order_id == "5123456789"
    assert row.discount_codes == ["HBA10"]
    assert row.total_piastres == 115_700


def test_a_numeric_id_is_turned_into_a_gid():
    """Shopify's GraphQL API addresses orders by global id, not legacy id."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["variables"] = request.read().decode()
        return httpx.Response(200, json={"data": {"order": ORDER_NODE}})

    client = ShopifyClient(
        shop_domain="s.myshopify.com",
        access_token="t",
        api_version="2026-07",
        transport=httpx.MockTransport(handler),
    )
    from app.db import SessionLocal

    with SessionLocal() as session:
        sync_one_order(session, "5123456789", client=client)
        session.rollback()
    assert "gid://shopify/Order/5123456789" in seen["variables"]


def test_an_order_that_no_longer_exists_returns_none(db):
    """A deleted order is not an error; it simply has nothing to index."""
    assert sync_one_order(db, "999", client=_client(None)) is None


def test_syncing_the_same_order_twice_leaves_one_row(db):
    sync_one_order(db, "5123456789", client=_client(ORDER_NODE))
    db.flush()
    sync_one_order(db, "5123456789", client=_client(ORDER_NODE))
    db.flush()
    assert db.query(OrderIndex).count() == 1


def test_a_shopify_failure_propagates_so_the_job_retries(db):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "bad query"}]})

    client = ShopifyClient(
        shop_domain="s.myshopify.com",
        access_token="t",
        api_version="2026-07",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ShopifyError):
        sync_one_order(db, "1", client=client)
```

- [ ] **Step 2: Run it to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_shopify_sync.py -q
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write the sync service**

Create `app/services/shopify/sync.py`:

```python
"""Fetching orders from Shopify and indexing them."""

import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.models.orders import OrderIndex
from app.services.shopify.client import ShopifyClient
from app.services.shopify.normalise import normalise_order, upsert_order_index
from app.services.shopify.queries import SINGLE_ORDER
from app.worker import register_handler

logger = logging.getLogger(__name__)


def build_client() -> ShopifyClient:
    """A client from configuration. Raises if Shopify is not configured."""
    return ShopifyClient(
        shop_domain=settings.shopify_shop_domain,
        access_token=settings.shopify_access_token,
        api_version=settings.shopify_api_version,
        timeout_seconds=settings.shopify_timeout_seconds,
    )


def order_gid(order_id: str) -> str:
    """Shopify's GraphQL API addresses orders by global id."""
    text_id = str(order_id)
    return text_id if text_id.startswith("gid://") else f"gid://shopify/Order/{text_id}"


def sync_one_order(
    db: Session, order_id: str, client: ShopifyClient | None = None
) -> OrderIndex | None:
    """Fetch one order and write it to the index.

    Returns None when Shopify has no such order. That is not an error - an
    order can be deleted between a webhook firing and the job running - and
    treating it as one would retry forever.
    """
    client = client or build_client()
    data = client.execute(SINGLE_ORDER, {"id": order_gid(order_id)})
    node = data.get("order")
    if not node:
        logger.info("Shopify has no order %s; nothing to index", order_id)
        return None
    return upsert_order_index(db, normalise_order(node))


@register_handler("shopify_sync_order")
def _handle_sync_order(db: Session, payload: dict) -> None:
    order_id = str(payload.get("order_id") or "").strip()
    if not order_id:
        raise ValueError("shopify_sync_order requires an order_id")
    sync_one_order(db, order_id)
```

- [ ] **Step 4: Import the module so the handler registers**

In `app/main.py`, add near the other imports:

```python
# Importing registers the job handlers with the worker.
from app.services.shopify import sync as _shopify_sync  # noqa: F401
```

- [ ] **Step 5: Run the tests**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_shopify_sync.py -v
./.venv/Scripts/python.exe -m pytest tests/ -q
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/shopify/sync.py app/main.py tests/test_shopify_sync.py
git commit -m "feat: order sync handler wired to the worker"
```

---

## Task 7: Historical import and reconciliation

**Files:**
- Create: `app/services/shopify/bulk.py`, `app/services/reconcile.py`
- Test: `tests/test_shopify_bulk.py`, `tests/test_reconcile.py`

**Interfaces:**
- Consumes: `ShopifyClient`, `normalise_order`, `upsert_order_index`
- Produces:
  - `start_bulk_import(client, since: str) -> str` returning the operation id
  - `poll_bulk_operation(client) -> dict`
  - `ingest_jsonl(db, lines: Iterable[str]) -> int` returning rows written
  - `reconcile_recent(db, client, since_hours=48) -> int`
  - handlers `"shopify_bulk_import"` and `"shopify_reconcile"`

- [ ] **Step 1: Write the failing bulk test**

Create `tests/test_shopify_bulk.py`:

```python
"""Historical import via Shopify's Bulk Operations API.

Paginating a year of orders would be hundreds of throttled requests. A bulk
operation runs server-side and returns one JSONL file.
"""

import json

import httpx
import pytest

from app.models.orders import OrderIndex
from app.services.shopify.bulk import ingest_jsonl, poll_bulk_operation, start_bulk_import
from app.services.shopify.client import ShopifyClient, ShopifyError


def _client(responses):
    """responses: list of dicts returned in order."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return httpx.Response(200, json=payload)

    return ShopifyClient(
        shop_domain="s.myshopify.com",
        access_token="t",
        api_version="2026-07",
        transport=httpx.MockTransport(handler),
    )


def _order_line(order_id: str, codes=("HBA10",), created="2026-03-04T10:00:00Z") -> str:
    return json.dumps(
        {
            "id": f"gid://shopify/Order/{order_id}",
            "legacyResourceId": order_id,
            "name": f"#{order_id}",
            "createdAt": created,
            "updatedAt": created,
            "cancelledAt": None,
            "displayFinancialStatus": "PAID",
            "displayFulfillmentStatus": "FULFILLED",
            "discountCodes": list(codes),
            "currentSubtotalPriceSet": {"shopMoney": {"amount": "100.00", "currencyCode": "EGP"}},
            "currentTotalPriceSet": {"shopMoney": {"amount": "110.00", "currencyCode": "EGP"}},
            "totalShippingPriceSet": {"shopMoney": {"amount": "10.00", "currencyCode": "EGP"}},
            "currentTotalTaxSet": {"shopMoney": {"amount": "0.00", "currencyCode": "EGP"}},
        }
    )


def test_starting_an_import_returns_the_operation_id():
    client = _client(
        [
            {
                "data": {
                    "bulkOperationRunQuery": {
                        "bulkOperation": {"id": "gid://shopify/BulkOperation/1", "status": "CREATED"},
                        "userErrors": [],
                    }
                }
            }
        ]
    )
    assert start_bulk_import(client, since="2026-01-01") == "gid://shopify/BulkOperation/1"


def test_a_user_error_from_shopify_is_raised():
    client = _client(
        [
            {
                "data": {
                    "bulkOperationRunQuery": {
                        "bulkOperation": None,
                        "userErrors": [{"field": "query", "message": "already running"}],
                    }
                }
            }
        ]
    )
    with pytest.raises(ShopifyError) as caught:
        start_bulk_import(client, since="2026-01-01")
    assert "already running" in str(caught.value)


def test_polling_reports_status_and_url():
    client = _client(
        [
            {
                "data": {
                    "currentBulkOperation": {
                        "id": "gid://shopify/BulkOperation/1",
                        "status": "COMPLETED",
                        "objectCount": "412",
                        "url": "https://storage.example/bulk.jsonl",
                        "errorCode": None,
                    }
                }
            }
        ]
    )
    result = poll_bulk_operation(client)
    assert result["status"] == "COMPLETED"
    assert result["url"].endswith("bulk.jsonl")


def test_ingesting_jsonl_writes_every_order(db):
    lines = [_order_line("1"), _order_line("2"), _order_line("3")]
    assert ingest_jsonl(db, lines) == 3
    db.flush()
    assert db.query(OrderIndex).count() == 3


def test_blank_lines_are_skipped(db):
    assert ingest_jsonl(db, [_order_line("1"), "", "   ", _order_line("2")]) == 2


def test_non_order_lines_are_skipped(db):
    """A bulk file can interleave child objects; only orders belong here."""
    child = json.dumps({"id": "gid://shopify/LineItem/9", "__parentId": "gid://shopify/Order/1"})
    assert ingest_jsonl(db, [_order_line("1"), child]) == 1


def test_a_malformed_line_does_not_abort_the_whole_import(db):
    """One bad row must not discard thousands of good ones."""
    written = ingest_jsonl(db, [_order_line("1"), "{not json", _order_line("2")])
    db.flush()
    assert written == 2
    assert db.query(OrderIndex).count() == 2


def test_re_ingesting_the_same_file_is_safe(db):
    lines = [_order_line("1"), _order_line("2")]
    ingest_jsonl(db, lines)
    db.flush()
    ingest_jsonl(db, lines)
    db.flush()
    assert db.query(OrderIndex).count() == 2


def test_business_months_are_assigned_during_import(db):
    ingest_jsonl(
        db,
        [
            _order_line("1", created="2026-08-31T20:00:00Z"),
            _order_line("2", created="2026-08-31T21:30:00Z"),
        ],
    )
    db.flush()
    months = sorted(row.business_month for row in db.query(OrderIndex).all())
    assert months == ["2026-08", "2026-09"]
```

- [ ] **Step 2: Write the bulk service**

Create `app/services/shopify/bulk.py`:

```python
"""Historical import via Shopify's Bulk Operations API.

Paginating a year of orders would be hundreds of requests against a cost-based
rate limit. A bulk operation runs server-side and produces one JSONL file, which
is both faster and far gentler on the limit.

The file interleaves parent and child objects, so ingestion skips anything that
is not an order. A malformed line is logged and skipped rather than aborting:
one bad row must not discard thousands of good ones.
"""

import json
import logging
from typing import Iterable

import httpx
from sqlalchemy.orm import Session

from app.services.shopify.client import ShopifyClient, ShopifyError
from app.services.shopify.normalise import normalise_order, upsert_order_index
from app.services.shopify.queries import ORDER_FIELDS

logger = logging.getLogger(__name__)

BULK_RUN = """
mutation BulkImport($query: String!) {
  bulkOperationRunQuery(query: $query) {
    bulkOperation { id status }
    userErrors { field message }
  }
}
"""

BULK_STATUS = """
query {
  currentBulkOperation {
    id
    status
    objectCount
    url
    errorCode
  }
}
"""


def _orders_query(since: str) -> str:
    return f"""
    {{
      orders(query: "created_at:>={since}") {{
        edges {{
          node {{
            {ORDER_FIELDS}
          }}
        }}
      }}
    }}
    """


def start_bulk_import(client: ShopifyClient, since: str) -> str:
    """Ask Shopify to start building the export. Returns the operation id."""
    data = client.execute(BULK_RUN, {"query": _orders_query(since)})
    result = data.get("bulkOperationRunQuery") or {}
    errors = result.get("userErrors") or []
    if errors:
        messages = "; ".join(str(item.get("message", "")) for item in errors)
        raise ShopifyError(f"Shopify refused the bulk operation: {messages}")
    operation = result.get("bulkOperation") or {}
    operation_id = operation.get("id")
    if not operation_id:
        raise ShopifyError("Shopify returned no bulk operation")
    return operation_id


def poll_bulk_operation(client: ShopifyClient) -> dict:
    """Current status of the running or most recent bulk operation."""
    data = client.execute(BULK_STATUS, {})
    return data.get("currentBulkOperation") or {}


def download_jsonl(url: str, timeout_seconds: float = 120.0) -> Iterable[str]:
    """Stream the export rather than loading it all into memory."""
    with httpx.stream("GET", url, timeout=timeout_seconds) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            yield line


def ingest_jsonl(db: Session, lines: Iterable[str]) -> int:
    """Write every order line to the index. Returns how many were written."""
    written = 0
    skipped = 0
    for line in lines:
        text_line = (line or "").strip()
        if not text_line:
            continue
        try:
            node = json.loads(text_line)
        except ValueError:
            skipped += 1
            continue
        # The export interleaves child objects; they carry __parentId and are
        # not orders.
        if not isinstance(node, dict) or node.get("__parentId"):
            continue
        if not str(node.get("id", "")).startswith("gid://shopify/Order/"):
            continue
        try:
            upsert_order_index(db, normalise_order(node))
            written += 1
        except (ValueError, TypeError):
            skipped += 1
    if skipped:
        logger.warning("bulk ingest skipped %s unusable lines", skipped)
    return written
```

- [ ] **Step 3: Write the reconciliation test**

Create `tests/test_reconcile.py`:

```python
"""The reconciliation sweep.

Webhooks are not guaranteed. A periodic pass over recently updated orders
catches anything missed or delivered out of order.
"""

import httpx

from app.models.orders import OrderIndex
from app.services.reconcile import reconcile_recent
from app.services.shopify.client import ShopifyClient


def _node(order_id: str) -> dict:
    return {
        "id": f"gid://shopify/Order/{order_id}",
        "legacyResourceId": order_id,
        "name": f"#{order_id}",
        "createdAt": "2026-08-18T16:36:00Z",
        "updatedAt": "2026-08-18T16:36:00Z",
        "cancelledAt": None,
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "FULFILLED",
        "discountCodes": ["HBA10"],
        "currentSubtotalPriceSet": {"shopMoney": {"amount": "100.00", "currencyCode": "EGP"}},
        "currentTotalPriceSet": {"shopMoney": {"amount": "110.00", "currencyCode": "EGP"}},
        "totalShippingPriceSet": {"shopMoney": {"amount": "10.00", "currencyCode": "EGP"}},
        "currentTotalTaxSet": {"shopMoney": {"amount": "0.00", "currencyCode": "EGP"}},
    }


def _paged_client(pages):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        page = pages[min(calls["n"], len(pages) - 1)]
        calls["n"] += 1
        return httpx.Response(200, json={"data": {"orders": page}})

    return ShopifyClient(
        shop_domain="s.myshopify.com",
        access_token="t",
        api_version="2026-07",
        transport=httpx.MockTransport(handler),
    )


def test_recent_orders_are_indexed(db):
    client = _paged_client(
        [{"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [_node("1"), _node("2")]}]
    )
    assert reconcile_recent(db, client) == 2
    db.flush()
    assert db.query(OrderIndex).count() == 2


def test_every_page_is_followed(db):
    client = _paged_client(
        [
            {"pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"}, "nodes": [_node("1")]},
            {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [_node("2")]},
        ]
    )
    assert reconcile_recent(db, client) == 2


def test_an_order_already_present_is_updated_not_duplicated(db):
    client = _paged_client(
        [{"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [_node("1")]}]
    )
    reconcile_recent(db, client)
    db.flush()
    reconcile_recent(db, client)
    db.flush()
    assert db.query(OrderIndex).count() == 1


def test_an_empty_result_is_not_an_error(db):
    client = _paged_client(
        [{"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}]
    )
    assert reconcile_recent(db, client) == 0
```

- [ ] **Step 4: Write the reconciliation service**

Create `app/services/reconcile.py`:

```python
"""Reconciliation sweep.

Webhook delivery is best-effort: Shopify can drop one, deliver two out of
order, or deliver during a deploy when nothing is listening. A periodic pass
over recently updated orders closes that gap, and because indexing is
idempotent, re-reading an order the platform already has costs nothing but a
write.
"""

import logging

from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.services.shopify.client import ShopifyClient
from app.services.shopify.normalise import normalise_order, upsert_order_index
from app.services.shopify.queries import ORDERS_PAGE
from app.worker import register_handler
from datetime import timedelta

logger = logging.getLogger(__name__)

PAGE_SIZE = 50
MAX_PAGES = 200  # a stop, so a pagination bug cannot loop forever


def reconcile_recent(
    db: Session, client: ShopifyClient, since_hours: int = 48
) -> int:
    """Re-index every order updated in the window. Returns how many."""
    since = (utcnow() - timedelta(hours=since_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    query = f"updated_at:>={since}"

    cursor: str | None = None
    seen = 0
    for page in range(MAX_PAGES):
        data = client.execute(
            ORDERS_PAGE, {"first": PAGE_SIZE, "after": cursor, "query": query}
        )
        orders = data.get("orders") or {}
        for node in orders.get("nodes") or []:
            upsert_order_index(db, normalise_order(node))
            seen += 1

        page_info = orders.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            break
    else:
        logger.warning("reconciliation stopped at the %s page limit", MAX_PAGES)

    return seen


@register_handler("shopify_reconcile")
def _handle_reconcile(db: Session, payload: dict) -> None:
    from app.services.shopify.sync import build_client

    hours = int(payload.get("since_hours") or 48)
    count = reconcile_recent(db, build_client(), since_hours=hours)
    logger.info("reconciliation re-indexed %s orders", count)
```

- [ ] **Step 5: Register the bulk import handler**

Append to `app/services/shopify/bulk.py`:

```python
@register_handler("shopify_bulk_import")
def _handle_bulk_import(db: Session, payload: dict) -> None:
    """Run one step of the import, rescheduling itself while Shopify works.

    A bulk export of a year of orders takes minutes. Holding a worker for that
    long would block every other job, so each run either starts the operation,
    checks on it, or ingests the finished file.
    """
    from app.core.businesstime import utcnow
    from app.services.jobs import enqueue
    from app.services.shopify.sync import build_client
    from datetime import timedelta

    client = build_client()
    since = str(payload.get("since") or "2026-01-01")

    if not payload.get("started"):
        start_bulk_import(client, since)
        enqueue(
            db,
            "shopify_bulk_import",
            {"since": since, "started": True},
            run_after=utcnow() + timedelta(seconds=30),
        )
        return

    operation = poll_bulk_operation(client)
    status = str(operation.get("status") or "").upper()

    if status in {"CREATED", "RUNNING"}:
        enqueue(
            db,
            "shopify_bulk_import",
            {"since": since, "started": True},
            run_after=utcnow() + timedelta(seconds=30),
        )
        return

    if status != "COMPLETED":
        raise ShopifyError(
            f"Bulk operation ended as {status or 'UNKNOWN'}: "
            f"{operation.get('errorCode') or 'no error code'}"
        )

    url = operation.get("url")
    if not url:
        # COMPLETED with no url means the query matched nothing.
        logger.info("bulk import completed with no orders to ingest")
        return

    written = ingest_jsonl(db, download_jsonl(url))
    logger.info("bulk import indexed %s orders", written)
```

Add `from app.worker import register_handler` to the imports at the top of the file.

- [ ] **Step 6: Import both modules so their handlers register**

In `app/main.py`:

```python
from app.services import reconcile as _reconcile  # noqa: F401
from app.services.shopify import bulk as _shopify_bulk  # noqa: F401
from app.services.shopify import sync as _shopify_sync  # noqa: F401
```

- [ ] **Step 7: Run the tests**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_shopify_bulk.py tests/test_reconcile.py -v
./.venv/Scripts/python.exe -m pytest tests/ -q
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add app/services tests/test_shopify_bulk.py tests/test_reconcile.py app/main.py
git commit -m "feat: bulk historical import and reconciliation sweep"
```

---

## Task 8: Discount code verification and the operational view

**Files:**
- Create: `app/services/shopify/discounts.py`, `app/api/operations.py`
- Modify: `app/main.py`
- Test: `tests/test_shopify_discounts.py`, `tests/test_operations_api.py`

**Interfaces:**
- Consumes: `ShopifyClient`, `require_permission`
- Produces:
  - `verify_discount_code(client, code) -> dict` with keys `exists`, `code`, `status`, `discount_bp`, `usage_count`, `title`
  - `GET /api/operations/sync` — job and event counts, last sync
  - `GET /api/operations/failed-jobs` — visible failures
  - `GET /api/operations/unregistered-codes` — codes in use, owned by nobody
  - `POST /api/operations/verify-code` — the Phase 3 onboarding gate

- [ ] **Step 1: Write the failing verification test**

Create `tests/test_shopify_discounts.py`:

```python
"""Discount code verification.

Spec section 10.4. This is the gate that stops a mistyped code reaching
production, where it would silently attribute nothing.
"""

import httpx

from app.services.shopify.client import ShopifyClient
from app.services.shopify.discounts import verify_discount_code


def _client(node):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"codeDiscountNodeByCode": node}})

    return ShopifyClient(
        shop_domain="s.myshopify.com",
        access_token="t",
        api_version="2026-07",
        transport=httpx.MockTransport(handler),
    )


PERCENTAGE_NODE = {
    "id": "gid://shopify/DiscountCodeNode/1",
    "codeDiscount": {
        "__typename": "DiscountCodeBasic",
        "title": "NOUR10",
        "status": "ACTIVE",
        "usageLimit": None,
        "asyncUsageCount": 47,
        "customerGets": {"value": {"__typename": "DiscountPercentage", "percentage": 0.1}},
    },
}


def test_an_existing_code_is_reported_with_its_details():
    result = verify_discount_code(_client(PERCENTAGE_NODE), "NOUR10")
    assert result["exists"] is True
    assert result["status"] == "ACTIVE"
    assert result["usage_count"] == 47
    assert result["discount_bp"] == 1000  # 10%


def test_a_missing_code_is_reported_not_raised():
    """A typo is an expected answer, not an exception."""
    result = verify_discount_code(_client(None), "NOUR1O")
    assert result["exists"] is False
    assert result["code"] == "NOUR1O"


def test_the_code_is_normalised_before_lookup():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"data": {"codeDiscountNodeByCode": PERCENTAGE_NODE}})

    client = ShopifyClient(
        shop_domain="s.myshopify.com",
        access_token="t",
        api_version="2026-07",
        transport=httpx.MockTransport(handler),
    )
    verify_discount_code(client, "  nour10  ")
    assert "NOUR10" in seen["body"]


def test_an_expired_code_is_reported_as_existing_but_not_active():
    node = {
        "codeDiscount": {
            "__typename": "DiscountCodeBasic",
            "title": "OLD10",
            "status": "EXPIRED",
            "asyncUsageCount": 3,
            "customerGets": {"value": {"__typename": "DiscountPercentage", "percentage": 0.1}},
        }
    }
    result = verify_discount_code(_client(node), "OLD10")
    assert result["exists"] is True
    assert result["status"] == "EXPIRED"


def test_a_fixed_amount_discount_reports_no_percentage():
    """A fixed-amount code is valid; it simply has no percentage to compare."""
    node = {
        "codeDiscount": {
            "__typename": "DiscountCodeBasic",
            "title": "FLAT50",
            "status": "ACTIVE",
            "asyncUsageCount": 1,
            "customerGets": {
                "value": {
                    "__typename": "DiscountAmount",
                    "amount": {"amount": "50.00", "currencyCode": "EGP"},
                }
            },
        }
    }
    result = verify_discount_code(_client(node), "FLAT50")
    assert result["exists"] is True
    assert result["discount_bp"] is None


def test_verification_never_infers_a_commission_rate():
    """Spec section 10.4: the customer discount and the commission are different.

    A creator may give customers 10% off while earning 5%. The result carries
    the discount only, never anything named like a commission.
    """
    result = verify_discount_code(_client(PERCENTAGE_NODE), "NOUR10")
    assert "commission" not in " ".join(result.keys()).lower()
```

- [ ] **Step 2: Write the verifier**

Create `app/services/shopify/discounts.py`:

```python
"""Discount code verification.

Approving an affiliate is blocked until their code is confirmed to exist in
Shopify. That removes the mistyped-code failure at source: a code that does not
exist attributes nothing, silently, until someone notices the sales are missing.

What is deliberately absent: any inference of a commission rate. The customer
discount and the affiliate's commission are different commercial concepts - a
creator may give customers 10% off while earning 5% - so this returns the
discount and lets the caller compare it against a recorded expectation.
"""

from app.services.shopify.client import ShopifyClient

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


def verify_discount_code(client: ShopifyClient, code: str) -> dict:
    """Look a code up in Shopify.

    A missing code is a normal answer, not an exception: it is the most likely
    result of a typo, and the caller needs to show it rather than crash.
    """
    normalised = str(code or "").strip().upper()
    data = client.execute(CODE_LOOKUP, {"code": normalised})
    node = data.get("codeDiscountNodeByCode")

    if not node:
        return {
            "exists": False,
            "code": normalised,
            "status": None,
            "discount_bp": None,
            "usage_count": None,
            "title": None,
        }

    discount = node.get("codeDiscount") or {}
    value = ((discount.get("customerGets") or {}).get("value")) or {}

    discount_bp = None
    if value.get("__typename") == "DiscountPercentage":
        # Shopify expresses 10% as 0.1. Basis points keep it an integer.
        percentage = value.get("percentage")
        if percentage is not None:
            discount_bp = int(round(float(percentage) * 10_000))

    return {
        "exists": True,
        "code": normalised,
        "status": discount.get("status"),
        "discount_bp": discount_bp,
        "usage_count": discount.get("asyncUsageCount"),
        "title": discount.get("title"),
    }
```

- [ ] **Step 3: Write the operational API test**

Create `tests/test_operations_api.py`:

```python
"""The operational view.

Spec section 10.5: failed jobs are visible in the interface, not buried in
logs. The maintainer should learn about a sync failure from the platform, not
from a confused affiliate.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine
from app.main import app

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "a-long-enough-password",
}


@pytest.fixture()
def client(fresh_database):
    with TestClient(app) as test_client:
        test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        yield test_client


def test_sync_status_requires_authentication(fresh_database):
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/operations/sync").status_code == 401


def test_sync_status_reports_counts(client):
    body = client.get("/api/operations/sync").json()
    assert "jobs" in body
    assert "orders_indexed" in body
    assert body["orders_indexed"] == 0


def test_failed_jobs_are_listed(client):
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO background_job (kind, payload, status, attempts, last_error) "
                "VALUES ('shopify_sync_order', '{}'::jsonb, 'failed', 5, 'Shopify timed out')"
            )
        )
    body = client.get("/api/operations/failed-jobs").json()
    assert len(body["jobs"]) == 1
    assert body["jobs"][0]["last_error"] == "Shopify timed out"


def test_unregistered_codes_are_surfaced(client):
    """A code live in Shopify but owned by nobody means missing attribution."""
    with engine.begin() as connection:
        for order_id, code in [("1", "SARA10"), ("2", "SARA10"), ("3", "HBA10")]:
            connection.execute(
                text(
                    "INSERT INTO order_index (shopify_order_id, order_number, placed_at, "
                    "business_month, discount_codes, subtotal_piastres, total_piastres, "
                    "shipping_piastres, tax_piastres, currency) "
                    "VALUES (:i, :n, now(), '2026-08', ARRAY[:c], 0, 0, 0, 0, 'EGP')"
                ),
                {"i": order_id, "n": f"#{order_id}", "c": code},
            )
    body = client.get("/api/operations/unregistered-codes").json()
    counts = {row["code"]: row["order_count"] for row in body["codes"]}
    assert counts["SARA10"] == 2
    assert counts["HBA10"] == 1


def test_code_verification_requires_permission(client):
    """It reaches Shopify, so it is not open to any authenticated caller."""
    response = client.post(
        "/api/operations/verify-code",
        json={"code": "NOUR10"},
        headers={"X-CSRF-Token": "missing"},
    )
    # Either the CSRF check or the permission check refuses it; both are fine.
    assert response.status_code in (401, 403)
```

- [ ] **Step 4: Write the operational API**

Create `app/api/operations.py`:

```python
"""Operational visibility.

A failed background job that only exists in a log file is invisible. These
endpoints put sync state, failures, and unattributed codes where the
maintainer will actually see them.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.config import settings
from app.core.permissions import Permission
from app.db import get_session
from app.models.identity import UserAccount
from app.services.shopify.client import ShopifyError, ShopifyNotConfigured
from app.services.shopify.discounts import verify_discount_code

router = APIRouter(prefix="/api/operations")


class VerifyCodeBody(BaseModel):
    code: str = Field(min_length=1, max_length=120)


@router.get("/sync")
def sync_status(
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    jobs = dict(
        db.execute(
            text("SELECT status, count(*) FROM background_job GROUP BY status")
        ).all()
    )
    orders = db.execute(text("SELECT count(*) FROM order_index")).scalar()
    last_order = db.execute(text("SELECT max(last_synced_at) FROM order_index")).scalar()
    last_event = db.execute(text("SELECT max(received_at) FROM integration_event")).scalar()

    return {
        "shopify_configured": settings.shopify_configured,
        "orders_indexed": orders or 0,
        "last_order_synced_at": last_order.isoformat() if last_order else None,
        "last_event_received_at": last_event.isoformat() if last_event else None,
        "jobs": {
            "pending": jobs.get("pending", 0),
            "running": jobs.get("running", 0),
            "succeeded": jobs.get("succeeded", 0),
            "failed": jobs.get("failed", 0),
        },
    }


@router.get("/failed-jobs")
def failed_jobs(
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    rows = db.execute(
        text(
            "SELECT id, kind, attempts, last_error, created_at, finished_at "
            "FROM background_job WHERE status = 'failed' "
            "ORDER BY finished_at DESC NULLS LAST LIMIT 100"
        )
    ).mappings().all()
    return {
        "jobs": [
            {
                "id": row["id"],
                "kind": row["kind"],
                "attempts": row["attempts"],
                "last_error": row["last_error"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
            }
            for row in rows
        ]
    }


@router.get("/unregistered-codes")
def unregistered_codes(
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Codes in use on real orders.

    Phase 3 will subtract the codes that belong to an affiliate, leaving only
    the genuinely unregistered ones. Until affiliates exist, this reports every
    code seen, which is already the information needed to spot a live code
    nobody has set up.
    """
    rows = db.execute(
        text(
            "SELECT code, count(*) AS order_count, min(placed_at) AS first_seen, "
            "       max(placed_at) AS last_seen "
            "FROM order_index, unnest(discount_codes) AS code "
            "GROUP BY code ORDER BY order_count DESC LIMIT 200"
        )
    ).mappings().all()
    return {
        "codes": [
            {
                "code": row["code"],
                "order_count": row["order_count"],
                "first_seen": row["first_seen"].isoformat() if row["first_seen"] else None,
                "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
            }
            for row in rows
        ]
    }


@router.post("/verify-code")
def verify_code(
    body: VerifyCodeBody,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_MANAGE)),
) -> dict:
    """Confirm a discount code exists in Shopify. The Phase 3 onboarding gate."""
    from app.services.shopify.sync import build_client

    try:
        return verify_discount_code(build_client(), body.code)
    except ShopifyNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except ShopifyError as exc:
        raise HTTPException(502, f"Could not reach Shopify: {exc}") from exc
```

- [ ] **Step 5: Mount the router**

In `app/main.py`:

```python
from app.api import auth, health, operations, webhooks
...
app.include_router(operations.router)
```

- [ ] **Step 6: Run everything**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add app/services/shopify/discounts.py app/api/operations.py app/main.py tests
git commit -m "feat: discount code verification and operational visibility"
```

---

## Definition of done for Phase 2

- [ ] `pytest` passes in full
- [ ] `alembic upgrade head` builds the schema from empty
- [ ] `integration_event` refuses UPDATE, DELETE and TRUNCATE
- [ ] A forged webhook is rejected **and recorded nowhere**
- [ ] A redelivered webhook is acknowledged without queueing duplicate work
- [ ] A crashed worker's lease expires and its job is picked up again
- [ ] A job that exhausts its retries is **visible**, not deleted
- [ ] An order placed at 21:30 UTC on 31 August is indexed as `2026-09`
- [ ] Money is integer piastres from the moment it leaves Shopify
- [ ] Verification reports a missing code as `exists: false`, not an exception
- [ ] Deployed, `/api/health/ready` still green, `/api/operations/sync` reachable

---

## Self-review

**Spec coverage.** §10.1 scopes → documented in open questions, since they are granted in Shopify's UI rather than in code. §10.2 two-tier storage → Task 2 (`order_index`; `attributed_order` is Phase 3 by design). §10.3 bulk import, webhooks, reconciliation → Tasks 5, 6, 7. §10.4 code verification → Task 8. §10.5 durability → Tasks 3 and 4, with the operational view in Task 8. §7 Cairo months → enforced in Task 2's normaliser and tested at both DST boundaries. §4.7 integer piastres → `money_to_piastres`, which refuses floats outright.

**Deliberately deferred:** `attributed_order` and backfill-on-code-registration (need affiliates, Phase 3); `notification_outbox` (nothing sends messages yet — failures surface in the operational view, which is what §10.5 asks for).

**Type consistency.** `normalise_order` returns exactly the keys `OrderIndex` declares, and `upsert_order_index` passes them straight through. `record_event` returns `(event, newly_recorded)` and is destructured that way in Task 5. `lease_job`/`complete_job`/`fail_job` all take `(db, job)` in that order. `verify_discount_code` returns the same six keys in every branch, including the not-found one, so callers never have to guard for missing fields.

**Placeholder scan:** none. Every step contains the code or command it requires.

---

## Open questions

1. **Which Shopify credentials?** This plan uses a custom-app access token (`SHOPIFY_ACCESS_TOKEN`). The old dashboard also supported a Client ID/Secret exchange for short-lived tokens. Confirm which HBA will use before Task 1 — the client gains a token-refresh path if it is the latter.
2. **Is `read_discounts` granted?** Task 8 fails without it, and the scope is added in Shopify's app configuration, not here.
3. **Historical import start date.** The spec says 1 January 2026. Confirm before running the import.
4. **Webhook registration.** Creating the subscriptions in Shopify is an operational action pointing at the live URL, so it needs explicit approval and is not in any task.
