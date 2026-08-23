"""Shopify Admin GraphQL transport.

Three things make this more than a thin HTTP wrapper.

**Tokens expire.** HBA's app is a Dev Dashboard app, so there is no permanent
Admin API token: one is exchanged from the client credentials and lives for a
day. The client caches it until shortly before expiry, and re-exchanges once on
a 401 — a token can lapse between the cache check and Shopify reading it, and
that should cost one retry rather than a failed job.

**GraphQL reports failure inside a 200.** Checking the status code alone would
treat a failed query as valid empty data, so every response is inspected for an
errors block.

**Shopify rate-limits by query cost, not request count**, returning a THROTTLED
error rather than a 429. That is retryable, while a malformed query or a bad
credential is not, so they are separate exceptions and only the retryable ones
are retried.

Nothing in this module puts a secret into an exception message. Errors here are
logged and surfaced to operators, and Shopify's own error bodies can echo back
request details, so only status codes and our own text are included.
"""

import logging
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ShopifyError(RuntimeError):
    """A Shopify request failed in a way that will not fix itself."""


class ShopifyThrottled(ShopifyError):
    """Rate limited by query cost. Retryable."""


class ShopifyNotConfigured(ShopifyError):
    """Shopify credentials are absent or unusable."""


class ShopifyMissingScope(ShopifyError):
    """The app has not been granted a scope this operation needs."""


#: What Phase 2 needs. read_all_orders matters specifically because Shopify's
#: ordinary read_orders scope only reaches back 60 days, and the historical
#: import starts in January 2026.
REQUIRED_SCOPES = frozenset({"read_orders", "read_all_orders", "read_discounts"})

MAX_ATTEMPTS = 4
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
#: Refresh this long before the token actually expires, so a request in flight
#: never races the expiry.
TOKEN_SAFETY_MARGIN_SECONDS = 300


