"""Shopify GraphQL transport and token exchange.

HBA's app is a Dev Dashboard app, so there is no permanent Admin API token.
One is exchanged from the client credentials and expires, which makes token
handling part of the transport rather than configuration.
"""

import httpx
import pytest

from app.services.shopify.client import (
    REQUIRED_SCOPES,
    ShopifyClient,
    ShopifyError,
    ShopifyMissingScope,
    ShopifyNotConfigured,
    ShopifyThrottled,
)

TOKEN_PATH = "/admin/oauth/access_token"
GRAPHQL_PATH = "/admin/api/2026-07/graphql.json"

GRANTED = "read_orders,read_all_orders,read_discounts"


def _routes(graphql, token=None, on_token=None, on_graphql=None):
    """Build a transport that answers the token and GraphQL endpoints."""
    token_payload = token or {
        "access_token": "shpat_exchanged",
        "scope": GRANTED,
        "expires_in": 86399,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == TOKEN_PATH:
            if on_token is not None:
                return on_token(request)
            return httpx.Response(200, json=token_payload)
        if on_graphql is not None:
            return on_graphql(request)
        return graphql(request)

    return httpx.MockTransport(handler)


def _client(graphql=None, **kwargs):
    graphql = graphql or (lambda request: httpx.Response(200, json={"data": {"ok": True}}))
    client = ShopifyClient(
        shop_domain="hbawear.myshopify.com",
        client_id="cid",
        client_secret="csecret",
        api_version="2026-07",
        transport=_routes(graphql, **kwargs),
    )
    client.retry_base_seconds = 0
    return client


# ── Configuration ──────────────────────────────────────────────────────────────


def test_no_credentials_at_all_is_refused():
    with pytest.raises(ShopifyNotConfigured):
        ShopifyClient(shop_domain="s.myshopify.com", api_version="2026-07")


def test_a_missing_shop_domain_is_refused():
    with pytest.raises(ShopifyNotConfigured):
        ShopifyClient(shop_domain="", client_id="a", client_secret="b", api_version="v")


def test_the_shop_domain_must_be_a_myshopify_domain():
    """A wrong domain would send credentials to somebody else's server."""
    with pytest.raises(ShopifyNotConfigured):
        ShopifyClient(
            shop_domain="evil.example.com",
            client_id="a",
            client_secret="b",
            api_version="v",
        )


def test_a_pasted_url_is_reduced_to_the_domain():
    client = ShopifyClient(
        shop_domain="https://hbawear.myshopify.com/",
        client_id="a",
        client_secret="b",
        api_version="2026-07",
    )
    assert client.shop_domain == "hbawear.myshopify.com"


def test_a_static_token_is_accepted_without_client_credentials():
    """An older admin-created app still works."""
    client = ShopifyClient(
        shop_domain="s.myshopify.com", access_token="shpat_static", api_version="2026-07"
    )
    assert client is not None


# ── Token exchange ─────────────────────────────────────────────────────────────


def test_a_token_is_exchanged_from_the_client_credentials():
    seen = {}

    def on_token(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.read().decode()
        seen["url"] = str(request.url)
        return httpx.Response(
            200, json={"access_token": "shpat_x", "scope": GRANTED, "expires_in": 3600}
        )

    _client(on_token=on_token).execute("{ ok }")
    assert seen["url"].endswith(TOKEN_PATH)
    assert "grant_type=client_credentials" in seen["body"]
    assert "client_id=cid" in seen["body"]


def test_the_exchanged_token_is_sent_on_the_graphql_request():
    seen = {}

    def graphql(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("X-Shopify-Access-Token")
        return httpx.Response(200, json={"data": {"ok": True}})

    _client(graphql).execute("{ ok }")
    assert seen["token"] == "shpat_exchanged"


def test_the_token_is_cached_across_calls():
    """Exchanging on every request would waste a round trip and rate limit."""
    exchanges = {"n": 0}

    def on_token(request: httpx.Request) -> httpx.Response:
        exchanges["n"] += 1
        return httpx.Response(
            200, json={"access_token": "shpat_x", "scope": GRANTED, "expires_in": 3600}
        )

    client = _client(on_token=on_token)
    client.execute("{ ok }")
    client.execute("{ ok }")
    client.execute("{ ok }")
    assert exchanges["n"] == 1


def test_an_expired_cached_token_is_exchanged_again():
    exchanges = {"n": 0}

    def on_token(request: httpx.Request) -> httpx.Response:
        exchanges["n"] += 1
        return httpx.Response(
            200, json={"access_token": "shpat_x", "scope": GRANTED, "expires_in": 3600}
        )

    client = _client(on_token=on_token)
    client.execute("{ ok }")
    client._token_expires_at = 0  # pretend it aged out
    client.execute("{ ok }")
    assert exchanges["n"] == 2


def test_a_401_triggers_one_re_exchange_then_succeeds():
    """A token can expire between the cache check and Shopify reading it."""
    exchanges = {"n": 0}
    calls = {"n": 0}

    def on_token(request: httpx.Request) -> httpx.Response:
        exchanges["n"] += 1
        return httpx.Response(
            200, json={"access_token": f"shpat_{exchanges['n']}", "scope": GRANTED, "expires_in": 3600}
        )

    def graphql(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(401, text="Invalid API key or access token")
        return httpx.Response(200, json={"data": {"ok": True}})

    client = _client(graphql, on_token=on_token)
    assert client.execute("{ ok }") == {"ok": True}
    assert exchanges["n"] == 2


def test_a_persistent_401_gives_up_rather_than_looping():
    def graphql(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Invalid API key or access token")

    with pytest.raises(ShopifyError):
        _client(graphql).execute("{ ok }")


def test_a_token_endpoint_failure_is_reported_clearly():
    def on_token(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="invalid_client")

    with pytest.raises(ShopifyError) as caught:
        _client(on_token=on_token).execute("{ ok }")
    assert "token" in str(caught.value).lower()


def test_a_token_response_without_a_token_is_an_error():
    def on_token(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"scope": GRANTED})

    with pytest.raises(ShopifyError):
        _client(on_token=on_token).execute("{ ok }")


# ── Scopes ─────────────────────────────────────────────────────────────────────


def test_granted_scopes_are_reported():
    client = _client()
    client.execute("{ ok }")
    assert "read_orders" in client.granted_scopes()
    assert "read_discounts" in client.granted_scopes()


def test_a_missing_scope_is_named_rather_than_left_to_fail_later():
    """An opaque permission error mid-import is far worse than this."""
    def on_token(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": "t", "scope": "read_orders", "expires_in": 3600},
        )

    client = _client(on_token=on_token)
    client.execute("{ ok }")
    missing = client.missing_scopes()
    assert "read_discounts" in missing
    assert "read_all_orders" in missing


def test_require_scope_raises_with_the_scope_named():
    def on_token(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": "t", "scope": "read_orders", "expires_in": 3600}
        )

    client = _client(on_token=on_token)
    with pytest.raises(ShopifyMissingScope) as caught:
        client.require_scope("read_discounts")
    assert "read_discounts" in str(caught.value)


def test_the_required_scopes_are_the_ones_this_phase_needs():
    assert REQUIRED_SCOPES == frozenset(
        {"read_orders", "read_all_orders", "read_discounts"}
    )


# ── GraphQL semantics ──────────────────────────────────────────────────────────


def test_a_successful_query_returns_the_data_block():
    def graphql(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"shop": {"name": "HBA"}}})

    assert _client(graphql).execute("{ shop { name } }") == {"shop": {"name": "HBA"}}


def test_the_api_version_is_pinned_into_the_path():
    seen = {}

    def graphql(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"data": {}})

    _client(graphql).execute("{ ok }")
    assert seen["url"] == f"https://hbawear.myshopify.com{GRAPHQL_PATH}"


def test_graphql_errors_are_raised_not_returned():
    """A 200 with an errors block is still a failure.

    GraphQL reports errors inside a successful HTTP response, so checking the
    status alone would treat a failed query as valid empty data.
    """
    def graphql(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "Field 'nope' doesn't exist"}]})

    with pytest.raises(ShopifyError) as caught:
        _client(graphql).execute("{ nope }")
    assert "doesn't exist" in str(caught.value)


