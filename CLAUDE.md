# hba-platform — how to work here

Affiliate operations, clothing gifts, sales, targets and payroll for **HBA / HBA Wear**.
Admin serves owner, marketing and finance; model portal shows each model her own performance, wardrobe and payments.
Stack: FastAPI + SQLAlchemy + Postgres, React + Vite, Railway.

## Sources of truth

- **Rules:** `docs/RULES.md`. Read before changing anything involving money. Do not restate rules here.
- **Current work / branch / next steps:** `docs/plans/2026-09-30-continuation-handoff.md`. It supersedes older handoffs.
- **Screen parity state:** `docs/redesign/parity/SCREEN_MATRIX.md`.
- **Current visual repair evidence / decisions:** `docs/repair/batch-2/visual/CHECKLIST.md`.
- **Definition of screen “done”:** `HBA_Exact_Design_Implementation_Prompt.md`. Approved exports win on structure, copy, sizes, tones and interactions. Passing tests do not prove visual parity.

## Current operating mode

This is an **audit repair** on `repair/batch-2`.

- **Do not merge unless explicitly authorised.**
- **Do not deploy unless separately and explicitly authorised.** Merge and deploy are different permissions.
- `main` deploys staging; `production` deploys to users.
- Historical finalisation stays locked.
- Never run destructive fixtures against staging or production.
- Older “promote automatically” instructions are build-phase history and are suspended until explicitly reinstated.
- Before describing remote branch state, check it with:
  `git ls-remote --heads origin main production`
  Do not infer remote state from stale local refs.

## Backend verification

### Safe test database

Always run pytest against the disposable test database:

```bash
DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform_test' .venv/Scripts/python.exe -m pytest -q --color=no
```

Never run bare `pytest`. Without `DATABASE_URL`, tests can fall back to the dev database, and committed-test cleanup can truncate real dev data.

### Whole backend suite

Use only:

```bash
bash docs/repair/batch-1/run-suite.sh
```

The runner is resumable, one pytest process per file, and refuses databases not marked disposable. Re-run until it reports nothing remaining.

Do not use old “15 groups of 5 files” or hand-written loop instructions.

### Concurrency

- Never run two pytest processes against the same database.
- Never launch a second test while another is still running in the background against that DB.
- If parallel investigation is required, create a separate disposable DB (for example `hba_probe`), migrate it, point `DATABASE_URL` to it, then drop it.
- After a killed run, clear stale DB locks before trusting new failures:

```sql
select pg_terminate_backend(pid) from pg_stat_activity
where datname = 'hba_platform_test' and pid <> pg_backend_pid();
```

### Frontend

```bash
cd frontend && npm test
cd frontend && npm run build
```

`npm run build` is the real frontend type/build gate.
Do **not** use `npx tsc --noEmit` as the typecheck: the root `tsconfig.json` checks no source files.

### Release gates

Do not describe the repair as releasable until the outstanding release gates in the current handoff are complete, including:

- reconciliation against an authorised restored copy of real data;
- migration / rollback rehearsal for the listed current migrations and `SETTINGS_ENCRYPTION_KEY` cases.

Read the continuation handoff for the exact migration IDs and current state rather than duplicating them here.

## Visual / screen verification

The approved visual review harness is under:
`docs/repair/batch-2/visual/`

- `review.mjs` captures;
- `compare.mjs` diffs;
- `actions.mjs` exercises flows;
- its `README.md` contains the run-up.

The harness uses Playwright headless with a throwaway local DB and its own sessions. Do not reuse a person’s staging session for review sweeps.

For approved export review:

- serve `docs/redesign/designs` with `python -m http.server 8899`;
- capture the export **frame element**, not the surrounding review page;
- name captures for the actual viewport width used;
- use headless viewport widths such as 390 directly; do not treat Chrome window minimum width as a blocker.

A passing test is not a screenshot, and a screenshot is not parity. Compare against approved exports / diffs before claiming parity.

## Working with the owner

- Answer product questions and present choices **before implementing** when the owner asks for analysis first.
- Give a recommendation, not an unranked survey of options.
- Build and review in batches.
- Never claim something works without running or verifying it.
- Explicit owner requirements override earlier internal decisions.
- If the implementation intentionally diverges from an approved design, document the divergence and reason.

## Context / command discipline

Treat context as a budget.

- Read files with focused ranges; do not repeatedly reread files already in context.
- Pipe noisy shell output through `head`, `tail`, or `grep` when appropriate.
- For pytest, redirect output if needed and preserve the **pytest** exit code; do not mistake a downstream pipe command’s exit code for test success.
- Long jobs may run in the background, but wait for completion/notification rather than polling aggressively.

## Environment

- Windows + Git Bash.
- Use `.venv/Scripts/python.exe`, not bare `python`, for project Python commands.
- Disposable test Postgres is Docker Compose on port **5433**.
- Native PG18 on 5432 is a different server.
- `GO_LIVE_MONTH` is `2026-10` on both staging and production since 30 September 2026 (owner's order; it was `2026-08` / `2026-09`). Read it back from Railway before relying on it.
- Staging DB access uses Railway SSH; its `DATABASE_URL` host resolves only inside Railway’s network.
- **Railway:** the project is `hba-platform` in the **`HBA_Server`** workspace (not the personal
  `yahyaaboamer's Projects`, which is empty). A Railway connector or token that sees only the
  personal workspace sees no project; it must be granted `HBA_Server`.
- **Checking Shopify:** use the platform's own app credentials (client id + secret, the same
  connection `build_client()` uses, with the scopes the app was granted) and read-only queries,
  so the answer is what the platform itself can see. Do not use a Shopify connector for this.
