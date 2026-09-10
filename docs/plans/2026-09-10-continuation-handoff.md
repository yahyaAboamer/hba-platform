# Where the work is — 10 September 2026

**Written to be the first thing a new session reads.** `CLAUDE.md` says what
the platform is and what may never be broken; this says what is done, what is
next, and what somebody is waiting on. It replaces
`2026-09-04-continuation-handoff.md`, which describes the portal redesign that
shipped *before* the current handoff package.

**The deadline is 30 September 2026** — twenty models onboarded before a real
month is paid through the platform.

---

## What is being worked on

An approved **complete redesign**, handed over as a package at
`docs/redesign/`. It is phased, and each batch is built, reported, merged and
walked on a phone before the next one starts.

**`docs/redesign/STATUS.md` is the authority on progress.** Read it before this
file's summary; detailed evidence lives in the latest batch report.

| Phase | State |
|---|---|
| 00 Baseline · 01 UI foundations · 02 Models and setup · 03 Products and wardrobe · **04 Targets** | **Complete** |
| 05 Financial rules | **Complete** |
| **06 Payments** | **Next** |
| 07 Performance screens · 08 Settings and notifications · 09 Rehearsal and release | Not started |

**1797+ backend tests, 237 frontend.** Migration head `a2f47b8e1c53`; **no
phase since 03 has added a migration.**

**`main` is at `99907f1`** — the whole redesign through 05C. **`production` is
at `9cbfcdb`**, one batch behind: Phases 01–05B were promoted on 10 September
on the owner's explicit instruction (39 commits and 5 migrations in a single
deploy, both environments healthy), and 05C has not been promoted. Promoting is
a separate owner-authorised act.

**None of Phase 05 has been seen by anybody.** No rendered review of the
financial preview, the approve screen, the retired reopen page or the
corrections panel — and 04A/04B before them are unreviewed too. Automation
cannot sign in here, so the only way any of it gets looked at is the owner
walking it on staging.

---

## Start here

1. Read `docs/redesign/STATUS.md`.
2. Read `docs/redesign/reports/05C-late-failure-corrections.md` — the batch that
   just closed. Phase 05 is complete and merged; its screens are unreviewed.
3. Then `docs/redesign/prompts/06_PAYMENTS.md`, and run **06A only** — the
   admin month-end payment journey. The prompt itself says to stop at the batch
   boundary.

**What 06A inherits and must not rebuild.** Recording, proof, allocation and
reconciliation all exist in `app/services/payments.py` and are reusable; 06A is
the journey around them, not a second ledger. Its own prompt says so. Two
Phase 05 facts land directly on the screen money is sent from:

- A month reduced by a carried correction can be **zero**, in a month the model
  met her targets in (D04). The payments screen has to read correctly for that
  and not present it as an error.
- `GET /api/affiliates/{id}/corrections` already answers *what is outstanding
  against her*. There is **no cross-model view** — Payments does not list every
  open correction at month end, which is exactly where somebody would notice
  one they had forgotten. That is the most valuable thing 06A could add.

## Three rules that arrived in Phase 05 and are easy to break

**An agreed month is never unmade.** Reopening is retired (05B); what changes
after an agreement is a correction recorded against it (05C). Wanting to reopen
a month to fix it is exactly the thing that was removed on purpose.

**An approval agrees the figure that was shown.** The preview hands out a source
fingerprint and the commit hands it back; a commit carrying none is refused.
Every test that approves over HTTP previews first — copy that shape rather than
removing the guard.

**D04: a carried correction takes a whole month, guaranteed minimum included.**
A model can be sent nothing in a month she met her targets in. The platform
recommended protecting the floor and was overruled;
`decisions/D04-recovery-comes-before-the-guarantee.md` holds the answer and the
reasoning it overrode, and the screens are obliged to explain it to her — the
sentence is written in `_credited_from` in `app/services/portal.py`.

