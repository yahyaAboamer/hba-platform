# Plan: Operations Dashboard

**Source PRD**: `.claude/prds/operations-dashboard.prd.md`
**Selected Milestone**: Milestones 2–5. The owner asked for the whole build in one plan. Each milestone is its own phase, ending at a review gate.
**Complexity**: Large

**Branch**: `feature/operations-dashboard`, cut from `main` at `c91aff0` (ADR 0058), as the remote stood on 5 Oct 2026.
- It lives in its own worktree, `.claude/worktrees/operations-dashboard` (owner, 5 Oct), so the shared folder can stay on `repair/batch-2` for other sessions.
- `frontend/node_modules` there is a junction to the shared folder's. Python uses the shared `.venv` by its full path.
- Merging needs the owner's explicit say-so; so does deploying.

## Summary

This adds an operations-manager role and a separate Operations dashboard with three tabs (Shopify, Bosta, E-stebdal), on the same platform and sign-in.

- **How the numbers are fetched:** each source is read every 5 minutes by its own background job into local tables that hold no customer details. The dashboard reads only those tables, so every number is under 10 minutes old whether or not webhooks arrive.
- **Separation from money:** nothing touches the order-sync or commission code. The Shopify tab uses its own query and shares only the Shopify client.

The plan has seven phases:

