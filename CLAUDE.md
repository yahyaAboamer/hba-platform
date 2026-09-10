# hba-platform

Commission and payroll for ~20 Egyptian beauty models at **HBA Aesthetics**.
FastAPI + SQLAlchemy + Postgres, React + Vite, on Railway.

**Read `docs/plans/2026-09-10-continuation-handoff.md` first** — it says where
the work is right now. Everything below is the part that does not change.

---

## The two halves

| | Who | Look |
|---|---|---|
| **Maintainer** | 2 people, laptop, month end | Dense, laptop-first, colour only for money state |
| **Affiliate portal** (`.affiliate`) | ~20 models, phone, arriving from an email | Dark by default, denser, phone-shaped |

**One palette across both, since ADR 0039** — HBA green, both themes, defined
once in `tokens.css` with the accent alone in `accent.css`. `portal.css` is
still scoped to `.affiliate`, but it now isolates *layout* rather than colour:
the phone's spacing, its tab-bar clearance, its furniture. **Keep that
isolation** — it is why the portal could be redesigned three weeks before
payroll without touching a maintainer screen.

## Rules that must not be broken

- **Money is integer piastres.** Never a float. Multiply first, divide once
  (ADR 0003), round once on the total (ADR 0004).
- **Nothing about money is calculated in the browser.** The server sends the
  figure; a second implementation is a second answer waiting to disagree in
  front of the one person guaranteed to check.
- **An agreed month is read from its snapshot**, never recalculated. A live
  recalculation under the word "paid" presents a working number as a debt.
- **No component names a colour directly.** The accent lives in
  `frontend/src/styles/accent.css` — eight declarations, now covering both
  halves (ADR 0039) — and `styles/__tests__/accent-isolation.test.ts` fails the
  build if those values appear anywhere else.
- **No customer data.** `order_index` and `attributed_order` hold no name,
  address, phone or email, and a test keeps it structural.
- **Append-only tables stay append-only**: `payroll_snapshot`,
  `payment_transaction`, `payment_allocation`, `payroll_adjustment`,
  `payout_destination`, `policy_version`. Guarded by triggers.
- **Three compensation types, not one.** `commission`,
  `fixed_plus_commission` (**both** are paid — the one most often got wrong),
  `base_guarantee` (`max(commission, base)`, only where targets were met *and*
  verified). No screen may hard-code an arrangement.

## Where the reasoning lives

- **`docs/adr/`** — 38 ADRs. The index is generated from the files. 0014 is
  superseded by 0036; 0027 is amended by 0038.
- **`docs/limits.md`** — every failure met, what it looked like from outside,
  and the fix. **Read this before debugging anything.**
- **`docs/plans/`** — what is being built and why.
- **`docs/specs/`** — the original design.
- **The code comments.** This codebase explains its own decisions; a docstring
  that says "and this caught us once" is describing a real incident.

## How the business works with us

- **Answer every question before implementing.** They walk the product on a
  phone, write up what they saw, and expect the questions answered and the
  choices laid out *before* anything is built. Then they approve, then build.
- **Give a recommendation, not a survey.** They ask for options and pick fast.
- **Ship in batches**, each merged and promoted on its own.
- **Push to both branches.** `main` deploys staging; `production` is a
  fast-forward of `main` and deploys production. Both stay current while no
  real model is onboarded (ADR 0034). Staging and production are **separate
  Railway services with separate databases** — but they **share one Shopify
  shop**, so never start a bulk import from staging.
- **Never claim something works without running it.** They test on a real
  phone with real data and will find it.

## Verification

- **Set `DATABASE_URL` before pytest, every time.**

  ```
  DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform_test'     .venv/Scripts/python.exe -m pytest -q --color=no
  ```

  There is **no pytest configuration that does this for you**. Unset, it falls
  through to `app/config.py`'s default, which is the **dev** database
  `hba_platform` - and `conftest.py`'s `fresh_database` truncates every table
  after each committing test. A whole session was run that way on 10 September
  and emptied the dev data; the tests all passed, because the suite builds its
  own rows, so nothing said anything was wrong.
- **One pytest process at a time**, and never one while another is running in
  the background. Two against the same database deadlock and leak committed
  rows into each other, and the failures look exactly like a real regression
  in whatever you just changed. Also on 10 September, and it cost an hour.
