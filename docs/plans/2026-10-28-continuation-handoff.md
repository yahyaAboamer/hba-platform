# Where the work is — 28 October 2026 (HBA OS Phase 1 complete: batches 1.0–1.4 live; Phase 2 next)

Supersedes `2026-10-11-continuation-handoff.md`, which stays as the record of
the audit repair and the WhatsApp inbox; its open items are carried below.
The overall picture is `hba-os-roadmap.md`; Phase 1's plan is
`2026-10-25-phase-1-foundations.md`, its checkpoint
`2026-10-25-phase-1-progress.md`.

## The exact position

Re-read the remote before describing it: `git ls-remote --heads origin main production`.

| | |
|---|---|
| **Code on both sites** | `origin/main` = `origin/production` = `ce1ab52` (PR #132, department folders), deployed 28 October on the owner's order; production health answers 200 (GET and HEAD) at `affiliate.hbawear.store` |
| **Migration head** | `e7b3d1f60021` on staging and production (Batch 1.4 added none); 18 append-only triggers intact on both |
| **Production config** | `TWO_STEP_ENFORCED=true` since 28 October (owner's order). Inbox switches as in the old handoff. Sentry DSNs set. Mail through Brevo |
| **Staging config** | `TWO_STEP_ENFORCED=true` on `hba-platform` (staging) and a reference `${{hba-platform.TWO_STEP_ENFORCED}}` on `hba-platform-staging` — see `docs/operations.md`: staging values live on the old service, while the app that deploys from `main` is `hba-platform-staging` |
| **Branches** | No work branch open. `feature/whatsapp-inbox` can be deleted (its two documents are in `main`) |
| **CI** | `backend` (department import check, then the whole suite, ~9–12 min) and `frontend` on every PR. Branch protection is blocked until GitHub Pro (owner) |

## What Phase 1 shipped (25–28 October)

| PR | What |
|---|---|
| #125 | CI; Sentry on backend, frontend and worker with scrubbing; health checks answer HEAD (UptimeRobot) |
| #126 | Release gates rehearsed on production's backup: restore, reconciliation (all zero — no payroll yet), migration rollback; restore runbook corrected |
| #127 | Several roles per person (ADR 0067 decisions 1–3, 7–9): *Add access* / *Remove* on Team; audit tagged by department |
| #128, #129 | Two-step sign-in with an authenticator, recovery codes, *Signed in on* (devices), suspending removes every role and ends every session; fixes from the live check (QR namespace; `two_step` read from `actor`) |
| #130 | The owner's amendment (ADR 0067 decision 5, 27 October): the second step only on a browser not remembered (30 days); **the owner** gives an authenticator code, **money roles** a code by email, other staff opt in, models never |
| #132 | Department folders (ADR 0065): moves and import lines only, import-linter in CI. Proven unchanged against `main`: OpenAPI byte-identical (167 paths), 50 tables and columns, 27 job handlers, `alembic check` clean, all 121 test files pass |

Each was reviewed by an independent Opus reviewer; every finding above Low was
fixed, the reasoning is in each PR. Batches 1.2–1.3 were checked in a real
browser on production, read-only, with the owner signing in; #132 changes no
behaviour and was checked by health and sign-in page only.

## Where the code lives now (ADR 0065)

- `app/shared/{api,models,services}` — sign-in, staff, access, audit, jobs,
  mail, notifications, the Shopify connection, schedule.
- `app/modules/affiliates/{api,models,services}` — everything for models:
  codes, targets, commission, payroll, payments, wardrobe, portal.
- `app/modules/inbox/` and `app/modules/operations/` — `api.py`,
  `models.py`, `services/`.
- `app/modules/production/` — empty until Phase 4.1.
- Each department has a `public.py`: the only part another department may
  import. `[tool.importlinter]` in `pyproject.toml` enforces it (`lint-imports`);
  two crossings that existed on the day are listed there as exceptions with a
  reason, and the list may only shrink.
- Unmoved on purpose: `app/main.py`, `app/worker.py` (moving it changes how
  Railway starts the worker), `app/config.py`, `app/db.py`, `app/core/`.
- `app/models/__init__.py` still imports every model so Alembic sees them all.

## State to know on 28 October

- **Enforcement is on in production** and the owner has finished
  authenticator set-up there, kept the recovery codes, and told the affiliate
  manager about email codes (confirmed 28 October).
- **Staging test account:** `yahyaaboaamer+hbatest@gmail.com`, affiliate
  manager, email codes, one remembered browser (the automation profile) until
  27 November. Mail to it reaches the owner's normal Gmail. Keep it for tests.
- **Staging owner account** has the authenticator on; another staging admin
  (`abdalrhmaan2412@…`) has not, and will be held at set-up on staging.
- **Left behind locally:** throwaway databases `hba_batch14` and `hba_batch3c`
  in the Docker Postgres on 5433, and a detached worktree of old `main` at
  `D:/claude-tmp/base` (`git worktree remove`). Drop them when convenient.
- **Drive C: is full** (0 bytes free on 28 October). Point `TMP`/`TEMP` at
  `D:/claude-tmp` and write command output to files on D:; Docker's data is on
  D:. Shell pipes on C: fail with "No space left on device".

## Remaining, in order

1. **Phase 2 — the unified HBA OS frame** (roadmap Batch 2.1; ADR 0068;
   approved mockup `docs/design/hba-os-shell-2026-10-25.html`): departments
   declared once, the sidebar, department addresses with redirects, Today,
   Team and access by department, the Settings split, the phone layout. No
   Phase 2 plan file exists yet: write one first
   (`docs/plans/<date>-phase-2-frame.md`, batches and tasks, like Phase 1's),
   get the owner's word on it, then build batch by batch, each on its own branch
   and PR. Designs win over taste (memory: the approved design wins).
2. **Phase 4.1 — Production moves in** (ADR 0069, mockup
   `docs/design/hba-os-production-frame-2026-10-25.html`): waits on the
   owner's ChatGPT source export. Do not put the old Production site's address
   in the repository while it is public.
3. **Inbox phase 8, retiring n8n**: two clean weeks ended about 29 October;
   only on the owner's word. The platform still sends with n8n's Meta key and
   tags with n8n's Shopify app — keep both (old handoff, Remaining 2).
4. **Reconciliation rerun** after the first payroll month is approved.
5. Carried from the old handoff, not blocking: its Remaining 3–5, 7, 8, 10–12
   (inbox security review and checks, the owner's Meta phone number, Nada
   alhady's sign-in, WhatsApp charges, Operations acceptance, the reset-email
   limit point, the optional database items, the shell at 390). Its item 9
   (release gates) was done on 25 October.
6. From the two-step reviews, not built: an email when the password was right
   but the code wrong; the owner's reset also ending that person's sessions.
7. From the Batch 1.4 review, Low, not built: the import check covers only each
   department's `api`/`models`/`services` (a file placed straight in a
   department folder is not checked yet); `notification_prefs` would sit better
   under affiliates; some comments still give old slash-style paths;
   `import-linter` is not pinned in `constraints.txt`.

**Owner actions outstanding:** GitHub Pro (then require `backend` and
`frontend` on `main` and `production`), the ChatGPT export, the word on
retiring n8n, freeing space on C:.

## Decisions not to reopen

- ADR 0065–0069 (one application by department, one database, several roles
  per person, one frame, Production keeps its look and moves its data in).
- ADR 0067 decision 5 as amended on 27 October (above). Enforcement is the
  owner's switch, `TWO_STEP_ENFORCED`; a password reset asks for the code only
  of authenticator users; the owner cannot reset their own — recovery codes
  are the way back.
- Suspending removes every staff role and ends every session; reactivating
  gives no access back; a former member of staff can never apply as a model.
- All decisions listed in the old handoff (inbox, Operations).

## How the work has been done (keep doing it)

- **After every deploy, a real-browser check** with `playwright-cli`
  (session `hbacheck`, persistent, headed); the owner types passwords;
  production read-only, writes only on staging test records (memory:
  browser check after each push).
- **Merge and deploy are separate permissions**, each given by the owner.
  Deploy = fast-forward `production` to `main` after a merge, then watch
  `hba-platform` in Railway's production environment reach SUCCESS.
- **Security-sensitive work:** write one API contract first, build backend
  (Opus, high effort) and frontend (Sonnet, medium) in parallel as subagents,
  then an independent Opus security review, fix, whole suite, PR, CI.
- **Tests only on disposable databases** carrying the `hba_test_guard`
  designation (`docs/repair/batch-1/run-suite.sh` explains); never bare
  pytest; never `hba_platform_test` when another session may use it.
- **New backend code goes in its department's folder**; reaching into another
  department goes through its `public.py`. Run `lint-imports` before pushing.

## Corrections worth knowing

- A hook ("Fact-Forcing Gate") blocks the first Bash, Edit or Write on each
  file and some commands until the facts it asks for are stated; state them and
  retry.
- Railway CLI is `C:/Users/AboAmer/AppData/Roaming/npm/railway.cmd`; read a
  database with `railway ssh --service hba-platform --environment <env> --
  "echo <base64 script> | base64 -d | python -"` and grep the result line.
  `railway variables --kv` shows resolved values, not whether one is a
  reference: never print values. `railway status --json` shows each service's
  latest deploy, its commit and status.
- Git Bash rewrites container paths: prefix `docker exec` with
  `MSYS_NO_PATHCONV=1` when a path is involved.
- The shared venv at the main checkout (`../../../.venv` from a worktree) was
  missing packages pyproject requires; they were installed at pinned versions
  on 28 October, with `import-linter`.
- Sessions last 12 hours; a browser check after a gap needs the owner to sign
  in again.
- The server sends `two_step` inside `actor`, not at the top of the session.
- Production runs Postgres 18.6; local tests and CI use 17.
