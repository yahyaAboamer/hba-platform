# Production rebuild: handoff (15 November 2026)

This is the state of the Production rebuild (ADR 0084). It does not replace
the platform's continuation handoff; it is the one place to start for this
piece of work.

## Read first

1. `CLAUDE.md` (root): the test-database, merge and deploy rules.
2. `docs/adr/0084-production-is-rebuilt-around-the-production-order.md`: every
   decision the owner made, and the build order.
3. `docs/redesign/mockups/production-orders.html`: the approved screens for
   all five sub-tabs (sample data). The owner approved each sub-tab.
4. The four build contracts, each ending with what was built:
   `docs/plans/2026-11-14-production-orders-build.md`,
   `…-tasks-build.md`, `…-incoming-build.md`, `…-suppliers-build.md`, and
   `2026-11-15-production-overview-build.md`,
   `2026-11-15-production-ratings-build.md`,
   `2026-11-16-production-factory-login-build.md` (approved screens:
   `docs/redesign/mockups/production-factory.html`).
5. `docs/RULES.md`, the Production paragraph.

## Where it stands

| Batch | What | State |
|---|---|---|
| 1 | Orders | Merged (PR #175), live on staging |
| 2 | Tasks | Merged (PR #176), live on staging |
| 3 | Incoming | Merged (PR #177), live on staging |
| 4 | Suppliers | Merged (PR #178), on staging |
| 5 | Overview | Merged (PR #179), on staging |
| 6a | Ratings and the performance record | Merged (PR #180), on staging |
| 6b | The factory's own login | Merged (PR #181), on staging |
| Final | Start from zero (ADR 0085): the old app and records removed, the department native | Pull request open from `claude/production-switch-over`; **not merged** |
| Final | Carry the old orders over, retire the framed tab | Not started |

Production (the `production` branch) has none of this. Nothing is merged or
deployed without the owner saying so, each time.

## How it is built

- Backend: `app/modules/production/orders/` (models, `api.py`,
  `suppliers_api.py`, `guards.py`, `services/`). API under `/api/prod`.
  Tables are prefixed `prod_`; suppliers stay in the old
  `production_supplier` table, which is read and written but never altered.
- Frontend: `frontend/src/departments/production/screens/`, reached at
  `/production/*` (sidebar sections: Overview, Orders, Tasks, Incoming,
  Suppliers, Stage days). The factory's own desk is `frontend/src/factory/`
  at `/factory`, API `/api/factory` (`factory_api.py`,
  `services/factory.py`). The old framed app (`production-ui/`,
  `/production-app`, `/api/production/*`) and its tables are removed (ADR
  0085); `production_supplier` and `production_supplier_category` stay.
  `/production/next/*` and the old app's page addresses redirect.
- Migrations so far: `f6b3d8e10033` (orders), `a7c4e9f20034` (tasks),
  `b8d5f1a30035` (suppliers), `c9e6a2b40036` (ratings), `d4a8f2c60037`
  (the factory's login), `e5b9a3d70038` (start from zero: drops the old
  tables). The Overview adds none. The next id ends `0039`. Each joins the list for the migration and rollback rehearsal.
- Permissions: `production.view` reads without money; `production.edit` is
  the QC manager's writes; `production.suppliers` manages suppliers and
  sections; `production.owner` (admin only) creates, approves, settles and
  **is the only one who receives money**. Money keys are omitted, not null,
  for everybody else, on every endpoint, and every batch has a recursive
  test proving it. Keep that test in every new batch.
- The factory's login is role `factory`: not staff, no permissions, never
  granted from Settings. `current_factory` guards its desk, and `signed_in`
  refuses a factory account everywhere else by route pattern.
  `tests/test_factory_login.py` calls every route as a factory: a new route
  must be refused to it or be added to that test's allow-list with a reason.
- Money is integer piastres. The supplier account is append-only (database
  trigger); a wrong line is reversed, never edited. A write that knows an
  order locks the order first, then the supplier.

## How each batch was run (keep doing this)

1. Branch from `origin/main`: `claude/production-<batch>`.
2. Write the batch's contract in `docs/plans/` (scope, data, rules, API,
   screens, verification).
3. Hand the build to subagents with the contract; for money, a separate
   read-only review agent, then a fix pass.
4. Run the tests yourself, one pytest file at a time, against the disposable
   database only. Check the screens in a browser on a throwaway local
   database (`hba_browser`, `docs/repair/batch-2/visual/README.md`) at 1440
   and 390. `seed_browser.py` empties the production tables, so add sample
   suppliers and sections after it.
5. Pull request; wait for CI; merge only when the owner says; confirm on
   staging.

## Things that bit us

- Docker Desktop stops when the machine sleeps or restarts. It is at
  `D:\Docker\DockerDesktop\Docker Desktop.exe`. Start the container with
  `docker compose up -d` **from the main checkout**, not from a worktree
  (a worktree would make a second compose project).
- This worktree has no `.venv`: use
  `D:/Desktop/HBA/HBA Engineering/hba-platform/.venv/Scripts/python.exe`.
- `docs/repair/batch-1/run-suite.sh` is cut off every ten minutes when run in
  the background; it resumes, so run it again until nothing remains.
- `main` moves: other branches add migrations. Fetch before opening a pull
  request and renumber if an id clashes.
- `tests/test_prod_orders.py` and `tests/test_prod_tasks.py` assert the head
  revision by id; a new migration must update both.
- Two frontend tests are timing-sensitive under a full run and pass alone:
  the payment-save focus test in `SupplierPage.test.tsx` and "adds one by
  name" in `SupplierScreen.test.tsx`; also `inbox/FeedbackSetup.test.tsx`.
- The automated staging browser (Jev) needs Chromium installed; it is not.
  The owner signs in to staging in the browser pane and it is checked there.

## Waiting on the owner

- **Confirm two rules built as recommended** (ADR 0084, decision 9, the
  italic sentence): cancelling an order after cutting writes what the factory
  has earned onto its account; voiding a purchase asks whether its deposit
  was returned.
- **Merge the final batch** to staging (the staging backup is taken right before).
- **Production**: none of the rebuild is there. A production deploy needs the owner's separate go-ahead, and production's old records are backed up immediately before it.
- The typical days per stage are still the starting values; the owner edits
  them on the Stage days screen.

## Not built, on purpose

- No paging on the closed-orders list (about two orders a month).
- Fix pieces still at the factory when an order is cancelled are not paid.
- Reminders for overdue tasks; the platform's Today page does not show
  Production tasks.
- Orders settled before Suppliers is merged get no account line added back
  (there are none on staging or production).

## What is next

Every batch is built. What remains:

- **Production deploy**, on the owner's separate go-ahead: export
  production's old records first (the same script as staging's backup,
  read only, to `D:\Desktop\HBA\Backups\production-old\`, outside the
  repository), check the counts, then deploy. Migrations `f6b3d8e10033` to
  `e5b9a3d70038` join the migration and rollback rehearsal list.
- **Small, not done:** the sidebar has no overdue-tasks badge for Production
  (badges come from the Today feed, which does not read Production yet; the
  count shows on the Tasks screen). The order page's "Next:" line says
  "Record cut quantities" while a factory's report waits, where Tasks says
  "Confirm the factory's cut". A switched-off factory address cannot be
  invited again.
- **The old tables' backup**: staging's is
  `D:\Desktop\HBA\Backups\production-old\staging-2026-11-16.json`
  (53 orders, 31 samples, 32 tasks, 40 styles, 2 phases, 165 activity lines,
  the 17 suppliers and 7 categories). It is the only copy once the
  migration runs.