| # | Phase | PRD milestone |
|---|---|---|
| 0 | Decision record and mockup (owner's approval gate) | — |
| 1 | Role and access | 2 |
| 2 | Shared operations foundation | — |
| 3 | Shopify tab | 3 |
| 4 | E-stebdal tab | 4 |
| 5 | Bosta tab | 5 |
| 6 | Keys in Settings | — |
| 7 | Verification, review and handoff | — |

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Roles | `app/core/permissions.py:41-86` | `ROLES` dict of frozensets. `admin` = `ALL_PERMISSIONS`, so it picks up new permissions automatically. `VALID_ROLES = frozenset(ROLES)`. |
| Granting | `app/core/permissions.py:98-112` | `can_grant`: the target's permissions must be a subset of the actor's. |
| Route guard | `app/api/deps.py:69-84` | `Depends(require_permission(Permission.X))` → 403 "Permission required: …". |
| CHECK-constraint migration | `migrations/versions/a71f4c9be830_a_target_from_before_the_platform.py:68-79` | `op.drop_constraint(..., type_="check")`, then `op.create_check_constraint(...)`; `downgrade` reverses it. Current head is `e1a5c3b70010`. |
| Errors | `app/api/staff.py:317-331` | Services raise `ValueError` with plain words; the API maps it to 422. |
| Recurring jobs | `app/services/jobs.py:36` (`JobKind`), `app/services/schedule.py:41-55` (`SCHEDULE`, gap after finishing), `app/worker.py:49` (`register_handler`), `app/services/jobs.py:97` (`PermanentFailure`) | The handler module is imported in `app/main.py:41-46` purely so its handlers register. |
| Long work in slices | `app/services/recipients.py:529` (`_handle_scan_recipients`) | Each run does one slice, commits it, and re-queues itself with a cursor (the job lease is 60 s). |
| Outbound HTTP | `app/services/shopify/client.py:73-139` | httpx client that takes a `transport=`, so tests can swap in `httpx.MockTransport`; bounded retries. |
| Shopify client | `app/services/shopify/sync.py:34` | `build_client()` uses the saved connection, or else the environment. |
| Encrypted credentials | `app/models/integration.py:132-156`, `app/services/shopify/connection.py:57-261`, `app/api/operations.py:1237-1275`, `frontend/src/components/ShopifyConnection.tsx` | Fernet keyed by `SETTINGS_ENCRYPTION_KEY`. `describe`/`check`/`save`: credentials are checked against the provider before saving, the secret is never returned, and audit entries carry no secret. |
| Read-only order list | `app/services/stale.py:86` (`admin_url`), `app/api/operations.py:619`, `frontend/src/screens/DataPanel.tsx:646-745` | Count, then a list of order numbers linking to Shopify admin. |
| Business time | `app/core/businesstime.py:23,45` | `BUSINESS_TIMEZONE = Africa/Cairo`, `business_date()`. |
| Logging | `app/services/schedule.py:37,89` | `logger = logging.getLogger(__name__)`; `logger.info` with no secrets or customer details. |
| Backend tests | `tests/test_operations_api.py:29-43` | The `client` fixture bootstraps an admin; `_demote_to(role)` tests refusals. Real Postgres throughout. |
| Client tests | `tests/test_shopify_client.py:26-56` | `httpx.MockTransport(handler)` with `retry_base_seconds = 0`. |
| Reachability | `tests/test_reachability.py:105-133` | API modules are listed by hand in `_served()`; every route must be called by the frontend. |
| Frontend tests | `frontend/src/screens/__tests__/StaleFulfilments.test.tsx:7-28` | `vi.stubGlobal("fetch")`, a `reply()` helper, and checks for data, empty and failure states. |
| Staff shell | `frontend/src/components/Layout.tsx:14-28` | Static `SECTIONS`. Theme comes from `/api/staff/me/preferences`. |
| Session split | `frontend/src/App.tsx:111` | The split is on what the session is (role), not on what it may do. |

## Files to Change

| File | Action | Why |
|---|---|---|
| `docs/adr/0057-operations-dashboard-a-separate-read-only-role.md`, `docs/adr/README.md` | CREATE / UPDATE | The decisions first, before any code |
| `docs/RULES.md` | UPDATE | Operations as a third half; access and read-only rules |
| `docs/design/operations-dashboard-2026-10-*.html` + PNGs | CREATE | Owner-approved mockup; no approved export exists for this screen |
| `docs/redesign/parity/SCREEN_MATRIX.md` | UPDATE | A8 row and divergence entry citing the mockup and ADR |
| `app/core/permissions.py` | UPDATE | `ORDER_OPS_VIEW`; `operations_manager` role |
| `migrations/versions/<new>_operations_manager_role.py` | CREATE | Role CHECK constraints; one-live-holder partial unique index |
| `app/services/staff.py`, `app/services/invitations.py` | UPDATE | Only one operations manager at a time |
| `app/services/notifications.py`, `app/services/audit_words.py` | UPDATE | Invitation email and audit wording for the role |
| `app/api/deps.py`, `app/api/staff.py` | UPDATE | Theme reachable by any staff role |
| `app/core/businesstime.py` | UPDATE | `working_days_since` (Cairo, Friday off) |
| `app/models/order_ops.py` + `migrations/versions/<new>_order_ops_tables.py` | CREATE | `ops_source_status`, `ops_shopify_order`, `ops_estebdal_return`, `bosta_delivery`, `integration_secret` |
| `app/services/order_ops/` (`freshness.py`, `shopify.py`, `estebdal.py`, `bosta.py`, `cards.py`, `connections.py`) | CREATE | Clients, polls, card rules and keys |
| `app/services/jobs.py`, `app/services/schedule.py`, `app/main.py` | UPDATE | Three poll job kinds every 5 min; handler imports; router |
| `app/api/order_ops.py` | CREATE | `/api/order-ops/*`, all behind `order_ops.view` except connections (`settings.manage`) |
| `frontend/src/App.tsx` | UPDATE | Landing for operations managers; `/operations/*` for admin |
| `frontend/src/components/OperationsLayout.tsx` (+ `.css`) | CREATE | The operations shell; calls no affiliate endpoints |
| `frontend/src/screens/OperationsDashboard.tsx` (+ `.css`) | CREATE | Three tabs, cards, lists, freshness and failure states |
| `frontend/src/components/Layout.tsx` | UPDATE | Admin-only switch to Operations (placement per mockup) |
| `frontend/src/screens/Settings.tsx`, `frontend/src/components/IntegrationKey.tsx` | UPDATE / CREATE | Role label, access table row, Bosta and E-stebdal key cards |
| `tests/test_permissions.py`, `tests/test_reachability.py`, `tests/test_staff_api.py`, `frontend/src/screens/__tests__/SettingsTeam.test.tsx` | UPDATE | Five roles; new API module; fixtures |
| `tests/test_order_ops_*.py`, `frontend/src/screens/__tests__/OperationsDashboard.test.tsx`, `frontend/src/__tests__/OperationsRouting.test.tsx` | CREATE | New behaviour |

## Tasks

### Phase 0 — Decisions and picture (gate: owner approves the mockup before any frontend code)

#### Task 0.1: ADR 0057 and RULES.md
- **Action**: Write `docs/adr/0057-…` from `docs/adr/template.md`, recording:
  - A separate dashboard on the same platform.
  - The `operations_manager` role: exactly one at a time, cannot invite, sees no model or commission data.
  - Operations only reads Shopify, Bosta and E-stebdal.
  - Bosta never feeds pay; ADR 0023 stands and is not reopened.
  - Freshness of 10 minutes or better, by polling.
  - The B4 definition.

  Then add Operations to RULES.md's "The two halves" table and access bullets, and add the ADR to the index.
- **Mirror**: ADR 0056 and its RULES.md bullet.
- **Validate**: The owner reads them; nothing contradicts ADR 0015 (Shopify read-only) or 0023.

#### Task 0.2: Mockup
- **Action**: Use UI/UX Pro Max, held to the existing tokens and components:
  - Overview cards: `.overview__hero-value`
  - `.panel`, `.table`, `.chip` tabs
  - `.notice--refused`

  Draw, at 1280 and 390, in light and dark:
  - the operations manager's shell
  - the Shopify, Bosta and E-stebdal tabs
  - a card opened to its list
  - the "last updated" line, plus stale and failed states
  - the success-rate range picker (today, a chosen day, last 7 days, last 30 days, custom)
  - the 7-day pickups
  - the admin's switch between dashboards
  - Settings: the role in Team, and the Bosta and E-stebdal key cards

  **Recommendation:** the admin's switch sits in the sidebar header, so the approved six tabs stay six.
- **Mirror**: `docs/design/admin-settings-tab-audit-2026-09-30.html` and its PNGs.
- **Validate**: Owner approval recorded in SCREEN_MATRIX (A8 row plus a divergence entry).

### Phase 1 — Operations-manager access (PRD milestone 2)

#### Task 1.1: Permission and role
- **Action**: Add `Permission.ORDER_OPS_VIEW = "order_ops.view"` and `ROLES["operations_manager"] = frozenset({ORDER_OPS_VIEW})`, with a comment giving the reason. The role has no `invitations.send`, so it cannot invite anyone.
- **Mirror**: The comments on the `content_manager` entry.
- **Validate**: `tests/test_permissions.py`:
  - five roles
  - the role's exact permission set
  - `can_grant`: admin→operations_manager true; affiliate_manager and content_manager→operations_manager false

#### Task 1.2: Migration — role constraints and one live holder
- **Action**: New revision on `e1a5c3b70010`:
  - Recreate `role_assignment_role_valid` and `invitation_role_valid` with the new role list.
  - Add the partial unique index `role_assignment_one_operations_manager` on `role_assignment(role) WHERE role = 'operations_manager' AND revoked_at IS NULL`.
  - `downgrade` reverses both.
- **Mirror**: `a71f4c9be830`, lines 68-79.
- **Validate**:
  - `tests/test_identity_models.py` (already loops over every role).
  - A new test showing a second live assignment is refused by the database.
  - On a disposable `hba_probe` DB: upgrade, downgrade, upgrade.

#### Task 1.3: Only one operations manager
- **Action**: Add `SINGLE_HOLDER_ROLES = {"operations_manager"}` to `app/services/staff.py`, plus `assert_role_free(db, role, for_user_id=None)`. It raises `ValueError("HBA already has an operations manager: <name>. Change their access first.")`. Call it from:
  - `create_invitation`: refuse if a live holder or a pending, unexpired invitation exists.
  - `change_role`
  - `accept_invitation`: re-check, because two invitations could race.
- **Mirror**: `_assert_leaves_an_admin` in `change_role`.
- **Validate**: `tests/test_order_ops_access.py`:
  - inviting a second manager is refused
  - a pending invitation blocks a second one
  - changing someone's role to operations manager is refused while one exists
  - a race on acceptance is refused
  - an operations manager calling `POST /api/auth/invitations` gets 403

#### Task 1.4: Words
- **Action**:
  - Invitation email: a branch for `operations_manager` reading "You've been given access to HBA's operations dashboard. Choose a password to get in."
  - `audit_words._ROLE["operations_manager"] = "operations manager"`.
- **Mirror**: The existing affiliate and staff branches in `notifications.py:553-580`.
- **Validate**: Test the email subject and body for each of the three branches.

#### Task 1.5: Theme for every staff role
- **Action**:
  - Add `require_staff` to `deps.py`: any role in `ASSIGNABLE_ROLES`, otherwise 403.
  - `GET /api/staff/me/preferences` and `PUT /me/theme` use it. The preference switches return empty for a role without `affiliates.view`.
  - `PUT /me/preferences` stays on `affiliates.view`.
- **Mirror**: `require_permission`.
- **Validate**:
  - An operations manager gets 200 on the theme and sees no switches.
  - An affiliate gets 403.
  - Admin is unchanged.

#### Task 1.6: Landing and shell
- **Action**:
  - `App.tsx`:
    - Role `operations_manager` → `<OperationsLayout>` with `path="*"` → `<OperationsDashboard>`. This covers sign-in and accepting an invitation, which both go to `/`.
    - Admin: `/operations/*` → the same layout and dashboard.
  - `OperationsLayout`: brand, the three tabs, an account menu (theme, sign out); no affiliate fetches.
  - `Layout`: an admin-only switch, placed per the mockup.
- **Mirror**: The `affiliate` split at `App.tsx:111`; theme handling in `Layout.tsx:56-80`.
- **Validate**: `OperationsRouting.test.tsx`:
  - The operations manager sees Operations, with no Models, Payments or Settings links.
  - Admin sees the switch.
  - No request goes to `/api/affiliates*` or `/api/operations/counts` for the operations manager.

#### Task 1.7: Settings, Team
- **Action**: In `Settings.tsx`:
  - `ROLE_LABEL.operations_manager = "Operations manager"`
  - an `ACCESS_LINES` row: "See the operations dashboard" → `["order_ops.view"]`
  - the invite-panel role columns include the new role

  The single-holder refusal shows in the invite form's existing refusal notice.
- **Validate**: Update the `SettingsTeam.test.tsx` fixtures; `npm test`; `npm run build`.

**Phase 1 gate**: The owner reviews it on a local run.

### Phase 2 — Shared operations foundation

**Done 5 Oct 2026 at `e5d3b0c`** (on `feature/operations-dashboard`, not merged). Phases 0–1 plus the cleanup went to staging (`main`) at `405a86d` the same day; production stays at `c91aff0`. Whole suite 92/92; migration `b3d81f6a2c07` rehearsed up/down/up on `hba_probe`. Two departures from the tasks below, for phases 3–5 to pick up:
- **Scheduling arrives with each handler.** The three `JobKind.ORDER_OPS_*` exist, but each joins `SCHEDULE` in its own phase, together with its handler (a scheduled kind with no handler fails every 5 minutes; `test_every_scheduled_kind_has_a_handler`). A handler is just `run_poll(db, "<source>", read)`; `read` raises `NotConnected` with no key, `KeyRefused`/`SourceUnavailable` with plain words, and returns the rows stored.
- **The API module has no route yet.** The `order_ops.view` guard is on the router itself; the permission matrix is proven on a probe route mounted with the router's own dependencies (`tests/test_order_ops_foundation.py`). Each tab's route lands with its tab, returns `freshness(db, source)`, and must be called by the frontend (reachability).
- `run_poll` replaces any non-`SourceUnavailable` exception with "Couldn't read <source>" before the worker sees it: the worker stores a failed job's message in `last_error`, its log and the failed-jobs panel.

#### Task 2.1: Working days
- **Action**: `working_days_since(moment_utc, now_utc) -> int` in `businesstime.py`. It counts Cairo dates after the moment's date, up to today, skipping Fridays. No holiday list (owner).
- **Validate**: Table-driven tests:
  - Friday start, Friday today, Thursday→Saturday, the same day
  - a UTC/Cairo midnight edge

#### Task 2.2: Source freshness
- **Action**:
  - Table `ops_source_status`: `source` PK in `{shopify, bosta, estebdal}`, `last_attempt_at`, `last_success_at`, `last_error` (plain words, no secrets), `row_count`.
  - `order_ops/freshness.py` with `record_success`, `record_failure` and `describe`, where `describe` returns `{updated_at, state: fresh|stale|failed|not_connected|never}` and `FRESH_FOR = 10 min`.
- **Validate**: Unit tests for every state.

#### Task 2.3: Poll jobs
- **Action**:
  - `JobKind.ORDER_OPS_SHOPIFY`, `ORDER_OPS_BOSTA` and `ORDER_OPS_ESTEBDAL`, each in `SCHEDULE` at `timedelta(minutes=5)`. That's the gap after finishing, plus the 60 s worker tick, so the worst case stays under 10 minutes.
  - A missing key records `not_connected` and returns without raising, so the failed-jobs list doesn't fill every 5 minutes.
  - A refused key or a network failure records the failure, then raises, so the normal retries and failed-job visibility apply.
- **Mirror**: The `RESYNC_IN_FLIGHT` entry and handler registration.
- **Validate**: `tests/test_reconcile.py`'s `SCHEDULE` and `HANDLERS` checks still pass; `/api/operations/sync` lists the three kinds.

#### Task 2.4: API module
- **Action**:
  - `app/api/order_ops.py` with prefix `/api/order-ops`; every route behind `require_permission(Permission.ORDER_OPS_VIEW)`.
  - Register it in `app/main.py` and `tests/test_reachability.py::_served()`.
  - Every response carries `freshness` per source.
- **Validate**: A permission matrix for each route:
  - operations manager and admin: 200
  - affiliate_manager, content_manager and affiliate: 403
  - anonymous: 401

### Phase 3 — Shopify tab (PRD milestone 3)

**Built 5–6 Oct 2026 at `afbb7d7`; on staging (`main`) with phase 2 on 6 Oct.** Whole suite 93/93, frontend 608 tests and build, migrations `b3d81f6a2c07` + `c7e2a9d40b15` rehearsed up/down/up on `hba_probe`. The search was checked read-only on the live shop (29 orders, as on 3 Oct). Captured headless against the mockup at 1280 and 390, both themes: the tab matches. Notes:
- The S3 card's non-zero note ("No WhatsApp message sent yet" / phone "Send a WhatsApp") is ours: the mockup only draws S3 at 0.
- At 390 the phase-1 shell puts the account row under the tabs; the mockup has the avatar in the brand row. Left for Task 7.2.
- **Worker lanes (`260325c`).** On staging's first hour a Shopify read waited 4.5 minutes behind the hourly batch of 500 line-item reads (one queue, oldest first), 10m22s after the previous read. Operations' reads (`OPERATIONS_READS`) now run in a lane of their own (`app.worker.LANES`); the main lane takes everything else and tops up the schedule. Phases 4–5 need nothing more: their kinds are already in the set.
- **Gate still open:** the owner compares each card with the same filter in Shopify admin on staging.

#### Task 3.1: Read open, unshipped orders
- **Action**: Put `OPEN_UNSHIPPED` in `order_ops/shopify.py`, not in the shared `queries.py`, so the order-sync query never changes.
  - Fields: `legacyResourceId name createdAt displayFulfillmentStatus tags`.
  - Search: `status:open -status:cancelled` with unfulfilled-or-partial; 250 per page.
  - Uses `build_client()`.
  - Before coding, confirm the partial-fulfilment search syntax with one read-only call; if `OR` isn't accepted, run two queries.
- **Validate**: A MockTransport test for paging; the live count matches the 3 Oct check's method.

#### Task 3.2: Snapshot
- **Action**:
  - Table `ops_shopify_order`: `shopify_order_id` PK, `order_number`, `placed_at`, `tags text[]`, `fulfillment_status`, `seen_at`.
  - Each poll replaces the whole set in one transaction.
- **Validate**: An order that leaves the set (shipped or cancelled) disappears on the next poll.

#### Task 3.3: Card rules S1–S7
- **Action**: `TAG_RULES` in one place, compared after strip and casefold:
  - Confirmed: `Confirmed ✅` or `Confirmed✅`
  - `No answer`, `no answer( 2 times )`
  - `WA Sent 📤`, `No WhatsApp 📵`
  - `bosta_sync_failed`
  - `compression`, `Call Confirmed📞`
  - `Cancelled ❌`

  The PRD's exclusions apply: an order tagged `Cancelled ❌` counts only on S7, and Confirmed wins over S2–S4.
- **Validate**: Table-driven tests using the 3 Oct combinations. For example:
  - `Confirmed ✅ + No WhatsApp 📵` is not on S4.
  - `Cancelled ❌ + bosta_sync_failed` is on S7 only.
  - `Confirmed ✅ + Edit ✏️ + No answer + compression` is on S1 and S6, not S2.

#### Task 3.4: Endpoint and tab
- **Action**:
  - `GET /api/order-ops/shopify` → `{freshness, cards: [{key, label, count, orders: [{order_number, placed_at, age_days, tags, admin_url}]}]}`.
  - The UI tab follows the mockup.
- **Mirror**: `stale.admin_url`; `StaleFulfilments` for the list.
- **Validate**: An API test, plus `OperationsDashboard.test.tsx` covering counts, an opened card, empty, failed (a failure never shows 0), and stale (time shown).

**Phase 3 gate**: Each card's count equals the same filter in Shopify admin at the time of the check.

### Phase 4 — E-stebdal tab (PRD milestone 4)

**Built 6 Oct 2026 at `35cba0a`, on `feature/operations-dashboard`; not on staging yet.** Whole suite 94/94, frontend 619 tests and build, migration `d4f1b8e62a39` rehearsed up/down/up on `hba_probe`; captured headless against the mockup's frame 3 (1280, both themes) and checked at 390. Facts checked read-only from staging: `x-api-key` header, `page` paging with `meta.hasNextPage`, `limit=250` honoured, 200 requests a minute, **a wrong key answers 500** (so it reads as "didn't answer", not "refused"); `ESTEBDAL_API_KEY` is set on staging (5 requests waiting on 6 Oct). Departures:
- **Links.** E-stebdal publishes no address for one request; each opens E-stebdal's dashboard in Shopify admin (`https://<shop>/admin/apps/e-stebdal`, assumed from the app's listing handle). Owner to confirm, or supply a per-request address.
- **The count is the rows stored**, not `meta.totalCount`; they agree, and a mismatch cannot then show a number the list does not have.
- A page where no item has the status asked for is a failure, not a 0; a request on two pages counts once (review findings).

