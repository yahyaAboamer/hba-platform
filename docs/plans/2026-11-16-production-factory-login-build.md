# Production rebuild, batch 6b: the factory's own login (build plan)

Decision: `docs/adr/0084-production-is-rebuilt-around-the-production-order.md`
(build order 6: "the factory's own login (its own orders only; it enters cut
quantities, dates and progress; it sees no costs, balances or other
suppliers)"). Approved screens: `docs/redesign/mockups/production-factory.html`
(approved by the owner, 16 November 2026). Branch:
`claude/production-factory-login`. **This changes sign-in: an independent
security review is required before the pull request.**

## The owner's answers (15 and 16 November 2026)

- The factory's cut counts **wait for the QC manager to confirm** before they
  count (what the factory is paid is cut pieces times its rate).
- The factory enters **cut counts and dates only**: it moves its delivery date
  with a reason. Nothing else (it does not mark stages done).
- It never sees ratings, its record, costs, balances, payments or other
  suppliers.
- **English**, like the rest of the platform.
- **Whoever manages suppliers** (`production.suppliers`: the owner and the
  production manager) invites the factory by email from the supplier's page
  and can switch the login off there, which signs it out at once.

## Who the factory is, to the server

- A new role **`factory`** with an **empty permission set**, like `affiliate`.
  It is **not staff**: `is_staff` must treat `factory` like `affiliate`
  (today any role but `affiliate` counts as staff, which would let a factory
  reach `/api/today` and the staff preferences). Keep one constant of
  non-staff roles. A factory account must also be refused by the model
  application routes (`_applicant`): it is not a would-be model.
- A new table **`prod_factory_access`**: `id`, `supplier_id` (FK
  `production_supplier.id`), `email`, `invitation_id` (FK, nullable),
  `user_account_id` (FK, nullable, unique while live), `created_by`,
  `created_at`, `switched_off_at`, `switched_off_by`. At most one live row
  per supplier.
- **`current_factory`** dependency beside `current_affiliate` in
  `app/shared/api/deps.py`: the signed-in account must be active, hold a live
  `factory` role, and own a live `prod_factory_access` row; it returns the
  supplier. **Every refusal is 403** (never 404), as `current_affiliate`.
  `require_permission` and `current_factory` are never mixed on one route.
- The role list feeds database CHECK constraints (`role_assignment`,
  `invitation`): the migration re-creates both with `factory` added. One
  migration, the id after batch 6a's, `downgrade()` refusing while any
  `factory` role or access row exists.
- Two-step sign-in is not asked of the factory (the switch applies to staff
  only, and the factory reaches no money: its cut counts wait for the QC
  manager). Recorded as a decision, not an oversight.

## Inviting and switching off (`/api/prod`, `production.suppliers`)

- `POST /suppliers/{id}/factory-login {email, name}`: refuses an email that
  already belongs to an account (staff or model) or a supplier that already
  has a live login; creates the platform's ordinary invitation with role
  `factory` (reuse `create_invitation` and its email) and the access row.
  The general `POST /api/auth/invitations` **refuses role `factory`**: a
  factory invitation exists only through this route, so it always has a
  supplier.
- Accepting the invitation (the existing accept route) links the new account
  to the access row by `invitation_id`.
- `POST /suppliers/{id}/factory-login/resend`: a new invitation for a login
  not yet accepted (revokes the old one).
- `DELETE /suppliers/{id}/factory-login`: switches it off: revokes a pending
  invitation, or suspends the account (reuse the staff suspension service:
  status, roles revoked, every session ended), and marks the row switched
  off. Audited (`production.factory_login_*`, subject
  `production:supplier:{id}`).
- The supplier page (`GET /suppliers/{id}`) gains `factory_login: null |
  {state: invited | active | off, email, invited_at, last_seen_at}` for
  people with `production.suppliers`; absent for everybody else.

## The factory's API (`/api/factory`, `current_factory` on the router)

Every response is built from a whitelist of fields: **no key ending
`_piastres`, no "EGP", no other supplier's id or name, no ratings, no notes
written by HBA, no audit names** (HBA people are "HBA").

- `GET /orders`: its open orders (factory = this supplier), newest delivery
  date last: `id, code, style_name, colour, printing (words), planned_total,
  cut: {reported_total | null, confirmed_total | null}, status_words,
  delivery_date, moved (bool)`.
- `GET /orders/{id}`: one of its orders (open, or closed in the last 30
  days): the above plus `sizes: [{size, planned, reported | null, confirmed |
  null}]`, `report: {reported_on, note} | null`, `can_report_cut`,
  `can_move_date`, `dates: [{on, date, by: "HBA" | "You", reason}]`. Another
  supplier's order, or a cancelled one: 403.
- `PUT /orders/{id}/cut-report {sizes, note}`: allowed while the order is open
  and its cutting is not recorded; replaces an earlier report not yet
  confirmed. Sizes are the order's sizes; each 0..100000; at least one piece.