class ShopifyClient:
    def __init__(
        self,
        shop_domain: str,
        client_id: str = "",
        client_secret: str = "",
        access_token: str = "",
        api_version: str = "2026-07",
        timeout_seconds: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        domain = (
            str(shop_domain or "")
            .strip()
            .removeprefix("https://")
            .removeprefix("http://")
            .rstrip("/")
        )
        if not domain:
            raise ShopifyNotConfigured(
                "Shopify is not configured: set SHOPIFY_SHOP_DOMAIN"
            )
        # Guard the domain shape. A typo here would send client credentials to
        # somebody else's server.
        if "/" in domain or not domain.endswith(".myshopify.com"):
            raise ShopifyNotConfigured(
                "SHOPIFY_SHOP_DOMAIN must look like your-store.myshopify.com"
            )
        if not (client_id and client_secret) and not access_token:
            raise ShopifyNotConfigured(
                "Shopify is not configured: set SHOPIFY_CLIENT_ID and "
                "SHOPIFY_CLIENT_SECRET, or SHOPIFY_ACCESS_TOKEN for an older "
                "admin-created app"
            )

        self.shop_domain = domain
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds
        self.retry_base_seconds = 1.0

        self._client_id = client_id
        self._client_secret = client_secret
        self._static_token = access_token
        self._transport = transport

        self._token: str | None = access_token or None
        self._token_expires_at: float = float("inf") if access_token else 0.0
        self._granted_scopes: set[str] = set()
        self._token_lock = threading.Lock()

    def __repr__(self) -> str:
        # Deliberately omits every credential.
        return f"<ShopifyClient {self.shop_domain} api={self.api_version}>"

    # ── URLs ──────────────────────────────────────────────────────────────────

    @property
    def endpoint(self) -> str:
        return f"https://{self.shop_domain}/admin/api/{self.api_version}/graphql.json"

    @property
    def token_endpoint(self) -> str:
        return f"https://{self.shop_domain}/admin/oauth/access_token"

    # ── Tokens ────────────────────────────────────────────────────────────────

    def _http(self) -> httpx.Client:
        return httpx.Client(transport=self._transport, timeout=self.timeout_seconds)

    def _exchange_token(self) -> str:
        """Swap the client credentials for a short-lived access token."""
        try:
            with self._http() as http:
                response = http.post(
                    self.token_endpoint,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                )
        except httpx.HTTPError as exc:
            raise ShopifyError(
                f"Could not reach the Shopify token endpoint: {type(exc).__name__}"
            ) from None

        if response.status_code >= 400:
            # The body can echo the credentials back; only the status is safe.
            raise ShopifyError(
                f"Shopify token exchange failed with {response.status_code}"
            )

        try:
            payload = response.json()
        except ValueError:
            raise ShopifyError(
                "Shopify token endpoint returned a non-JSON response"
            ) from None

        token = payload.get("access_token")
        if not token:
            raise ShopifyError("Shopify token response contained no access token")

        self._granted_scopes = {
            scope.strip()
            for scope in str(payload.get("scope", "")).split(",")
            if scope.strip()
        }
        expires_in = int(payload.get("expires_in") or 86_399)
        self._token = token
        self._token_expires_at = time.time() + max(
            expires_in - TOKEN_SAFETY_MARGIN_SECONDS, 60
        )

        missing = self.missing_scopes()
        if missing:
            # Not fatal here: a missing scope only matters when something needs
            # it. Logged now so it is visible before an import fails on it.
            logger.warning(
                "Shopify app is missing scopes: %s", ", ".join(sorted(missing))
            )
        return token

    def _access_token(self, force_refresh: bool = False) -> str:
        if self._static_token:
            return self._static_token
        with self._token_lock:
            if (
                not force_refresh
                and self._token
                and self._token_expires_at > time.time()
            ):
                return self._token
            return self._exchange_token()

    # ── Scopes ────────────────────────────────────────────────────────────────

    def granted_scopes(self) -> set[str]:
        """Scopes Shopify reported when issuing the token."""
        return set(self._granted_scopes)

    def missing_scopes(self) -> set[str]:
        """Required scopes the app does not hold.

        Empty when scopes are unknown - a static token carries none - because
        reporting everything as missing would be worse than saying nothing.
        """
        if not self._granted_scopes:
            return set()
        return set(REQUIRED_SCOPES) - self._granted_scopes

    def require_scope(self, scope: str) -> None:
        """Refuse early, naming the scope, rather than failing opaquely later."""
        self._access_token()
        if self._granted_scopes and scope not in self._granted_scopes:
            raise ShopifyMissingScope(
                f"The Shopify app is missing the {scope} scope. Add it in the "
                f"app's configuration and reinstall the app on the store."
            )

    # ── Requests ──────────────────────────────────────────────────────────────

    def _post_graphql(self, document: str, variables: dict, token: str) -> httpx.Response:
        with self._http() as http:
            return http.post(
                self.endpoint,
                json={"query": document, "variables": variables or {}},
                headers={
                    "X-Shopify-Access-Token": token,
                    "Content-Type": "application/json",
                },
            )

    def execute(self, document: str, variables: dict | None = None) -> dict[str, Any]:
        """Run a GraphQL document and return its data block."""
        last_error: ShopifyError | None = None
        reauthenticated = False

        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                time.sleep(self.retry_base_seconds * (2 ** (attempt - 1)))

            token = self._access_token()

            try:
                response = self._post_graphql(document, variables or {}, token)
            except httpx.TimeoutException:
                last_error = ShopifyError("Shopify request timed out")
                continue
            except httpx.HTTPError as exc:
                last_error = ShopifyError(
                    f"Shopify request failed: {type(exc).__name__}"
                )
                continue

            if response.status_code in (401, 403):
                # The token may have lapsed since the cache check. Re-exchange
                # once; a second failure means the credentials are wrong.
                if not reauthenticated and not self._static_token:
                    reauthenticated = True
                    self._access_token(force_refresh=True)
                    continue
                raise ShopifyError(
                    f"Shopify rejected the credentials ({response.status_code})"
                )

            if response.status_code in RETRYABLE_STATUS:
                last_error = ShopifyError(f"Shopify returned {response.status_code}")
                continue
            if response.status_code >= 400:
                raise ShopifyError(f"Shopify returned {response.status_code}")

            try:
                payload = response.json()
            except ValueError:
                raise ShopifyError("Shopify returned a non-JSON response") from None

            errors = payload.get("errors")
            if errors:
                codes = {
                    str((item.get("extensions") or {}).get("code", "")).upper()
                    for item in errors
                    if isinstance(item, dict)
                }
                messages = "; ".join(
                    str(item.get("message", ""))
                    for item in errors
                    if isinstance(item, dict)
                )
                if "THROTTLED" in codes:
                    last_error = ShopifyThrottled(f"Shopify throttled: {messages}")
                    continue
                if "ACCESS_DENIED" in codes:
                    raise ShopifyMissingScope(f"Shopify denied access: {messages}")
                raise ShopifyError(f"Shopify GraphQL error: {messages}")

            return payload.get("data") or {}

        raise last_error or ShopifyError("Shopify request failed")