#### Task 4.1: Client and poll
- **Action**: `EstebdalClient(api_key, transport=None)`:
  - `GET https://api.e-stebdal.com/api/v1/public/returns`, header `x-api-key`.
  - `filter=[{"field":"status","operator":"isAnyOf","value":["Needs Review"]}]`, `limit=250`, paged by `meta.hasNextPage`.
  - 401 or 403 → "key refused"; 429 → back off (limit is 200 per minute).
  - Key from `ESTEBDAL_API_KEY` until Phase 6.
- **Validate**: MockTransport tests with synthetic `meta`/`data` shaped like the milestone 1 response.

#### Task 4.2: Snapshot, endpoint, tab
- **Action**:
  - Table `ops_estebdal_return`: `estebdal_id`, `return_number`, `order_number`, `requested_at`, `seen_at`. **No customer info.** Replaced each poll.
  - The card count comes from `meta.totalCount`.
  - `GET /api/order-ops/estebdal`, and the UI tab.
  - The link goes to the E-stebdal return page; confirm its URL format at build, otherwise link to the dashboard home.
- **Validate**: The count equals E-stebdal's dashboard "Needs Review" at the time of the check.

### Phase 5 — Bosta tab (PRD milestone 5)

#### Task 5.1: Client
- **Action**: `BostaClient(api_key, transport=None)`:
  - Base `https://app.bosta.co/api/v2`, header `Authorization: <key>` (raw, as milestone 1 proved).
  - `POST /deliveries/search` (`limit` 200, `page`, `stateCodes`, `sortBy: -updatedAt`, `createdAtStart`/`createdAtEnd`) and `GET /deliveries/business/{tn}`.
  - Parses `creationTimestamp` (ms), JS date strings (`updatedAt`) and ISO strings (`collectedFromBusiness`, `latestAWBPrintDate`).
  - **Never reads or stores** `receiver`, any address, `notes`, phone numbers, `star` or `holder`.
