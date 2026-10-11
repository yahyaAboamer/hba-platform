> **Superseded by `2026-10-11-continuation-handoff.md`.** Kept for its record of 3–7 October; its *Remaining* items are carried there.

# Where the work is — 7 October 2026 (Operations dashboard, ADR 0057, built and on staging)

Supersedes `2026-09-30-continuation-handoff.md`, whose open items are carried
under *Remaining* below.

## The exact position

Re-read the remote before describing it (`git ls-remote --heads origin main production`).

| | |
|---|---|
| **Branch** | `repair/batch-2`, released to `origin/main` (staging) with this handoff. `feature/operations-dashboard` (worktree `.claude/worktrees/operations-dashboard`) is the same history up to phase 6 and can be removed once this lands. |
| **`origin/production`** | `c91aff0` (ADR 0058) — **none of the Operations work is on production.** |
| **Migration head** | `f6b2d8a41c57`. Staging has run all six Operations migrations; production has none. |
| **Backend** | whole suite through `run-suite.sh` at the final code (`1f279e2`) — the count is in the release commit's message |
| **Frontend** | 641 tests across 40 files; `npm run build` green |

## What shipped: the Operations dashboard (3–7 October)

ADR 0057; plan `.claude/plans/operations-dashboard.plan.md` (each phase records
what was checked and its departures); PRD `.claude/prds/operations-dashboard.prd.md`.

- **Phases 0–1:** the `operations_manager` role — one at a time (partial unique
  index + service checks), sees only Operations, invites nobody; the admin's
  *Affiliates | Operations* switch; mockup `docs/design/operations-dashboard-2026-10-03.html`.
- **Phase 2:** `working_days_since` (Cairo, Friday off); `ops_source_status` and
  the five states (fresh, stale > 10 min, failed, not connected, never);
  `run_poll`; the `/api/order-ops` router guard.
- **Phase 3:** Shopify tab, S1–S7, its own query (`order_ops/shopify.py`).
- **Worker lanes:** Operations' three reads run in their own lane
  (`app.worker.LANES`, `OPERATIONS_READS`), each lane tops up its own schedule,
  operations reads hold a 5-minute lease. Measured on staging: reads stay 5–6
  minutes apart through the hourly 500-job line-item batch.
- **Phase 4:** E-stebdal tab, E1 (four fields kept of a response full of
  customer details).
- **Phase 5:** Bosta mirror (`ops_bosta_delivery`, `ops_bosta_sync`), B1–B6,
  the 7-day pickups, the success rate for any range from 1 January; history
  reads backwards, ten days a read.
- **Phase 6:** the Bosta and E-stebdal keys in Settings → Shopify, encrypted
  with `SETTINGS_ENCRYPTION_KEY` (helpers now `app/core/secrets.py`), tried
  before saving, never shown but for the last four.
- **Phase 7:** whole-feature reviews and their fixes (plan, phase 7); parity
  sweep recorded in `docs/repair/batch-2/visual/CHECKLIST.md` and
  `docs/redesign/parity/SCREEN_MATRIX.md`.
- Also on this branch: the 5 October cleanup (`52ee369`); `NotBuiltYet` came
  back for the phase-1 placeholders and went again with phase 5.

## Remaining, in order

1. **Owner acceptance on staging** (the plan's gates):
   - invite the operations manager (Settings → Team), sign in as them, and as
     admin use the switch;
   - Shopify: each card against the same filter in Shopify admin;
   - E-stebdal: *Needs review* against E-stebdal's list;
   - Bosta: B5 against Bosta's *Awaiting your action*; spot-check B1, B2, B6;
     September's success rate against Bosta's export (history must have
     reached September — the tab says how far back it has read);
   - click one Bosta and one E-stebdal link: both addresses are assumed
     (`https://business.bosta.co/orders/<tracking>`,
     `https://<shop>/admin/apps/e-stebdal`) — supply the right ones if not.
2. **`SETTINGS_ENCRYPTION_KEY` on staging is not set**, so no key (and no
   Shopify connection) can be saved from Settings there; the cards say so.
   Set a Fernet key on the staging service when wanted.
3. **Production** needs a separate, explicit authorisation. Before it: set
   `BOSTA_API_KEY` (read-only) and `ESTEBDAL_API_KEY` (or a
   `SETTINGS_ENCRYPTION_KEY` and save them in Settings); deploy at a quiet
   moment (the role migration takes `lock_timeout = 5s` and fails rather than
   queue sign-ins — retry the deploy if it does). Production polls all three
   sources every 5 minutes once deployed.
4. **Optional, from the database review:** the `state_code` index on
   `ops_bosta_delivery` serves no query (a partial index on
   `unfinished AND deleted_at IS NULL` would); two operations-manager
   invitations accepted in the same instant give one of them a 500 rather than
   the refusal (the index still holds); `ops_integration_key.updated_by` has no
   foreign key.
5. **Shell at 390** (phase 1): the account row sits under the tabs, not in the
   brand row as the mockup draws it.
6. Carried from 30 September: owner acceptance of the Models tab; the admin
   sidebar's sideways scroll at 390; mapping the flows with real data, then
   the admin audit tab by tab (Payments next); the release gates
   (reconciliation against a restored copy, `SETTINGS_ENCRYPTION_KEY` cases,
   and `a6b1c4e20006` on a restored copy, skipped by order).

## Decisions not to reopen

- ADR 0057 as written: Operations only reads; Bosta never decides pay
  (ADR 0023 stands); one operations manager; no customer details stored or
  shown; working days are Cairo, Saturday–Thursday, no holiday list.
- **A source that fails is a dashboard state, not a failed job** — a refused key
  or an outage is recorded and shown; only an unexpected error fails the job.
- **The Bosta mirror reads history backwards** and the rate and pickups say how
  far back they have read rather than show a number that may be short.
- Card copy where the mockup had none, and the departures listed in
  SCREEN_MATRIX's *Operations as built* table.

## Corrections worth knowing

- **Bosta's search wants `stateCodes` as strings** (`["10"]`; `[10]` is a 400);
  its `count` is always 0; a wrong key is a 401, an unknown tracking number a
  400. **E-stebdal answers a wrong key with a 500.**
- **en-GB now writes September as "Sept".** Operations formats dates from
  en-US parts, day first, to keep the design's "14 Sep".
- **The reachability test reads `api.get("…")` literals,** including in
  comments: a hook that takes a path variable hides routes from it, and a path
  written in a comment reads as a call.
- `run-suite.sh` keys passes on the HEAD commit: commit before running it, or
  earlier passes are trusted for code they did not test.
