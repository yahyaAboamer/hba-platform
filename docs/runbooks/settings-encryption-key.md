# `SETTINGS_ENCRYPTION_KEY` — generating, storing, deploying and recovering it

**Written 25 September 2026, batch J.** Needed before the Shopify connection
edited in Settings (decision b, ADR 0045, migration `c3d51e7a0002`) can be used
on an environment. **Nothing here has been done on staging or production** — no
deployment is authorised. Every behaviour described below was read from the
code and exercised against the disposable test database, not on Railway.

> **The key never goes in Git, a log, a ticket, a chat message or an email.**
> Not a real one, not a "temporary" one. This document contains no key and
> never should.

---

## What it is for, and what it is not

- It encrypts **one value**: the Shopify client secret saved from Settings →
  Shopify → *Connection*, stored as a Fernet token in
  `shopify_connection.client_secret_encrypted`. Nothing else in the platform
  reads the key (`app/services/shopify/connection.py` is its only reader).
- The platform never returns the secret or the key in a response, never logs
  either, and never writes either to the audit trail (ADR 0045; tested in
  `tests/test_shopify_connection.py`).
- It is **not** the session secret, the webhook secret or a database password.
  Losing it loses the saved Shopify secret and nothing else.
- It is read once, when the process starts. Changing it takes effect on the
  next deploy/restart.

## 1. Generate one key per environment

Staging and production get **different keys**. A staging database, a backup or
a rehearsal copy must never be able to decrypt production's secret, and a key
exposed on staging must not expose production.

On a trusted computer, in a terminal nobody is sharing or recording:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

It prints 44 characters of URL-safe base64. Then, immediately:

1. Paste it into the **password manager** entry described in step 2. That is
   the only copy anybody can ever read back (Railway will not show it again
   once sealed).
2. Paste it into Railway (step 3).
3. Clear the terminal (`clear`, and close it). If the shell keeps history,
   remove the line (`history -d <n>`), or run the command with a leading space
   where `HISTCONTROL=ignorespace` is set.

Do not generate it in a browser tool, an online generator, a notebook that
syncs, or a chat with anyone - including an AI assistant.

## 2. Store the escrow copy

One password-manager entry per environment, named for example
**"HBA platform - SETTINGS_ENCRYPTION_KEY - production"**, holding the key and
the date it was created. At least two named people should be able to open it
(the owner and one other) so a single lost account does not lose the key.

**Keep it away from the database backups.** Backups (`ops/backup`, see
`docs/runbooks/restore.md`) contain the *encrypted* secret; the key is what
turns that back into the secret. The key in the same bucket as the backups
would make the encryption decoration.

## 3. Set it on Railway, sealed

For each environment (staging, then production when promotion is authorised),
on the **hba-platform** service → *Variables*:

1. *New Variable* → name `SETTINGS_ENCRYPTION_KEY`, value the key.
2. Open the variable's ⋯ menu → **Seal**. A sealed variable is given to builds
   and deployments but is never shown in the UI again and cannot be read
   through the API or `railway variables` / `railway run` (Railway docs,
   *Using Variables → Sealed variables*). It cannot be unsealed.
3. Review and deploy the staged change.

Sealed-variable caveats that matter here: it is **not copied** when an
environment or service is duplicated, or into PR environments. That is what we
want (each environment gets its own key), but it means a duplicated
environment starts **without** a key - see *Missing* below.

## 4. Deploy order, and how to confirm it worked

The release that carries the connection form also carries migrations
`c3d51e7a0002` (the connection table) and `d4e7a2c90003` (staff
preferences). Both are additive; both are in the release rehearsal
(`CLAUDE.md`, release gates).

1. Set the sealed variable (step 3) **before or with** the deploy.
2. Deploy; the entrypoint applies the migrations.
3. As an admin, open Settings → Shopify and sync. **Expected:** the
   *Connection* card has no red line saying the server cannot protect a saved
   secret, and *Update connection* is available once a domain is entered.
4. Enter the store domain, client ID and client secret from Shopify's Dev
   Dashboard and press *Update connection*. **Expected:** *Connection updated.
   Shopify answered as {shop name}.* A refusal leaves the connection in use
   exactly as it was and says why.
5. Press *Refresh now*. **Expected:** *Refreshing*, then *Connected ·
   last successful refresh {date}* once the sweep finishes.