- **Validate**: Parser tests on synthetic fixtures shaped like milestone 1.

#### Task 5.2: Mirror
- **Action**: Table `bosta_delivery` with `bosta_id` PK, `tracking_number` unique, and:
  - `type_value`, `state_code`
  - `created_at`, `updated_at_bosta`
  - `collected_at` (`collectedFromBusiness`)
  - `awb_printed_at` (`latestAWBPrintDate`)
  - `waiting_for_action` (`state.waitingForBusinessAction`)
  - `business_reference`, `shopify_order_number`
  - `unfinished`, `deleted_at`, `synced_at`

  Index `state_code`, `created_at` and `collected_at`.
- **Validate**: A migration test, and a schema with no customer columns.

#### Task 5.3: Poll every 5 minutes
- **Action**: Three steps each poll:
  1. Fetch the whole unfinished set (state codes 10, 11, 20–25, 30, 40, 41, 47, 102, 103, 105; about 165 orders, 1 page) and upsert it. Mirror rows still marked unfinished but now absent get re-fetched by tracking number: updated, or marked `deleted_at` on a 404. This keeps orders deleted on Bosta from inflating B1.
  2. Incremental pass: walk `sortBy -updatedAt` until reaching the high-water mark minus 15 minutes.
  3. First run: backfill from `2026-01-01` by creation range, in cursor slices.
