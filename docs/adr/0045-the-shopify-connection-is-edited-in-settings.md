# 0045 — The Shopify connection is edited in Settings

**Status:** accepted
**Date:** 2026-09-25
**Amends:** [0015](0015-shopify-client-credentials.md) (where the credentials live)
**Related:** `docs/redesign/designs/Admin Dashboard.dc.html` (`setShopify`,
`syncCreds`, *Update connection*); `app/services/shopify/connection.py`;
`tests/test_shopify_connection.py`

## The situation

0015 kept the Shopify credentials in the server's environment, so changing the
connection was a deploy, and Settings showed a read-only card saying so. The
approved export draws the connection as a form with *Update connection*. The
owner's decision b, 25 September:

> Implement the approved editable connection form in Settings. Only
> authorised staff can change it. Protect saved credentials and never expose
> them in responses, logs or audit text. A failed connection update must not
> destroy the working connection. This does not authorise editing Shopify
> orders or products.

The export's fields are *Store domain* and *Admin API key*. HBA's app is a Dev
Dashboard app with no permanent Admin API key (0015), so the owner chose, the
same day, *Store domain*, *Client ID* and *Client secret*.

## Decision

- A connection saved from Settings (`shopify_connection`, one row) is the one
  every client uses (`build_client` → `connection.effective`). With nothing
  saved - or a saved one this server cannot decrypt - the environment's
  connection is used, as before.
- **Only `settings.manage`** (the admin role) reads or changes it.
- **The client secret is encrypted at rest** with Fernet, keyed by the
  environment's `SETTINGS_ENCRYPTION_KEY`; without that key the form refuses
  to save rather than store a secret it cannot protect. Neither the secret
  nor the full client ID is ever returned - the page gets the domain, the
  shop's name, the client ID's last four characters and *whether* a secret is
  saved - and neither appears in a log line, an exception message or the
  audit trail, which records the domain and *that* the credentials changed.
- **Try, then save.** New credentials are sent to Shopify (`{ shop { name } }`)
  first; nothing is written unless Shopify answers and grants every scope the
  platform needs (`REQUIRED_SCOPES`). A refusal leaves the connection in use
  exactly as it was. A field left blank keeps the saved value.
- Nothing changes about what the connection may do: read scopes only (0015);
  no order or product in Shopify is ever edited.

## What this costs

- **A secret now lives in the database**, encrypted. Whoever holds both the
  database and `SETTINGS_ENCRYPTION_KEY` can read it; the key must be set on
  each environment, kept out of the database, and treated like the secret.
  Rotating the key makes a saved connection unreadable: the platform falls
  back to the environment's and Settings says so, until it is saved again.
- A new table and migration (`c3d51e7a0002`): the release gate's
  migration/rollback rehearsal covers it as well as `b1f0a40c0001`.
- One more dependency, `cryptography`.

## What stays

0015's client-credentials exchange, token caching, the single retry on `401`,
the read-only scopes, and the rule that no credential reaches a message, a log
or a `repr`. The webhook secret stays in the environment.