## What happens when the key is missing or wrong

| Situation | What the platform does | What to do |
|---|---|---|
| **Missing** (variable not set) | Starts normally. Settings shows *This server cannot protect a saved secret yet (SETTINGS_ENCRYPTION_KEY is not set)*; saving is refused and **nothing is written**. A connection saved earlier is **not used** - the platform falls back to the environment's `SHOPIFY_*` variables and says so. If those are unset too, Shopify reads *Not connected*: *Refresh now* is disabled and answers 409, and order sync jobs fail as *not configured* and show in Settings' failed work. Webhook verification is unaffected (a different secret). | Set the key from the password manager (step 3) and redeploy. The saved connection is readable again; nothing needs re-entering. |
| **Malformed** (set, but not a Fernet key - truncated, extra quote, a space) | Exactly as *Missing*, but the message says *SETTINGS_ENCRYPTION_KEY is set but is not a valid key (it must be a Fernet key: 44 characters of URL-safe base64)*. The key itself is never printed. | Re-paste the key from the password manager, redeploy. |
| **Wrong** (a valid key, but not the one the secret was saved with - e.g. another environment's) | The saved secret fails to decrypt (Fernet is authenticated, so it fails rather than producing garbage). Settings says *The saved connection cannot be read with this server's key; the environment's connection is in use until it is saved again*, and the platform uses the environment's `SHOPIFY_*` connection, or none. | Put the right key back and redeploy - or, if the right key is gone, see *Lost*. |
| **Lost** (no copy of the key anywhere) | As *Wrong*. The stored secret cannot be recovered by anyone, by design. No other data depends on the key. | Generate a new key (step 1), store and set it (steps 2-3), redeploy, then re-enter the client ID and secret in Settings (the secret is shown or rotated in Shopify's Dev Dashboard). Saving writes the secret under the new key. |
| **Exposed** (seen in a log, a message, a screenshot) | Nothing visible - which is the danger: with the key and any copy of the database (a backup, a dump), the client secret can be decrypted. | Treat the **client secret** as exposed too. Rotate the client secret in Shopify's Dev Dashboard; generate a new key; set it and redeploy; save the connection with the new secret. The old secret stops working at Shopify, so an old backup plus the old key yields nothing usable. |

**Rotation without an incident** (e.g. a person with access leaves): the same
as *Exposed* minus the Shopify rotation if the secret itself was not at risk -
new key, redeploy, re-enter the secret. There is a moment between the deploy
and the re-save when the saved connection is unreadable and the environment's
connection (or none) is used; do it when no import is running. The platform
holds one key at a time; it does not support reading with an old key while
writing with a new one.

## Backups and restores

- A database backup contains `shopify_connection` with the **encrypted**
  secret, never the plain one.
- Restoring **production's** backup into production: the key on the service is
  the same, so the saved connection works as before.
- Restoring a backup **anywhere else** (a rehearsal, staging, a laptop): leave
  production's key out. The saved connection will read as unreadable and the
  platform falls back to that environment's own `SHOPIFY_*` connection - the
  safe outcome. If the rehearsal needs a working connection, save one there
  with that environment's own key. Do not copy production's key to make an old
  backup "work".
- Losing the key does not make a backup unrestorable; it only means the
  Shopify secret has to be entered again after restoring.

## Rehearsal (before promotion)

Part of the release gate in `CLAUDE.md` (*migration/rollback rehearsal*), on an
authorised restored copy, not on production:

1. Upgrade to head (`b1f0a40c0001`, `c3d51e7a0002`, `d4e7a2c90003`), downgrade
   one step at a time back past `b1f0a40c0001`, upgrade again; the application
   starts at each step it supports.
2. With the key **unset**: Settings refuses to save, says why, changes nothing.
3. With a key **set**: a connection saves, and survives a restart.
4. With a **different** valid key: the saved connection is reported unreadable
   and the environment's connection is used; saving again under the new key
   restores it.
5. Downgrading `c3d51e7a0002` drops the saved connection and the platform uses
   the environment's; note that the saved secret is gone and must be re-entered
   after upgrading again.

Local evidence so far (disposable database only): `c3d51e7a0002` downgraded
and upgraded in batch I; `d4e7a2c90003` upgraded, downgraded (table gone,
accounts intact) and upgraded in batch J; behaviours 2-4 are covered by
`tests/test_shopify_connection.py`.
