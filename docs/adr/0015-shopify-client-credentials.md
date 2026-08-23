# 0015. Shopify authenticates by client credentials

**Status:** Accepted
**Date:** 2026-08-23

## Context

Shopify offers two authentication shapes. An older admin-created custom app
issues a permanent Admin API token. An app created in the Dev Dashboard - which
is how Shopify directs new apps - has a client id and secret, and tokens are
exchanged from them and expire after roughly a day.

HBA's app is a Dev Dashboard app, so there is no permanent token to configure.

## Decision

The client exchanges a token against `/admin/oauth/access_token` using
`grant_type=client_credentials`, caches it until five minutes before expiry, and
re-exchanges **once** on a `401` - a token can lapse between the cache check and
Shopify reading it, and that should cost one retry rather than a failed job. A
second `401` raises, because at that point the credentials are genuinely wrong.

A static `SHOPIFY_ACCESS_TOKEN` remains supported for an older app.

**The token response reports the scopes actually granted**, and the client keeps
them. A missing scope becomes a named message rather than an opaque permission
error hours into an import.

No credential ever reaches an exception message, a log line, or the `repr`.
Shopify's own error bodies can echo request details back, so only status codes
and our own text are included.

## Consequences

Every process holds its own token cache, so a restart costs one extra exchange.
Negligible.

The scopes the app needs are `read_orders`, `read_all_orders` and
`read_discounts`. `read_all_orders` matters specifically: plain `read_orders`
reaches back only 60 days, so the January 2026 import would silently return
nothing without it.

**No write scopes are requested, ever.** This platform only reads from Shopify.
With read-only access a leaked token exposes data; with write access someone can
alter orders, discounts and inventory. That is a permanent increase in blast
radius for capability the code will never use.

## Alternatives considered

**A static token from an admin-created app.** Simpler, and not what HBA has.
Kept as a supported path rather than the primary one.