def test_throttling_raises_a_distinct_retryable_error():
    """Throttling is retryable; a malformed query is not."""
    def graphql(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]},
        )

    with pytest.raises(ShopifyThrottled):
        _client(graphql).execute("{ ok }")


def test_throttling_is_retried_and_then_succeeds():
    calls = {"n": 0}

    def graphql(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(
                200,
                json={"errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]},
            )
        return httpx.Response(200, json={"data": {"ok": True}})

    assert _client(graphql).execute("{ ok }") == {"ok": True}
    assert calls["n"] == 3


def test_a_server_error_is_retried():
    calls = {"n": 0}

    def graphql(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="upstream boom")
        return httpx.Response(200, json={"data": {"ok": True}})

    assert _client(graphql).execute("{ ok }") == {"ok": True}


def test_a_query_error_is_not_retried():
    """A malformed query will not fix itself; retrying burns the rate limit."""
    calls = {"n": 0}

    def graphql(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"errors": [{"message": "bad field"}]})

    with pytest.raises(ShopifyError):
        _client(graphql).execute("{ ok }")
    assert calls["n"] == 1


def test_a_non_json_response_fails_clearly():
    def graphql(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    with pytest.raises(ShopifyError):
        _client(graphql).execute("{ ok }")


def test_a_timeout_is_retried_then_reported():
    def graphql(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(ShopifyError) as caught:
        _client(graphql).execute("{ ok }")
    assert "timed out" in str(caught.value).lower()


# ── Secret hygiene ─────────────────────────────────────────────────────────────


def test_no_secret_ever_appears_in_an_error_message():
    """Errors are logged and surfaced; a secret in one would leak it."""
    def graphql(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom csecret shpat_exchanged")

    with pytest.raises(ShopifyError) as caught:
        _client(graphql).execute("{ ok }")
    message = str(caught.value)
    assert "csecret" not in message
    assert "shpat_exchanged" not in message


def test_a_token_endpoint_error_body_is_not_echoed():
    def on_token(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="client_secret csecret is wrong")

    with pytest.raises(ShopifyError) as caught:
        _client(on_token=on_token).execute("{ ok }")
    assert "csecret" not in str(caught.value)


def test_the_repr_does_not_expose_credentials():
    client = _client()
    text = f"{client!r}"
    assert "csecret" not in text
    assert "cid" not in text