**Do not read the whole project.** `docs/limits.md` alone is 2,500 lines and
would spend the context that starting a fresh session was meant to save. Read
it when you are debugging something, which is what it is for.

---

## What the next batch inherits, and must not re-derive

**05A is intentionally a read-only preview.** Models → model → Financial rules
preview calls the existing staff earnings endpoint with `rules_preview=true`.
`app/services/commission/preview.py` separates current source performance,
candidate entitlement, old approval, actual allocations and legacy carry links.
`source.py` handles latest delivery facts and completeness; `calculate.py`
shares the existing terms/targets/exact arithmetic with the legacy path.
Its named entry points now make that boundary explicit: `calculate_month`
cannot accept preview source orders, while `preview_calculation` is read-only;
both use private `_calculate`. Unused per-order commission was removed, not
replaced by another display-money implementation. The preview owns its CSS,
uses MonthPicker, and gets the platform start month from the server.

**The ordinary approval still pays delivered-only.** Pending-inclusive
approval and concurrency are 05B, persistent corrections are 05C, and D01 gates
activation. Do not remove the legacy engine or settled links during review.
Ingestion now retains a known base when pending becomes void, so a failed
order's explanation survives; neither policy pays that void order.

**Targets are settled.** `achieved` is three-valued and the third value is not
a miss; verification is a separate act from recording; a month before go-live
carries an outcome and no counts (ADR 0036). **AC28 — guarantee evidence —
gates on exactly these**, and they are already right. Read
`app/services/targets.py` and `app/services/portal.py::my_targets` rather than
rebuilding the reasoning.

**Money rules that are not open questions**: integer piastres, multiply before
dividing, one half-up rounding on the total, nothing about money calculated in
the browser, an agreed month read from its snapshot. `CLAUDE.md` lists them and
they were preserved by 05A.

**D02 remains open.** 05A followed the handoff's direction to preserve existing
whole-pound payout rounding and tested the supplied examples. That is not a
new business decision.

---

## Waiting on the owner

- **05A local review/visual acceptance.** The preview is not deployed. Evidence
  is a sign-in screenshot and three HTTP 200s, then blocked inspection before
  any rendered review. **No screen in 05A has been seen by anybody.** API and
  React server-rendering tests are not a completed browser comparison.
  A separate read-only code reviewer also hit an account usage limit and
  returned no review; direct diff review and the four required checks completed.

- **03E data cleanup.** Everything else through 04B was walked on staging on 10
  September and approved - Products paging and speed, all four Targets-grid
  behaviours, and the model's Targets tab.

  **03E is blocked on data, not on code.** Several models on staging share the
  phone number `01016215036`, so shipping-phone matching returns AMBIGUOUS and
  attaches nothing. That is the designed behaviour: guessing which of five
  models a parcel went to is worse than saying it cannot be told. The owner is
  separating the numbers and will then re-run *Settings → Shopify & data →
  Match parcels from 2026-01-01*.

  **Until that happens, an empty wardrobe on staging is expected** and is not
  evidence of a bug in 03C or 03E. Do not "fix" the matcher to break ties.

## Open decisions

**D01, D02, D03, D04, D08, D09, D10.** D05, D06, D07 and D11 are closed, each
with a record under `docs/redesign/decisions/`. None of the open ones blocks
05A; see `docs/redesign/DECISIONS.md` for which phase each belongs to.

---

## Things this project got wrong, so you do not repeat them

- **pytest has no configuration that names its database.** Unset,
  `DATABASE_URL` falls through to `app/config.py`'s default — the **dev**
  database — and `conftest.py` truncates every table after each committing
  test. A whole session ran that way on 10 September and emptied the dev data;
  every test passed throughout, because the suite builds its own rows. Always:

  ```
  DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform_test'     .venv/Scripts/python.exe -m pytest -q --color=no
  ```

