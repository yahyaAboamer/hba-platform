# hba-platform

Affiliate operations, clothing gifts, sales, targets and payroll for **HBA / HBA Wear**.
The admin serves the owner, marketing team and finance team; the model portal
shows each model their own performance, wardrobe and payment records.
FastAPI + SQLAlchemy + Postgres, React + Vite, on Railway.

**Read `docs/plans/2026-09-16-exact-design-handoff.md` first** — it says where
the work is right now, and `docs/redesign/parity/SCREEN_MATRIX.md` records
each screen's state. Everything below is the part that does not change.

---

## The two halves

| | Who | Look |
|---|---|---|
| **Maintainer** | Owner, marketing and finance teams on laptops | Laptop-first; match the approved Admin HTML structure and styling |
| **Affiliate portal** (`.affiliate`) | Models on phones | Dark by default, denser, phone-shaped |

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
- **An agreed month's *money* is read from its snapshot**, never recalculated.
  A live recalculation under the word "paid" presents a working number as a
  debt. **Her sales and order counts are the opposite** (F13, ADR 0040): they
  describe what happened in the month, so a parcel refused in November
  corrects September's sales and chart while September's agreed total does not
  move. A difference after approval is settled as a correction (05C), never by
  restating the agreement.
- **A pending order counts** (F02, ADR 0040). Pending and delivered are paid;
  a failed delivery is not. Approval settles every order it counted, and
  `carried_into` now pays only what a *delivered-only* approval left out — a
  backlog that shrinks and is never added to.
- **No component names a colour directly.** The accent lives in
  `frontend/src/styles/accent.css` — eight declarations, now covering both
  halves (ADR 0039) — and `styles/__tests__/accent-isolation.test.ts` fails the
  build if those values appear anywhere else.
- **No customer data.** `order_index` and `attributed_order` hold no name,
  address, phone or email, and a test keeps it structural.
- **A correction settles money that moved; a balance is money that has not**
  (ADR 0041, amending 0035). Carrying a difference into a later month recovers
  it **there** — taking it off the source month as well recovers it twice, and
  reported E£800 still to send on a month agreed at E£2,000 with E£1,000 sent.
  Absorbing records an **`accepted`**, always: a `writeoff` means *we are not
  sending the rest* and still reduces a balance, which is the opposite of HBA
  taking a loss. Absorbing takes the whole remaining difference, so carry what
  is recoverable first.
- **One gate in front of every writer of a model's money**
  (`app/services/money_gate.py`). `approve_month`, `corrections.resolve` and
  `record_payment` all take it **before reading anything they decide on**, not
  before writing. It locks the *affiliate* row rather than a month because
  approval and `resolve` need the same two month rows in opposite orders, and
  one lock has no order to get wrong. It re-reads on the way in.
- **The payer sees the whole destination** (ADR 0042, amending 0028). The
  approved design puts the real number on the payments row and the full
  details plus the submitted InstaPay link on the detail card, with no reveal
  step - the owner asked for that explicitly. `mask_destination` still governs
  every *record*: audit rows, logs, notices, change confirmations. The full
  values go only where `payments.record` holds.
- **Historical finalisation is locked** until `HISTORICAL_FINALISATION_UNLOCKED`
  is set on that environment. The *review* is never locked - it is how the
  gaps are found. What HBA must supply first is listed in
  `docs/repair/HISTORICAL-INFORMATION-NEEDED.md`.
- **Append-only tables stay append-only**: `payroll_snapshot`,
  `payment_transaction`, `payment_allocation`, `payroll_adjustment`,
  `payout_destination`, `policy_version`. Guarded by triggers.
- **Three compensation types, not one.** `commission`,
  `fixed_plus_commission` (**both** are paid — the one most often got wrong),
  `base_guarantee` (`max(commission, base)`, only where targets were met *and*
  verified). No screen may hard-code an arrangement.

## Where the reasoning lives

- **`docs/adr/`** — 42 ADRs. The index is generated from the files. 0014 is
  superseded by 0036; 0027 is amended by 0038; **0035 is amended by 0041**, in
  one clause — a *write-off* closes a debt and a *credit* does not.
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
- Backend: `.venv/Scripts/python.exe -m pytest -q` — **2032 passing**, and no
  change merges below that. It takes 5–15 minutes; run it in the background.