- **Mirror**: `recipients._handle_scan_recipients` (slices).
- **Validate**: Tests covering:
  - a deleted delivery is marked gone
  - the incremental pass stops at the high-water mark
  - the backfill resumes after a crash

#### Task 5.4: Card rules B1–B6
- **Action**:

  | Card | Rule |
  |---|---|
  | B1 | `state_code = 10` and `working_days_since(created_at) > 2` |
  | B2 | Unfinished, not collected, type Send or Exchange, `awb_printed_at` is null |
  | B3 | Count by the Cairo date of `collected_at`, last 7 days including today; each day lists its orders |
  | B4 | Orders created in the range (Cairo dates, inclusive). **Successful:** Send and 45, or Exchange / Customer Return Pickup and 46. **Unsuccessful:** Return to Origin and 46 or 60. Rate = s ÷ (s + u). |
  | B5 | Unfinished and `waiting_for_action` |
  | B6 | Unfinished, collected, and `working_days_since(collected_at) > 3` |

  **Do not use `state.pickedUpTime`**: it carries the delivery date.
- **Validate**: Table-driven tests, including Fridays; B4 over a fixture month reproduces a hand-computed figure.

#### Task 5.5: Endpoints and tab
- **Action**:
  - `GET /api/order-ops/bosta` returns cards, lists and the 7-day pickups.
  - `GET /api/order-ops/bosta/success-rate?from=&to=` validates its dates. A range starting before the mirror's start returns 422 "Not available before <date>".
  - UI tab per the mockup, including the range presets.