- `POST /orders/{id}/delivery-date {date, reason}`: the existing date move
  with `set_by = "factory"` (reuse batch 1's `change_delivery_date`; the date
  history and lateness rules stay theirs). Open orders only.
- Each write is audited with the factory's account as actor.

## The QC manager's side

- New table `prod_cut_report`: `order_id`, `sizes` (json), `note`,
  `reported_by`, `reported_at`, `confirmed_at` (set when the cut is recorded),
  `replaced_at`. Recording the cut (batch 1's `record_cut`) marks the live
  report confirmed. The confirmed figures are whatever the QC manager saves.
- A generated task **"Confirm the factory's cut"** (who `qc`, open `cut`, due
  the day it was reported) while a report waits; the cut form opens already
  filled with the reported sizes and says "Reported by the factory on <date>".
- The order page shows the waiting report on the Cutting stage.

## Screens

- `deskFor` (`frontend/src/lib/api.ts`) routes on permissions today, so a
  factory would land in the model portal: add `is_factory` to the actor
  (`/api/auth/me`) and send a factory account to its own desk at `/factory`
  (orders list, one order) per the mockup, phone first, 44px targets. A
  factory account opening any other address goes to `/factory`; staff and
  models never see `/factory`.
- Supplier page: a "Factory login" card for people with
  `production.suppliers`: invite (email, name), the state, resend, "Switch
  off" with a confirmation.

## Verification

- `tests/test_factory_login.py`:
  - **Every route the app serves**, called with a signed-in factory session
    (one safe call per route, any path parameters filled), is refused
    (401/403) except an explicit allow-list: `/api/factory/*`, the account's
    own `/api/auth/me`, sessions and sign-out routes, and the public routes.
    A new route added later fails this test until it is guarded.
  - Its own orders only: another supplier's order 403 on every factory route;
    a cancelled order 403; the recursive no-money / no-other-supplier check
    on every factory response.
  - Invite, accept, link; the general invitation route refuses `factory`;
    an existing account's email refused; one live login per supplier;
    switching off ends the session on its next call; resend.
  - Cut report: stored, replaced, refused once cutting is recorded; the QC
    task appears and goes when the cut is recorded; the cut form's prefill.
  - Date move by the factory lands in the history as "factory".
  - Not staff: `/api/today` and staff preferences refuse; the model
    application routes refuse.
  - The migration's downgrade refusal.
- Update `test_permissions` (the role list) and `test_several_roles` (the
  snapshot); keep green `test_prod_*`, `test_migrations`,
  `test_reachability`, `test_auth*`/invitation tests, `test_today`.
- Frontend: the factory desk (list, order, report, correct, move date), the
  routing for a factory account, the supplier page's login card per
  permission.
- Browser: local throwaway DB; invite, accept in a second browser context,
  report a cut at 390, confirm it as the QC manager, switch the login off.
- **Independent security review** (read-only) of the whole diff before the
  pull request: access control, every route's reachability by the factory,
  the invitation flow, session ending on switch-off, CSRF on the new writes,
  money and other-supplier leaks.

## What was built (16 November 2026)

- Backend: role `factory` (no permissions, not staff, never granted through
  Settings or the general invitation); `prod_factory_access`,
  `prod_cut_report` (migration `d4a8f2c60037`); `current_factory`; the
  `/api/factory` desk; invite, resend and switch-off on `/api/prod`; the
  "Confirm the factory's cut" task and the cut form's prefill.
- **A second wall, beyond the contract:** `signed_in` refuses an account that
  holds or ever held the factory role on every route except `/api/factory/*`,
  its own `/api/auth/me` and its own sessions routes. It matches the route's
  pattern, not the typed address, and fails closed. A route added later is
  refused to a factory by default. `tests/test_factory_login.py` calls every
  route the app serves as a factory and fails on anything not refused or not
  on its allow-list.
- Screens: `frontend/src/factory/` (its own plain shell with the account name
  and Sign out, which the mockup does not show), the routing by `is_factory`,
  the supplier page's Factory login card, the QC side of the cut.
- Choices and divergences:
  - Date reasons typed by HBA are shown to the factory (the mockup shows
    them); HBA's date form now says "The factory can read this."
  - A factory may report a cut before the cutting stage (the contract allows
    it while cutting is not recorded).
  - The factory may move its date only between 30 days back and two years
    ahead (from the security review).
  - The invitation link is handed to the inviter only when no email goes out.
  - An address that cannot be used gets one message that does not say why
    (no account lookup by invitation).
  - **A switched-off address cannot be invited again** (its account still
    exists, suspended): invite another address. The card says so.
  - A factory account cannot change its password from inside or use two-step
    sign-in; it recovers by the emailed reset.
  - The factory's list says "moved from <the planned date>".
- Independent security review (read-only): no critical or high findings;
  the four low ones above are fixed or recorded.