- `app/web` is gitignored; never `git add` it.
- This machine is memory-constrained. Prefer foreground work when memory is tight and avoid unnecessary concurrent heavy processes.

## Handoffs

Hand over at a milestone, preferably at the end of a batch.

1. Replace `docs/plans/<date>-continuation-handoff.md`; do not append indefinitely.
2. Include branch + commit, what shipped, what remains and in what order, blockers/waiting items, decisions not to reopen, and important corrections.
3. Update this `CLAUDE.md` only when workflow changes.
4. If a business rule changes, write/modify the ADR first, then update `docs/RULES.md`.
5. Store owner working preferences in memory; store code facts in the repo.
6. Leave the tree clean and state the ending branch + commit.

# Tool orchestration

Claude Code is the primary engineering orchestrator.
Available capabilities:

- ECC
- UI/UX Pro Max
- Jev Browser

Automatically select the minimum useful tools for the task. Do not ask the owner to choose ECC commands, agents, skills, or browser tools.
Do not invoke tools mechanically when they add no value.

## Default development loop

For substantial changes:

1. Understand the requirement and inspect the relevant implementation.
2. Plan when useful.
3. Implement without changing unrelated behaviour.
4. Add/update relevant tests.
5. Run the correct tests/build/type checks.
6. Review the implementation.
7. Fix issues found.
8. For important user-facing work, verify the actual workflow before calling it done.

## ECC

Use ECC proactively when it materially improves the task, for example:

- complex feature → planning;
- architecture change → architecture review;
- feature / bug fix → TDD or testing workflow when appropriate;
- code changes → code review;
- refactor → architecture/refactor workflow;
- build/compile failure → build resolver;
- security-sensitive change → security review;
- database change → database review;
- important user flow → relevant E2E/testing workflow.

Do not require explicit ECC slash commands.
Do not run every ECC specialist on every task.

## UI/UX Pro Max

Use automatically for meaningful user-facing UI/UX work, including hierarchy, layout, spacing, typography, components, dashboards, forms, responsive behaviour, accessibility, interaction patterns, loading/empty/error states and usability.

Preserve the existing product design system and brand unless a redesign is explicitly requested.
Do not redesign unrelated screens during a focused change.
Small UI edits do not require a full redesign workflow.

The skill is vendored at `.claude/skills/ui-ux-pro-max/` (upstream
`nextlevelbuilder/ui-ux-pro-max-skill` at `09170ee`, copied unchanged), so
every session loads it, cloud included; a session started before it was added
does not see it. Its `SKILL.md` writes the search script's path with
`${CLAUDE_PLUGIN_ROOT}`, which is unset for a project skill; from the repo root
run `python .claude/skills/ui-ux-pro-max/scripts/search.py "<query>" --domain <domain>`
(`.venv/Scripts/python.exe` on Windows; standard library only).

Its results are recommendations. **The approved exports and the owner's
explicit requirements win over them**, and a suggestion that departs from an
approved screen is brought to the owner as a choice, not built.

## Jev Browser

Jev Browser is available through MCP.
Use it when real-browser verification materially improves confidence in a user-facing change, especially authentication, navigation, forms, filters, dashboard/CRUD workflows, visible state changes, important E2E flows, and reproducing or confirming UI bugs.

Do not use it for isolated backend changes, internal refactors, documentation-only changes, or other work where browser verification adds no value.

### Staging

Staging host:
`hba-platform-staging-staging.up.railway.app`

Accounts:
- model: `yousefabooamer@gmail.com`
- admin: `yahyaaboaamer@gmail.com`

Use password source:
`JEV_PASSWORD_STAGING`

Trusted origin is configured through:
`JEV_BROWSER_PASSWORD_ORIGIN`

Never ask for, print, inspect, log, copy, expose, or store the actual password.
Never use production unless explicitly authorised.
Never perform destructive actions, real payments, external communications, or production-service changes unless explicitly requested.

## Tool routing

- **Backend-only:** ECC if useful → implementation → tests → review.
- **UI improvement:** UI/UX Pro Max → implementation → relevant tests → ECC review when useful → Jev verification.
- **Full-stack user-facing feature:** ECC planning/architecture when useful → UI/UX Pro Max if relevant → implementation → tests/build → ECC review → Jev verification → fix → retest → reverify.
- **Build failure:** ECC build resolver → build/tests → review.
- **Refactor:** ECC architecture/refactor workflow → tests → review. Add Jev only if observable behaviour warrants browser validation.
- **UX bug:** reproduce when practical → UI/UX Pro Max → implement → tests → Jev verification → review.

## Browser verification standard

For important user-facing work, where practical:

1. Use the correct environment.
2. Exercise the relevant workflow with Jev Browser on staging.
3. Inspect visible failures, browser errors and behaviour.
4. Fix problems found.
5. Re-run relevant automated tests.
6. Re-verify the affected browser flow.

Do not claim a user-facing issue is fixed without reasonable evidence.

## Autonomy

The owner specifies product requirements and desired behaviour; Claude selects the engineering tools.
Automatically decide whether planning, ECC specialists, UI/UX Pro Max, browser verification, tests, review, or security analysis are warranted.