- **Validate**: API and frontend tests.

**Phase 5 gate**:
- B5 equals Bosta's "Awaiting your action".
- B1, B2 and B6 are spot-checked in Bosta.
- B4 for September is reconciled order by order against Bosta's exported unsuccessful orders (the owner supplies the export); the tolerance is agreed.

### Phase 6 — Keys in Settings

#### Task 6.1: Saved keys
- **Action**:
  - Table `integration_secret`: `provider` PK in `{bosta, estebdal}`, `secret_encrypted`, `hint` (last 4), `verified_at`, `updated_by`, `updated_at`.
  - `order_ops/connections.py`: the effective key is the saved row if readable, otherwise the environment. `check()` makes one read call before saving. The audit entry carries no secret.
  - Reuse `_fernet` and `key_problem` by moving them to a shared helper.
- **Mirror**: `shopify/connection.py:57-261`.
- **Validate**: Tests mirroring the Shopify connection's: a wrong key is refused and the saved one kept; the secret never appears in responses or the audit log.

#### Task 6.2: Endpoints and cards
- **Action**:
  - `GET` and `PUT /api/order-ops/connections/{provider}`, behind `settings.manage`.
  - Two cards in Settings → Shopify section, per the mockup.
- **Mirror**: `ShopifyConnection.tsx`.
- **Validate**: API tests and a frontend test.