- **If the suite is killed for low memory, make the groups smaller — and keep
  a record so a kill costs one group, not the run.** One pytest process grows
  as it goes and this machine has 7.9 GB, most of it spoken for: Docker alone
  holds about 1.2 GB, and on 19 September there was **0.23 GB free**, where
  groups of five *and then three* were both killed. Ten worked in early
  September, five on the 14th. There is no safe fixed number; check
  `Get-CimInstance Win32_OperatingSystem` and go smaller than the last size
  that failed.

  **On 20 September it was 0.16 GB, and one file per process was killed too** —
  twice, and both times as a *background* job while foreground runs of the same
  thing survived. The watchdog reaches for background tasks first. At that much
  pressure, run the loop in the **foreground** and re-invoke it until it reports
  nothing remaining; the log is what makes that cost nothing, because each call
  skips everything already recorded as passing at this revision. The runner used
  that day is kept at `docs/repair/batch-1/run-suite.sh`.

  **Clear the backends and empty the database at the start of every slice, not
  only after a kill.** A killed run skips its teardown and leaves committed rows
  behind, so the *next* slice opens on a dirty database and its first file or
  two fail on unique violations — `test_affiliate_self_api.py` reported "3
  failed, 4 errors" twice on 20 September and passed alone both times, which
  cost two re-runs before the cause was the obvious one. The runner does this
  itself now; a slice that starts clean is the difference between a phantom
  failure and a real one.

  **A disposable database says so inside itself, and the runner refuses any
  that does not.** It terminates every connection and truncates every table, so
  an exported `DATABASE_URL` cannot be the only thing between here and staging
  — an environment variable is exactly what goes wrong, which is what emptied
  the dev data on 10 September. The designation is a row in
  `hba_test_guard.designation`, written once by hand into a database somebody
  has decided is throwaway; it survives both `empty_the_database` (truncates
  only `public`) and `_rebuild_schema` (drops only `public`). Nothing creates it
  automatically. The refusal message carries the SQL. Exit codes: `0` green and
  finished, `1` a file failed, `2` refused and nothing touched, `3` cleanup
  failed and nothing ran, `4` budget exhausted with files left — call it again.

  One file per process is the floor, and resumable, which is what makes it
  the one to fall back to. **Record pytest's exit status, not a tail of its
  output**, and skip only what passed:

  ```
  ls tests/test_*.py > todo.txt; touch log.txt      # never truncate: that is the progress
  rev=$(git rev-parse HEAD)
  while read -r f; do
    grep -q "^PASS $rev $f " log.txt && continue    # only a pass, only this revision
    out=$(DATABASE_URL='...' .venv/Scripts/python.exe -m pytest -q --color=no       -p no:cacheprovider "$f" > one.txt 2>&1; echo $?)
    [ "$out" = 0 ] && state=PASS || state=FAIL
    echo "$state $rev $f $(tail -1 one.txt)" >> log.txt
  done < todo.txt
  grep -c '^PASS ' log.txt; grep '^FAIL ' log.txt
  ```

  Three things that version gets right and the obvious one does not. **The
  exit code is the result**: `pytest | tail` reports *tail's* status, so a
  file with a hundred failures reads as a pass. **A failure is recorded as a
  failure**, so a resume re-runs it instead of skipping it as done. **The
  revision is in the line**, so yesterday's pass is not mistaken for today's.

  Errors are worth a second look before believing them. A killed run leaves a
  backend holding locks, and every file after it reports *errors* that look
  exactly like a regression in whatever you last changed — clear the
  connection (below) and re-run the file alone before concluding anything.

  Clear the leftover backends first — a killed run leaves one holding locks.
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
- Frontend: `cd frontend && npm test` (357), `npx tsc --noEmit` and
  `npm run build`.
- **`npm run build` is the typecheck; `npx tsc --noEmit` is not.** The root
  `tsconfig.json` is a solution file — nothing but `references` — so bare
  `tsc --noEmit` checks *no files at all* and exits 0 whatever is broken. The
  build runs `tsc -b`, which follows the references and actually compiles. On
  20 September `tsc --noEmit` passed a JSX syntax error and an import of a type
  that does not exist; `npm run build` caught both. Run the build before
  believing a green typecheck.
- **Real viewport widths need `docs/repair/batch-2/set-viewport.ps1`.** The
  browser tool's `resize_window` reports success and changes nothing: Chrome
  keeps a maximised window maximised and the extension never restores it
  first. That script does the restore through Win32 and converges on the
  width; 1280 and 1440 both work, verified by reading `innerWidth` in the
  page. **Chrome's minimum window width is about 500px**, so a 390 phone
  viewport cannot be had this way at all. And when the automation shares a
  Chrome window that somebody is using, the window is restored between
  operations - verify `innerWidth` in the same batch as every screenshot, and
  name the file for the width you actually got.
- **A browser session is now possible.** Yahya signs in himself at
  `https://hba-platform-staging-staging.up.railway.app/sign-in` and the session
  is then usable for the rest of the conversation - ask for it rather than
  writing another report that says "visual evidence: none". Serve the approved
  exports for comparison with
  `python -m http.server 8899` inside `docs/redesign/designs` (`file://` URLs
  are blocked), and compare at 1280 and 1440 wide, excluding the export's own
  demo toolbar and scenario buttons.
- **The redesign is NOT complete, and a report that said so was wrong.**
  Phases 00-09 are merged and every feature works, but the screens were built
  *onto the old page structure* rather than rebuilt to the approved exports.
  This was confirmed on 12 September by rendering the reference export and the
  live staging app side by side: admin Home leads with four stacked notice
  blocks and four operational tiles where the design has three compact notices
  and three business cards; the payout breakdown sits in its own panel instead
  of inside the payment card; *Content needing a look* shows two aggregate
  counts where the design has a per-model table. Nine batch reports said
  "visual evidence: none" and none of them was wrong about that - the mistake
  was concluding that a passing test and a present feature meant parity.
  **A test that finds a word on a page does not verify the page.**
  The correction is `docs/plans/2026-09-12-design-parity-handoff.md`, batches
  C1-C5, on top of the imported branch `review/approved-design-parity`.
- Redesign 05A is a **read-only rules preview**. The normal calculation and
  approval still need verified pending-inclusive activation; D01 alone did not
  switch the code path. Do not mistake the preview's
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
- **Payments is a control desk around the existing ledger, not another
  ledger** (06A). Server totals distinguish forecast, approved gross, recorded
  and remaining money; unresolved corrections are visible across models;
  inactive obligations remain and house accounts do not. A correction-covered
  zero month creates no payment. Browser retries reuse one durable operation
  key so one external transfer cannot become two ledger rows or notices.
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
