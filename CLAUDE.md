# hba-platform — how to work here

Affiliate operations, clothing gifts, sales, targets and payroll for
**HBA / HBA Wear**. The admin serves the owner, marketing and finance; the
model portal shows each model her own performance, wardrobe and payments.
FastAPI + SQLAlchemy + Postgres, React + Vite, on Railway.

**This file is workflow. The rules are [`docs/RULES.md`](docs/RULES.md)** —
one shared source that this file and `AGENTS.md` both point at and neither
repeats. Read it before changing anything that touches money, and never
restate a rule here.

**Where the work is: [`docs/plans/2026-09-24-continuation-handoff.md`](docs/plans/2026-09-24-continuation-handoff.md)**
— branch, commit, what is done, what is next. It replaces every earlier
handoff; the old ones carry a banner saying so and are kept.

Per-screen state against the approved exports is
`docs/redesign/parity/SCREEN_MATRIX.md`, and the current sweep's evidence and
outstanding decisions are `docs/repair/batch-2/visual/CHECKLIST.md`.

**What "done" means for a screen** is the owner's own standard, unchanged:
`HBA_Exact_Design_Implementation_Prompt.md` at the repo root. Every screen
matches its corresponding element in the approved exports — structure, copy,
sizes, tones, interactions — and a passing test is not evidence of it.

---

## Right now: repair, not release

The work is an **audit repair** on `repair/batch-2`. Three standing
instructions from the owner override the build-phase habits below:

- **Do not merge, and separately, do not deploy.** These are **two
  permissions, not one.** Being told the repair may merge to `main` does not
  authorise promoting to `production`: `main` deploys staging, `production`
  deploys to the people who use it, and the second needs its own yes. Never
  read one as implying the other.
- **Historical finalisation stays locked.**
- **No destructive fixture ever touches staging or production.**

### The deployment rule, and why it is paused

The build-phase rule was: *push to both branches — `main` deploys staging,
`production` is a fast-forward of `main`, keep them level (ADR 0034), promote
without asking.* It came from
`docs/plans/2026-09-12-design-parity-handoff.md` and it was right for that
phase, when no real model was onboarded and there was nothing to lose.

**It is suspended for the duration of the repair**, by the owner's explicit
and repeated instruction. It resumes when he says so — and *"you may merge"*
is not that sentence. Promotion is its own decision and needs its own yes.

If a memory or an older document tells you to promote automatically, it is
describing the build phase. This paragraph is the current one.

**Read the remote before describing the remote.** `origin/main` and
`origin/production` are both at `6a13958` — level, a gap of zero. A document
in this repository claimed production was *122 commits behind* for a day;
that number came from the **local** `production` ref, which nobody had
updated. `git ls-remote --heads origin main production` is the check, and a
local `git rev-list --count production..main` is not.

---

## Verification

### The database, every time

```
DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform_test' \
  .venv/Scripts/python.exe -m pytest -q --color=no
```

**There is no pytest configuration that does this for you.** Unset, it falls
through to `app/config.py`'s default — the **dev** database — and
`conftest.py` truncates every table after each committing test. A whole
session ran that way on 10 September and emptied the dev data. Every test
passed, because the suite builds its own rows.

`README.md` used to show a bare `pytest`; that is corrected, and this is the
form to copy.

### The whole backend suite: one command

```
bash docs/repair/batch-1/run-suite.sh          # ~540s of work, then stops
```

One file per pytest process, resumable, and it **refuses any database that
has not said inside itself that it is disposable**. Call it again until it
reports nothing remaining. Exit codes: `0` green and finished, `1` a file
failed, `2` refused and nothing touched, `3` cleanup failed and nothing ran,
`4` budget exhausted with files left.

This replaces two older instructions that still appear in old handoffs:
**"run the suite in fifteen groups of five files"** and the hand-written
`while read` loop. Both are superseded; the runner is that loop, hardened.

**Current: 2,069 tests, 80 files, all passing** (24 September 2026),
reconciling exactly with `--collect-only`. No change merges below that. On
this machine a full pass took three calls and about an hour.

### One pytest at a time

Never two against the same database, and never one while another runs in the
background. They deadlock and leak committed rows into each other, and the
failures look exactly like a regression in whatever you just changed. It has
cost hours twice, and it produced two false findings on 23 September.

A killed run leaves a backend holding locks. Clear it before believing
anything:

```
select pg_terminate_backend(pid) from pg_stat_activity
where datname = 'hba_platform_test' and pid <> pg_backend_pid();
```

A second database is the safe way to investigate one file while a suite runs:
create `hba_probe`, migrate it, point `DATABASE_URL` at it, drop it after.

### Memory

7.9 GB on this machine and most of it spoken for; Docker alone holds about
1.2 GB. Background jobs are reaped first under pressure — the app and export
servers were stopped mid-session on 23 September for exactly that. Check
`Get-CimInstance Win32_OperatingSystem` before starting anything large, and
prefer the foreground when it is tight.