### Phase 7 — Verify, review, hand over

#### Task 7.1: Gates
- **Action**:
  - The whole backend suite, the frontend tests and the build.
  - Migration rehearsal (upgrade, downgrade, upgrade) on the disposable `hba_probe` DB.
- **Validate**: All green.

#### Task 7.2: Visual parity
- **Action**: With the `docs/repair/batch-2/visual/` harness and a throwaway DB seeded with snapshot rows, capture the operations screens at 1280, 1440 and 390, in both themes. Compare them with the approved mockup and update SCREEN_MATRIX.
- **Validate**: Differences listed or fixed.

#### Task 7.3: Reviews
- **Action**:
  - ECC Python and React reviewers.
  - Security review: secrets, outbound calls, permission matrix, customer data.
  - Database review of the migrations.

  Fix what they find, then re-run Task 7.1.
- **Validate**: No open critical or high findings.

#### Task 7.4: Staging check and handoff
- **Action**:
  - Only after the owner authorises merging to `main` (which deploys staging): the owner invites the operations manager; a browser check on staging as that account and as admin; each card compared with its source.
  - Replace the continuation handoff.
  - Update the PRD milestone statuses.
  - Production deploy only on separate authorisation, and needs the Bosta and E-stebdal keys set there.
- **Validate**: The owner signs off.