- **A killed pytest run leaves an idle database connection holding locks**, and
  every later `TRUNCATE` deadlocks against it. The failures appear in unrelated
  files as "An account already exists" and unique violations, and read exactly
  like a regression in what you just changed. Terminate connections to
  `hba_platform_test`, empty it, then re-run one file alone before believing
  anything.
- **This machine may not have memory for the full suite.** Three runs were
  killed on 10 September with 0.56 GB free of 7.9 GB. Check free memory before
  concluding a run "failed"; restarting Docker Desktop reclaims most of it.
- **A killed pytest run leaves an idle database connection holding locks**,
  and every later `TRUNCATE` deadlocks against it. The failures surface in
  unrelated files as "An account already exists" and unique violations, and
  read exactly like a regression in what you just changed. Terminate
  connections to `hba_platform_test` (`pg_terminate_backend`), empty it, then
  re-run one file alone before believing anything.
- **This machine may not have memory for the full suite.** Three runs were
  killed on 10 September with 0.56 GB free of 7.9 GB. Check free memory before
  concluding a run failed; restarting Docker Desktop reclaims most of it.
- **One pytest process at a time**, and never one while another runs in the
  background. Two against the same database deadlock and leak committed rows
  into each other, and the failures look exactly like a regression in whatever
  you just changed. Same day; it cost an hour.
- **Check whether a helper already exists before writing one.** Two were
  duplicated in Phase 05 — a per-order commission and a month-name formatter —
  and both were dead code shadowed by the original.

- **Do not overstate browser evidence.** In 05A the DOM proxy reported empty
  fields while a sign-in screenshot showed typed values. `/api/auth/login`,
  `/api/auth/me` and `/api/payroll/2026-09` returned HTTP 200. Further inspection
  hit a browser auto-review usage-limit rejection before any rendered review.
  Those observations establish neither failed typing nor a reviewed 05A screen.
- **The design-package raw hashes differ on Windows.** Eight assets use CRLF
  in this checkout; all eight match the manifest after LF normalization. The
  designs have no Git changes from `8ad14a6`. Preserve the files and report the
  raw checker failure rather than silently rewriting the originals/manifest.
- **`railway domain` with no arguments creates a domain**, it does not list
  one. It was run against production Postgres by mistake on 10 September; the
  owner deleted it and its absence was confirmed. The read-only form is
  `railway domain --service <name> --environment <env> --json`.
- **Never tell the owner to test a batch before it is merged.** It happened
  with 03B: he refreshed, saw nothing, and was right.
- **Regex rewrites of test files damage them.** Twice — once mangling a helper,
  once wedging a function between a fixture decorator and its function. Edit by
  hand or with an anchored replacement, and read the seam afterwards.
- **A guard failing is the guard working.** `test_reachability.py`,
  `accent-isolation.test.ts`, the writable-routes list and
  `payoutLabels.test.ts` all fail deliberately when somebody adds something.
  Update the guard *with its reasoning*; never weaken it to pass.
- **`app/web` is gitignored.** It is the built frontend, not a committed
  bundle.
- **The local Postgres container stops between sessions.**
  `docker compose up -d postgres`, then wait on `pg_isready`.

---

## Environment

Everything runtime — seed accounts, the test-database identity procedure, the
design-reference server — is in `docs/redesign/BASELINE_REPORT.md` §10. Read
that rather than rediscovering it.

05A used a separate synthetic **`hba_platform_05a_preview`** database on local
Postgres 5433, at the same migration head. The existing `seed_demo.py` clears
its target, so it was not run against the existing dev database. The isolated
additive seed helper is `design-preview/seed-05a.py` (gitignored local artifact).
It checks the exact database name and refuses to reseed a nonempty database.
Runtime/review commands and synthetic account details are in the batch report.

- **C: is 99% full (1.9 GB free)** and has been since 4 September. There is
  **no CI**; every check is local.
- `main` deploys staging. `production` is deliberately one release behind;
  promoting it is a separate, owner-authorised act.
- `GO_LIVE_MONTH` differs: staging `2026-08`, production `2026-09`.
