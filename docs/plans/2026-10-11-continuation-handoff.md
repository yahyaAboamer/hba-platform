# Where the work is — 11 October 2026, evening (the inbox's silent run is on production)

Supersedes this morning's version of this file and `2026-10-07-continuation-handoff.md`;
their open items are carried under *Remaining*.

## The exact position

Re-read the remote before describing it (`git ls-remote --heads origin main production`).

| | |
|---|---|
| **Branch** | `feature/whatsapp-inbox`, cut from `repair/batch-2`. `origin/main` (staging), `origin/production` and the feature branch were all on `6533260` when this was written; a later commit carrying this file may be ahead on the feature branch only. |
| **Production** | Promoted from `3753df6` to `6533260` on 11 October, 18:28 UTC, on the owner's explicit order (fast-forward). It now also has the inbox's phases 0 to 2 (ADR 0059). Railway keeps the previous deployment for rollback. |
| **Migration head** | `c2e5a8b30014` on both. Production ran `b1d4f7a20013` (the customer-service role) and `c2e5a8b30014` (seven inbox tables) at that deploy. |
| **Production config** | `INBOX_CONFIRMATIONS_ENABLED=true` set on the production service, 11 October. `INBOX_SEND_TO_CUSTOMERS` is **not** set anywhere, and must not be until the switch-over. |
| **Staging config** | Neither inbox variable is set: the engine is off there, so staging holds no customer data. |
| **Backend** | whole suite through `run-suite.sh`, 103/103 files, at `6533260`. |
| **Frontend** | `npm test` 41 files / 651 tests and `npm run build`, at `a7b5977`; unchanged since. |

## What shipped today

**Earlier on 11 October:** Operations (ADR 0057) and the security fixes went to
production (`96d3832`, then the five remaining audit items in `24fa25c` and
`3753df6`).

**The customer inbox, phases 0 to 2** (ADR 0059). The plan, with what each phase
built and what is left of it, is
`docs/plans/2026-10-11-whatsapp-inbox-and-order-confirmation.md`. In short:

- The n8n project `order-confirmation-message` is being rebuilt inside the
  platform and will be retired. The owner approved the mockup
  `docs/design/whatsapp-inbox-2026-10-11.html`.
- Phase 1: the `customer_service` role and `inbox.use`, seven tables, the
  WhatsApp client, and the two connections in Settings → Shopify.
- Phase 2: the confirmation engine, **silent**. On production it records what
  it would send for each new order (`order_confirmation`) and sends nothing;
  it has no way to reach WhatsApp.

**n8n is still the thing that messages customers.** Nothing about what a
customer receives has changed.

## Remaining, in order

1. **The seven-day comparison (inbox phase 2).** From 12 October, compare
   production's `order_confirmation` with n8n's `wa_sends`, daily, with
   `python -m app.services.inbox.shadow` (see its docstring). n8n's database
   is read through `railway ssh` into the `Postgres` service of the
   `order-confirmation-message` project, read-only, order ids only. Every
   difference needs a written reason; the plan lists the expected ones.
2. **Inbox phase 3**, the backend: Meta's callbacks, sending, media, the
   conversations API. Builds on the branch; nothing to deploy until it is whole.
3. **From the owner, for the inbox:** October's charges in WhatsApp Manager;
   who owns the Meta business account, app and number; the WhatsApp keys and
   the second Shopify app's credentials, typed into Settings when wanted.
4. **`SETTINGS_ENCRYPTION_KEY` is set on both since 12 October** (owner's
   order; a different key on each, never displayed, kept only in Railway).
   Settings can now save keys on both. It must never be changed or deleted.
   The media buckets `inbox-media-staging` and `inbox-media-production` were
   created the same day; see the inbox plan for the variables.
5. **Owner acceptance of Operations, on production**: Shopify cards against
   Shopify admin; E-stebdal *Needs review* against its list; Bosta B5 against
   *Awaiting your action*, spot-check B1, B2, B6; one Bosta and one E-stebdal
   link (both addresses are assumed); sign in as the operations manager.
6. **Release gates**, open and behind production: reconciliation against a
   restored copy, the `SETTINGS_ENCRYPTION_KEY` cases, and `a6b1c4e20006` on a
   restored copy. **The two inbox migrations are now part of what a rollback
   rehearsal has to cover.** A restored copy of production now contains
   customer phones and first names (`order_confirmation`) and must be handled
   as customer data.
7. **One security point raised and not agreed.** A background review on
   11 October flagged that the reset-email limits are skipped when the
   caller's address is unknown (`app/api/auth.py`). On Railway the address is
   known, so it does not bite today. Proposed: count those against one shared
   bucket. The owner has not decided.
8. **Optional, from the database review:** a partial index for
   `ops_bosta_delivery`; a 500 when two operations-manager invitations are
   accepted in the same instant; no foreign key on
   `ops_integration_key.updated_by`.
9. Carried: the shell at 390 (account row under the tabs); owner acceptance of
   the Models tab; the admin sidebar's sideways scroll at 390; mapping the
   flows with real data, then the admin audit tab by tab (Payments next). The
   `feature/operations-dashboard` worktree can go.

## Decisions not to reopen

- ADR 0057 as written, amended by 0059 only when the inbox's screens exist:
  Operations only reads; Bosta never decides pay; one operations manager; no
  customer details shown in Operations.
- ADR 0059, all owner decisions of 11 October: code inside the platform, not
  n8n; Inbox is its own dashboard with a customer-service role; staff keep
  chatting on the API number and the per-message cost is accepted; old chats
  are imported; the operations manager holds the inbox; Operations gains a
  WhatsApp tab; no automatic reply after Confirm, Edit kept, Cancel reworded.
- The confirmation engine runs on production and not on staging.
- Staging stays: it costs about $5 a month, measured on 11 October.
- A source that fails is a dashboard state, not a failed job.
- A staff member may manage another account only if they hold all of that
  account's access — the same rule as invitations.

## Corrections worth knowing

- **Staging and production both report `APP_ENV=production`.** Nothing may be
  decided from it that should differ between them. The inbox's sending rule
  was first written that way and replaced before it could matter
  (`INBOX_SEND_TO_CUSTOMERS`).
- **Do not invite a customer-service account yet.** The role works on the
  server; its screens are phase 4.
- **n8n's "failed" count means nothing**: all 220 are paid orders it never
  meant to message. Its chat page is opened with one shared key in its address,
  and a Shopify secret sits in plain text in its workflows; that secret is to
  be replaced when n8n is retired.
- `run-suite.sh` keys passes on the HEAD commit: commit first, or use a fresh
  `OUT_DIR`, or earlier passes are trusted for code they did not test.
- `tests/test_reconcile.py` passes on its own, as the runner runs it, and one
  of its tests fails when run in the same process as `tests/test_worker.py`.
- The disposable Postgres container was killed for memory once during a run
  (exit 137). `docker start hba-platform-postgres-1`, then run again.
- Bosta's search wants `stateCodes` as strings; E-stebdal answers a wrong key
  with a 500.
