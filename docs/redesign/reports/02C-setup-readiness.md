# Batch report — Phase 02C, selected-month terms and setup readiness

**Date:** 10 September 2026
**Branch:** `phase02c/setup-readiness`, based on `main` @ `864d04d`
**Requested scope:** Atomic arbitrary month assignment with overlap/range preservation, approved locks, mixed selection and repeated Save in the same editor. Setup coverage by every eligible month, including outcome-only historical target hooks.

**Delivered behaviour:** The editor already existed. **What it could not tell
anybody was whether a model was actually set up** — and that is what this adds:
a verdict, per eligible month, computed from the rows that decide money.

---

## Review

### Half of this batch was already built

The selected-month terms editor shipped in `63c64c3`, before the redesign
package arrived. The month strip, shift-click ranges, mixed selection, approved
locks, period splitting and repeated Save in place are all there and were
verified rather than rebuilt. `BASELINE_REPORT.md` §5 recorded this; it is why
02C is a small batch.

### What it owed, and what V09 actually is

`DESIGN_REVIEW.md` puts it plainly:

> Historical readiness still uses the first `m.terms` entry rather than every
> monthly assignment. Probe reports missing terms after all eligible overrides
> were supplied.

That is the whole failure, and it fails in the dangerous direction. **A model
with terms for January alone looks arranged**, because the question being asked
was *does she have terms* rather than *does every month she was here for have
them*. Five unarranged months read as finished.

The new check asks once per month. On a model who started in January with terms
for January only:

```
eligible  6
ready     1
blocking  5
```

### And it asks a second question the editor never could

**A guaranteed-minimum month is not finished by terms.** F06: only guarantee
depends on targets. So for those months, and only those:

- **Settled outside the platform** (ADR 0036) → the recorded met/missed *is* the
  evidence, because the counts were never kept and inventing them would be
  fabricating the thing that decides money (H02). Absent, the month blocks —
  F06 is explicit that unknown qualifying information blocks a decision rather
  than being read as a failure.
- **Live** → the existing verification is the gate, because that is already what
  releases a guarantee. Adding a second approval would be a duplicate process
  for one fact.

A commission or salary month is complete with terms alone. Asking those for an
outcome would block payroll on evidence that decides nothing.

### What the owner should try

1. Open a model's **Set up … pay** screen. If anything is missing there is now a
   panel at the top: *Still needed before these months pay*, with the month and
   the reason.
2. Record her start month on her profile, then come back. The list of eligible
   months changes immediately — nothing is remembered, so nothing goes stale.
3. Set a **guaranteed minimum** on a month before go-live and save. The panel
   asks for the target outcome, which the strip itself collects.
4. Where no start month is recorded, the panel says so in as many words: the
   count is *"counted from March, which is her earliest order rather than a
   start anybody recorded"*.

**The panel is silent when there is nothing to say.** A banner announcing "all
set" on every visit is a banner that stops being read, and the one time it
matters is the one time somebody has learned to scroll past it.

### Approved-design deviations

**None.** The exports draw a setup screen; they do not specify how readiness is
decided, which is the whole of what this batch is.

---

## Engineering evidence

**Rules and IDs covered:** H01, H02, H06, F06, ADR 0036; UI11 (the readiness
half — finalisation itself remains Phase 09, per the prompt's *do not finalize
live historical records yet*). UI10 verified, not rebuilt.

### Files changed

| File | What |
|---|---|
| `app/services/setup.py` | **New.** `eligible_months`, `setup_readiness` |
| `app/api/affiliates.py` | The pay-history payload carries `readiness` |
| `frontend/src/lib/payHistory.ts` | `Readiness`, `ReadinessMonth`, `MISSING_REASON` |
| `frontend/src/screens/Compensation.tsx` + `.css` | The `SetupReadiness` panel |
| `tests/test_setup_readiness.py` | **New**, 14 tests |
| `tests/test_affiliates_api.py` | 3 more |
| `frontend/src/lib/__tests__/payHistory.test.ts` | Fixture carries the new field |

**No migration.** Readiness reads rows that already exist. **No stored flag** —
see below.

### Three decisions worth naming

**Nothing is stored, deliberately.** H06: *a first terms record or a clicked
Reviewed button does not prove readiness.* There is no `is_ready` column and no
Reviewed button, because a stored flag is a claim about the past that the
present can contradict — which is exactly what happens when somebody edits a
month after review. A test moves a model's start month and asserts the verdict
changes on the next read with nobody re-reviewing anything.

**An approved month is ready whatever else is true of it.** Its terms are frozen
in the snapshot; nothing here can ask it to change, so reporting it as blocking
would be asking for work that must not be done. Tested against a month with no
terms at all.

**Eligibility comes from her recorded start** (H01, the column 02A added),
falling back to her earliest order, and the payload says **which of the two it
used**. A model who joined in April has no January to arrange, and offering one
invites somebody to fill in three months that never existed.

### One query per table, not per month

Terms, targets and approvals are each read once and indexed in memory. Eleven
months across twenty models is otherwise six hundred round trips for something
the database answers in three — and the cost of getting that wrong grows exactly
as the programme grows.

### Commands, results, environment

| Check | Result |
|---|---|
| `pytest -q --color=no` against `hba_platform_test` | **1637 passed**, exit 0 — 1620 after 02B, **17 new** |
| `cd frontend && npm test` | **190 passed**, exit 0 |
| `cd frontend && npm run build` | exit 0 |

Green before and after.

**One test failed on the way and was right to.** A fixture inserted a verified
target with no actuals behind it; `monthly_target_cannot_verify_the_unrecorded`
refused the row. The database saying the same thing F06 does — a guarantee is
released by evidence, not by a timestamp. The fixture was wrong, not the
constraint.

### Visual comparison — not performed

Same limitation as 02A and 02B, now three batches old: browser automation cannot
sign in — the typed value never reaches the field, the form's own `required`
check blocks it, and no request reaches the server.

**The readiness panel is built, type-checked and unseen.** It renders only when
something is missing, which also means an empty staging model will not show it —
give a model a start month and no terms to see it.

---

## Continuation

### Limitations

- **Finalisation is not built**, by instruction: the prompt says not to finalise
  live historical records before Phase 09. Readiness reports; nothing signs off.
- **Data completeness is not checked.** H06 names three things — term coverage,
  required target outcomes, data completeness. The first two are here. The third
  means "are her orders actually matched and indexed for this month", which
  needs Phase 03's ingestion before it can mean anything.
- The panel appears on the pay-history editor only. A roster-wide *who is not
  ready* view belongs with the directory redesign (UI06).

### Decisions recorded

None new. D01 is unchanged and still the owner's — **this batch is what will
show whether the answers are complete once they arrive.**

### Next

**Phase 03A** — `docs/redesign/prompts/03_PRODUCTS_AND_WARDROBE.md`, first
batch: catalogue and line-item ingestion. It is the largest gap in the platform;
`BASELINE_REPORT.md` §5 lists UI12–UI20 as entirely absent. Note two things
before starting it:

- `read_products` is **not** in `REQUIRED_SCOPES` today, and nothing verifies it.
- The shipping-address phone that recipient matching depends on is **protected
  customer data**, and access was never confirmed. That is an engineering fact
  to establish against the real shop, not an owner decision — and staging and
  production share one Shopify shop, so it is checked, not experimented on.

### Live changes

**None.** Nothing deployed, no production branch moved, no financial data
touched. The branch is local and unpushed.
