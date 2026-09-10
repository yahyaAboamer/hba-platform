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
file's summary, because it is updated by every batch and this file is not.

| Phase | State |
|---|---|
| 00 Baseline · 01 UI foundations · 02 Models and setup · 03 Products and wardrobe · **04 Targets** | **Complete** |
| 05 Financial rules | **Next** |
| 06 Payments · 07 Performance screens · 08 Settings and notifications · 09 Rehearsal and release | Not started |

**1744 backend tests, 224 frontend.** Migration head `a2f47b8e1c53`; Phase 04
added none.

---

## Start here

1. Read `docs/redesign/STATUS.md`.
2. Read `docs/redesign/prompts/05_FINANCIAL_RULES.md` and run **05A only** —
   the prompt itself says to stop at the batch boundary.
3. `docs/redesign/reports/04B-model-targets.md` is the batch that just closed;
   its *Continuation* section names what 05A inherits.

**Do not read the whole project.** `docs/limits.md` alone is 2,500 lines and
would spend the context that starting a fresh session was meant to save. Read
it when you are debugging something, which is what it is for.

---

## What 05A inherits, and must not re-derive

**Targets are settled.** `achieved` is three-valued and the third value is not
a miss; verification is a separate act from recording; a month before go-live
carries an outcome and no counts (ADR 0036). **AC28 — guarantee evidence —
gates on exactly these**, and they are already right. Read
`app/services/targets.py` and `app/services/portal.py::my_targets` rather than
rebuilding the reasoning.

**Money rules that are not open questions**: integer piastres, multiply before
dividing, one half-up rounding on the total, nothing about money calculated in
the browser, an agreed month read from its snapshot. `CLAUDE.md` lists them and
they are not 05A's to revisit.

**D02 is the decision 05A runs into** — whole-pound payout rounding. Its
recommendation is to preserve what the repo already does. Proceed on that basis
and raise it in the batch report; do not stop on it.

---

## Waiting on the owner

- **Visual acceptance for 03D, 03E, 04A and 04B.** All four are merged to
  `main` and **nobody has looked at them**. The whole model Targets tab and the
  changes to the maintainer Targets screen have never been rendered in front of
  a person. Everything through 03C was walked on staging on 10 September and
  approved.
- **A scan re-run**, once, to fill wardrobes for parcels matched before 03E
  existed. Settings → Shopify & data → Match parcels from 2026-01-01. Already
  told to him; not confirmed done.

## Open decisions

**D01, D02, D03, D04, D08, D09, D10.** D05, D06, D07 and D11 are closed, each
with a record under `docs/redesign/decisions/`. None of the open ones blocks
05A; see `docs/redesign/DECISIONS.md` for which phase each belongs to.

---

## Things this project got wrong, so you do not repeat them

- **Browser automation cannot sign in.** The typed value never reaches the
  field, so the form's own `required` check blocks it and no request is made.
  Screens are verified over HTTP by the agent and by eye by the owner. **Say so
  plainly in every batch report** rather than implying a screen was seen.
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

- **C: is 99% full (1.9 GB free)** and has been since 4 September. There is
  **no CI**; every check is local.
- `main` deploys staging. `production` is deliberately one release behind;
  promoting it is a separate, owner-authorised act.
- `GO_LIVE_MONTH` differs: staging `2026-08`, production `2026-09`.
