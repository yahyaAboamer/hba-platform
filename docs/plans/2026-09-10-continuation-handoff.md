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
| 05 Financial rules | **05A implemented locally; review pending. 05B next after acceptance** |
| 06 Payments · 07 Performance screens · 08 Settings and notifications · 09 Rehearsal and release | Not started |

**1769 backend tests, 233 frontend.** Migration head `a2f47b8e1c53`; Phases 04
and 05A added none. Final backend run: 1769 passed in 383.46s, with one
non-failing local pytest cache warning. Explicit TypeScript no-emit check and
frontend build pass. Work is committed on `phase05a/pending-inclusive-earnings`,
based on verified `8ad14a6cd7453bc8140d52b6f5c64faf91927b67`: untouched original
batch `5320fd6`, code fix-up `8a20ca5`, then this documentation handoff.
The owner authorized a feature-branch push only. Nothing was merged or deployed;
05B was not started. Final branch SHA is the documentation handoff commit.

---

## Start here

1. Read `docs/redesign/STATUS.md`.
2. Read `docs/redesign/reports/05A-pending-inclusive-earnings.md`, including its
   fix-up evidence. The original batch is checkpoint `5320fd6`, with reviewed
   corrections in follow-up commits. Rendered preview acceptance remains owed.
   Review the committed branch, not an uncommitted batch.
3. After 05A acceptance, read `docs/redesign/prompts/05_FINANCIAL_RULES.md` and
   run **05B only — Immutable per-model approval**. Do not enable live policy
   or implement 05C just because the pending-inclusive preview exists.

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