## Validation

```bash
DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform_test' .venv/Scripts/python.exe -m pytest -q --color=no tests/test_permissions.py tests/test_order_ops_access.py tests/test_reachability.py
```

```bash
DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform_test' .venv/Scripts/python.exe -m pytest -q --color=no tests/test_order_ops_shopify.py tests/test_order_ops_estebdal.py tests/test_order_ops_bosta.py tests/test_order_ops_api.py
```

```bash
bash docs/repair/batch-1/run-suite.sh
```

```bash
cd frontend && npm test
```

```bash
cd frontend && npm run build
```

One pytest process at a time against the test DB. The migration rehearsal runs on a separate disposable `hba_probe` DB, which is dropped afterwards.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Bosta renames or drops a field a card relies on (`latestAWBPrintDate`, `collectedFromBusiness`, `waitingForBusinessAction`) | Medium | The parser marks the source failed when a relied-on field vanishes from every row; the card shows the failure, never a guess. |
| Orders deleted on Bosta linger in the mirror and inflate B1 | Medium | Each poll reconciles the unfinished set and re-fetches the missing ones (Task 5.3). |
| Shopify search syntax for partly shipped orders | Low | One read-only check before coding; fall back to two queries. |
| Tag spellings drift | Medium | `TAG_RULES` in one module; later, possibly a list of unknown tags on open orders. |
| A missing key floods the failed-jobs panel | Medium | "Not connected" is a recorded state, not a failed job (Task 2.3). |
| Two operations managers through a race | Low | The partial unique index refuses it at the database. |
| A Bosta key with write access is exposed | Low | Require a read-only key; encrypted at rest; never logged or returned. |
| Release coupled to the repair | Medium | Separate branch; no merge or deploy without authorisation. |
| A memory-constrained machine | Medium | Heavy runs one at a time, in the foreground. |

## Acceptance

- [ ] Phase 0: ADR 0057, RULES.md and the mockup are approved by the owner.
- [ ] Every task is complete, each phase's gate is passed, and its PRD milestone is marked complete.
- [ ] Validation passes: whole suite, frontend tests, frontend build, migration rehearsal.
- [ ] Patterns are mirrored, not reinvented (table above).
- [ ] No customer details are stored or shown; no key appears in any response, log or audit entry.
- [ ] Every card matches its source at the acceptance check; B4 is within the agreed tolerance of Bosta's dashboard.
- [ ] The operations manager sees only Operations; affiliate and content managers and models see none of it.
