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
   `…-tasks-build.md`, `…-incoming-build.md`, `…-suppliers-build.md`.
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
| 6b | The factory's own login | Pull request open from `claude/production-factory-login`; **not merged** |
| Final | Carry the old orders over, retire the framed tab | Not started |

Production (the `production` branch) has none of this. Nothing is merged or
deployed without the owner saying so, each time.

## How it is built

- Backend: `app/modules/production/orders/` (models, `api.py`,
  `suppliers_api.py`, `guards.py`, `services/`). API under `/api/prod`.
  Tables are prefixed `prod_`; suppliers stay in the old
  `production_supplier` table, which is read and written but never altered.
- Frontend: `frontend/src/departments/production/next/`, reached at
  `/production/next/*` (tabs: Orders, Tasks, Incoming, Suppliers, Stage
  days). The Production department is still `own: true`: the old framed app
  (`production-ui/`, `/api/production/*`, the `production_*` tables,
  `tests/test_production_api.py`) is untouched and keeps working until the
  final batch.
- Migrations so far: `f6b3d8e10033` (orders), `a7c4e9f20034` (tasks),
  `b8d5f1a30035` (suppliers). The Overview adds none. The next id ends
  `0036`. Each joins the list for the migration and rollback rehearsal.
- Permissions: `production.view` reads without money; `production.edit` is
  the QC manager's writes; `production.suppliers` manages suppliers and
  sections; `production.owner` (admin only) creates, approves, settles and
  **is the only one who receives money**. Money keys are omitted, not null,
  for everybody else, on every endpoint, and every batch has a recursive
  test proving it. Keep that test in every new batch.
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
- **Merge the Overview pull request** to staging.
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

**Batch 5, Overview** (`#v-overview` in the mockup): nothing to type; it
reads the other four. Decisions waiting for the owner, problems (late
orders, late materials, count mismatches, cost over target), every order
with its next action, the nearest deliveries, what is owed. The QC manager
sees it without the money card and the cost line. No migration.

**Owner's answers for batch 6 (15 November 2026):** the factory's own cut
counts wait for the QC manager to confirm them before they count; the factory
enters cut counts and dates only (moving its delivery date with a reason),
nothing else; the rating form is offered when an order is settled and can be
skipped and done later; the factory never sees ratings or its record.

**Batch 6**: a rating per supplier per order when it is settled (quality,
timing, dealing with them, 1 to 5 stars, a note; timing offered from the real
lateness), the lateness and reject record per supplier, and the supplier
list's ratings line and "Usual lateness" figure that batch 4 left out. Then
the factory's own login: its own orders only; it enters cut quantities,
dates and progress; it sees no costs, balances or other suppliers. The login
is a new kind of user: plan its security review before building.

**Final batch**: carry the old orders, samples and uploads over from the
`production_*` tables, make the department native (sidebar sections, drop
`own: true` and the iframe), and retire `production-ui/`. This one removes
things: it needs the owner's explicit go-ahead and an ADR for what is kept.