- Backend: `.venv/Scripts/python.exe -m pytest -q` — **1797+ passing**, and no
  change merges below that. It takes 5–15 minutes; run it in the background.
- **A killed pytest run leaves a connection behind that deadlocks the next
  one.** Teardown is skipped, an idle backend keeps holding locks, and every
  later `TRUNCATE` deadlocks — producing "An account already exists" and
  unique-violation failures across unrelated files that read exactly like a
  regression in whatever you just changed. Clear it before believing anything:

  ```
  select pg_terminate_backend(pid) from pg_stat_activity
  where datname = 'hba_platform_test' and pid <> pg_backend_pid();
  ```

  Then empty the database and re-run the file alone. Happened 10 September and
  cost the best part of an hour.
- Frontend: `cd frontend && npm test` (233) and `npm run build`.
- Redesign 05A is a **read-only rules preview**. The normal calculation and
  approval remain delivered-only until D01; do not mistake the preview's
  entitlement for a transfer instruction.
- **An agreed month is never unmade** (05B). Reopening is retired; what changes
  after an agreement is recorded against it as a correction (05C). An approval
  agrees the figure the preview showed, and a commit that cannot say what that
  was is refused.
- **An agreed month that turns out wrong is corrected, never unmade** (05C).
  `app/services/corrections.py` compares the frozen snapshot to a fresh
  calculation; a person carries the difference into a later month or absorbs
  it. Recovery is capped at what was actually paid, and the comparison runs the
  real engine twice so the guarantee applies itself.
- **A carried correction takes a whole month, guaranteed minimum included**
  (D04, 10 September 2026). A model can be sent nothing in a month she met her
  targets in, so the screens explain it - see `_credited_from` in
  `app/services/portal.py`, where the sentence is written.
- The suite is the ratchet. `test_reachability.py` fails when a route has no
  way in from the interface; `accent-isolation.test.ts` fails on a hard-coded
  accent; the writable-routes guard fails when anybody adds a route a model
  can call. **These failing is them working.**

## Spend context like it is the budget

It is. In the session that built the redesign, **file reads cost 1.7M tokens
and Bash results 299k** — vastly more than the conversation. MCP tools cost 66.
The waste is never where you expect it.

- **Read with `offset`/`limit`.** Never re-read a file already in context, and
  never read a whole file for ten lines.
- **Pipe every Bash result** through `head`, `tail` or `grep`. A bare `grep -rn`
  across the repo once returned 180KB.
- **`pytest -q --color=no | tail -5`.** The colour codes in a full run are
  thousands of tokens of `[32m.[0m`, and only the last line matters. **Redirect
  to a file and echo `$?`** rather than piping straight to `tail`: the pipeline
  reports *`tail`'s* exit code, so a run with a hundred failures still exits 0
  and reads as a pass if you only check the status.
- The suite takes 5–15 minutes: run it with `run_in_background` and poll.

## Handing over to a new session

This project outruns a single conversation. **Hand over at a milestone, not at
a breakdown** — the end of a batch, once it is merged and promoted, is the
cheapest moment: nothing is half-finished and the state is a sentence.

When Yahya says he wants to start a new chat, do this before he closes it:

1. **Update `docs/plans/<date>-continuation-handoff.md`** — replace it, do not
   append. It says what shipped, what is left and in what order, what somebody
   is waiting on, and the decisions not to reopen. Add anything you got wrong,
   so the next session does not repeat it.
2. **Update this file** if a rule changed, a batch finished, or the test count
   moved.
3. **Write a memory** for anything about *how he wants to work* that is not
   already there. Facts about the code belong in the repo, not in memory.
4. **Leave the tree clean and both branches level.** A new session should never
   inherit uncommitted work.

His first message in the new chat is then two lines: read the handoff, start
the next task. Never tell him to "read the whole project" — `limits.md` alone
is 2,500 lines and would spend the context that was the point of starting over.

## Environment

- Windows, Git Bash. Use `.venv/Scripts/python.exe`, not `python`.
- `GO_LIVE_MONTH` differs: staging `2026-08`, production `2026-09`. Never
  assume one while running in the other.
- Staging database access: `railway ssh --service hba-platform-staging
  --environment staging` and run Python inside the container — the
  `DATABASE_URL` host only resolves in Railway's network.