### Frontend

```
cd frontend && npm test          # 420 tests, 21 files
cd frontend && npm run build     # this is the typecheck
```

**`npx tsc --noEmit` is not a typecheck and must not be used as one.** The
root `tsconfig.json` is a solution file — nothing but `references` — so it
checks *no files at all* and exits 0 whatever is broken. On 20 September it
passed a JSX syntax error and an import of a type that does not exist;
`npm run build` caught both. An earlier version of this file listed
`tsc --noEmit` among the verification steps and contradicted itself two
paragraphs later. It is removed.

### Release gates still outstanding

Neither has run, and nothing in the repair reports satisfies either:

1. **Reconciliation against an authorised restored copy of real data.**
   `docs/repair/batch-1/reconcile.py` has only ever run against the test
   database.
2. **A migration/rollback rehearsal for `b1f0a40c0001`.**

Do not describe the repair as releasable while these are open.

---

## Looking at screens

**The reviewing browser is Playwright, headless, in its own process:**
`docs/repair/batch-2/visual/` — `review.mjs` captures, `compare.mjs` diffs,
`actions.mjs` exercises. The `README.md` there has the full run-up. It signs
itself in against a throwaway local database, never staging, and it does not
touch any browser a person is using.

Three earlier instructions are superseded, and are the reason this exists:

- **"Ask Yahya to sign in at staging and reuse the session."** Not needed:
  the harness makes its own sessions, one browser context per role, so the
  admin and a model can be open at once. That was recorded as a blocker in
  the September handoffs and in `SCREEN_MATRIX.md`; it is cleared.
- **"Use `set-viewport.ps1` for real widths."** It works, and it moves a
  window somebody is using. Keep it for a one-off look at a real window; do
  not use it for a sweep.
- **"Chrome's minimum window width is about 500px, so 390 is unreachable."**
  True of a window, irrelevant to a headless viewport. 390 is a number in a
  config object now.

What still holds: serve the approved exports with
`python -m http.server 8899` inside `docs/redesign/designs` (`file://` is
blocked); capture the export's **frame element**, not the page, so its review
toolbar is excluded by construction; and name every file for the width it was
actually taken at.

**A passing test is not a screenshot, and a screenshot is not parity.** Nine
batch reports said "visual evidence: none" and concluded parity anyway from
passing tests and present features. Diff the digests; that is what finds a
heading that lost its unit.

---

## How the business works with us

- **Answer every question before implementing.** They walk the product on a
  phone, write up what they saw, and expect the questions answered and the
  choices laid out *before* anything is built. Then they approve, then build.
- **Give a recommendation, not a survey.** They ask for options and pick fast.
- **Ship in batches**, each reviewed on its own.
- **Never claim something works without running it.** They test on a real
  phone with real data and will find it.
- **The approved design wins over an internal decision.** Said explicitly on
  20 September about the payment-details screen: *"Earlier internal decisions
  do not override my explicit requirements."* Where we keep a divergence, it
  is written down as a divergence with its reason, not left to be found.

---

## Spend context like it is the budget

In the session that built the redesign, **file reads cost 1.7M tokens and
Bash results 299k** — vastly more than the conversation. The waste is never
where you expect it.

- **Read with `offset`/`limit`.** Never re-read a file already in context.
- **Pipe every Bash result** through `head`, `tail` or `grep`.
- **Redirect pytest to a file and echo `$?`.** A pipeline reports *`tail`'s*
  exit code, so a run with a hundred failures reads as a pass.
- Long runs go in the background — but **wait for the notification**. Polling
  immediately after starting a sleep measures nothing, which wasted a dozen
  checks on 23 September.

---

## Environment

- Windows, Git Bash. Use `.venv/Scripts/python.exe`, never `python`.
- Test database: docker-compose Postgres on **5433**. A native PG18 on 5432 is
  a different server.
- `GO_LIVE_MONTH` differs: staging `2026-08`, production `2026-09`. Never
  assume one while running in the other.
- Staging database access: `railway ssh --service hba-platform-staging
  --environment staging`, then Python inside the container — the
  `DATABASE_URL` host only resolves in Railway's network.
- `app/web` is gitignored; never `git add` it.

---

## Handing over

Hand over at a milestone, not at a breakdown — the end of a batch is the
cheapest moment.

1. **Replace `docs/plans/<date>-continuation-handoff.md`**, do not append.
   Branch and commit, what shipped, what is left and in what order, what
   somebody is waiting on, decisions not to reopen, and anything you got
   wrong.
2. **Update this file** if a *workflow* changed. If a *rule* changed, it
   needed an ADR first, and then `docs/RULES.md` follows the ADR.
3. **Write a memory** only for how the owner wants to work. Facts about the
   code belong in the repo.
4. **Leave the tree clean and say which branch and commit it ends on.**
