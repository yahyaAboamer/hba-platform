# Batch report — Phase 04B, verification, historical outcome and the model's Targets tab

**Date:** 10 September 2026
**Branch:** `phase04b/model-targets`, based on `main` @ `3fef111`; merged to
`main` as `036ea94`
**Requested scope:** Known met/missed outcomes without invented counts for old months; current verification behaviour and evidence; models read current and history; protect target data used by immutable approval.

**Delivered behaviour:** The Targets tab is real. Two thirds of this batch
already existed and were verified rather than rebuilt — and saying which is
which is most of the report.

---

## Review

### What was already true

**Approval already protects target data.** `assert_month_recordable` and
`assert_recordable` both refuse a change to an approved month, and the first
carries a docstring saying it was added after a test found the gap. Nothing
needed adding; the batch prompt asks for a property the code already has.

**Historical outcomes already work.** `record_outcome` stores met or missed
with no counts, refuses any month at or after go-live, refuses to overwrite a
month somebody actually counted, records who and when, and writes an audit
entry that names recording and confirming as one deliberate act. That is
AC29's *outcome provenance*, and it shipped in `1fe55de`.

**Verification already behaves as §15 asks.** Confirming is a separate act from
recording, re-recording clears it, undoing it requires a written reason, and
the evidence — who, when, and what it replaced — is in the audit trail.

So 04B's real debt was the model's half: she could see the current month's
target on her month card and had **no way to see any other month**.

### The Targets tab

`GET /api/me/targets` returns every month she can look at, newest first, with
what was asked, what was recorded, how it ended, and whether that month decided
her pay. The screen is the tab the approved design has had since Phase 01 and
the platform did not.

Three rules that are easy to state and easy to get wrong in markup:

**An unrecorded month is not a missed one.** It is the state that blocks a
guaranteed minimum (§11.3), so it is precisely the month she will ask about —
and calling it a miss tells her the month is lost when it is waiting on HBA.

**A month from before the platform says the numbers were not kept.** ADR 0036.
Inventing counts to match a recorded outcome would be fabricating the evidence
for a figure that decided her pay.

**A target that decides nothing says so.** §15: on commission and on
salary-plus-commission a target is a record. `determines_pay` is computed **per
month from the arrangement she was on then**, not from her current one — she
may have moved between them, and a screen reading only the current arrangement
would be wrong about half her history.

### One implementation, not two

The month card and the tab draw the same two bars. They are now one component
(`TargetProgress`) and one vocabulary (`lib/targets`), because the third copy of
"what do we call a month nobody counted" is where the platform would eventually
contradict itself in front of the one person guaranteed to notice.

The four guarantee sentences on the tab are the ones already on the month card
and already approved. Only the informational sentence is new, because the month
card never reaches it.

### A zero is not a bar

AC30. A target of `0` produced `0 / max(0, 1)` — an empty bar under "0 of 0",
which reads as a failure at something nobody asked for. It now says *none
asked* and draws nothing. Nothing counted is still an em dash rather than a
zero, in both places.

### Preview and screenshots

**None, and not for want of trying.** Browser automation cannot sign in to this
platform — the typed value never reaches the field, so the form's own
`required` check blocks it and no request is ever made. The screens below are
reachable on staging once `main` deploys; every claim in this report is
evidenced by a test or by reading the code, and none by a look.

### What the owner should try

1. **Portal → Targets.** The month you are in at the top, every month before it
   underneath. Nothing on the screen is editable, and it says so.
2. **Targets (maintainer) → clear a model's two count boxes and save. Then open
   her portal Targets tab.** That month reads *not recorded*, not *short*.
3. **A model on commission**: her tab says her targets do not change what she is
   paid. **A model on a guaranteed minimum**: it says what is outstanding and
   whose move it is.
4. **A model with a pre-platform month** (one you recorded an outcome for on her
   profile): that row says *not kept* rather than showing counts.

### Approved-design deviations

**None.** The tab is the one the approved tab bar has always had.

### Confirmation needed before the next dependent decision

**Nothing for this batch.** The next batch, 05A, runs into **D02** — whether
final payouts stay whole-pound half-up or move to two decimals. Its recorded
recommendation is to preserve the existing rule, which is what the repo already
does, so 05A can build on that and put the question in its own report rather
than stopping for an answer now.

---

## Engineering evidence

**Rules and IDs covered:** A06, F06, H02, M01, §15, §11.3; UI23, UI24; AC29
(verified, already shipped), AC30. AC28 is 05B's.

### Files changed

| File | What |
|---|---|
| `app/services/portal.py` | **`my_targets`** — her months, her targets, per-month `determines_pay` |
| `app/api/affiliate_self.py` | `GET /api/me/targets`, and no companion write |
| `frontend/src/screens/MyTargets.tsx` + `.css` | The tab (UI24) |
| `frontend/src/components/TargetProgress.tsx` + `.css` | The bars, shared with the month card; the AC30 zero fix |
| `frontend/src/lib/targets.ts` | The four sentences and labels, in one place |
| `frontend/src/lib/portal.ts` | `MonthTargets` hoisted out of `MyEarnings`, so both screens read one type |
| `frontend/src/screens/MyMonth.tsx`, `.css` | Now uses both; its local copies deleted |
| `frontend/src/screens/AffiliatePortal.tsx` | The route, replacing `NotBuiltYet` |
| `frontend/src/screens/Targets.tsx` | Outcome and blocker read `achieved`, not `actual_videos` |
| `tests/test_portal_api.py` | 5 new |
| `tests/test_targets.py` | 2 new |
| `frontend/src/lib/__tests__/targets.test.ts` | 14 new |

### Schema, migration and compatibility

**No migration.** Migration head is unchanged at **`a2f47b8e1c53`** (35
revisions), the same head 03C left. Nothing was backfilled and no column was
added, read differently or dropped: `my_targets` reads `monthly_target` rows
that already existed, through properties (`is_achieved`, `is_backfilled`,
`is_verified`) that already existed.

**Forward and backward compatible.** The API change is one new `GET` and one
type hoisted in the frontend; every existing field of `/api/me/earnings/{month}`
is still present and unchanged. An older frontend against this backend behaves
identically — it simply never calls the new route. A rollback needs no data
work.

**No new write path anywhere.**

### Three decisions worth naming

**`determines_pay` is computed per month, from `all_terms`.** One extra query
for the whole history rather than one per month, and the loop is clamped to the
last month she can see — an open-ended arrangement must not walk into months
that have not happened.

**The wording lives in `lib/`, not in the screens.** The failures worth
guarding are semantic: *unrecorded* read as *missed*, a fabricated count on an
old month, a shortfall that reads as money gone. Those are testable as strings
and not as pixels, and `targets.test.ts` asserts each one directly — including
that no sentence for any of the twelve combinations comes back empty.

**A query-count test, not a timing test.** `my_targets` walks a year of months,
and asking the database per month inside that loop reads perfectly well. It is
twelve queries in the first year and twenty-four in the second — invisible on a
seeded database and growing with the business, which is exactly the shape that
made the Products screen slow in 03D.

### Something looked wrong and was not

The maintainer's grid decided *not recorded* and *blocks this month* from
`actual_videos === null`. On a month whose outcome was kept without counts that
would be false twice over. It cannot happen: the month picker locks every month
before go-live, and `record_outcome` refuses every month at or after it, so no
such row can reach that grid.

The conditions now read `achieved === null` anyway — the same answer, said in
terms of the thing the column is about, with a comment saying why the
difference does not currently arise. **No behaviour changed.**

### Commands, results, environment

| Check | Result |
|---|---|
| `pytest -q --color=no` against `hba_platform_test` | **1744 passed**, exit 0 — 1737 on `main`, **7 new** |
| `cd frontend && npm test` | **224 passed**, exit 0 — 206 before, **14 new** plus the accent guard's per-file additions |
| `cd frontend && npx tsc --noEmit` | exit 0 |
| `cd frontend && npm run build` | exit 0 |
| `tests/test_reachability.py` | Failed on `GET /api/me/targets` until the tab existed, then passed |
| Writable-routes guard | Unchanged and passing — this batch adds a read and nothing else |

**Re-run on `main` after the merge**, not only on the branch: `pytest -q
--color=no` → **1744 passed in 419.66s, exit 0**; `npx tsc --noEmit` → exit 0;
`npm test` → **224 passed**, exit 0; `npm run build` → exit 0. Environment:
Windows, Git Bash, `.venv/Scripts/python.exe` 3.14, local Postgres container
against `hba_platform_test`, migration head `a2f47b8e1c53`. No CI — every check
here was run locally and the numbers above are the ones the terminal printed.

### Authorisation, idempotency and money

**Authorisation.** `GET /api/me/targets` sits behind `current_affiliate`, the
same dependency as every other self route. It takes **no identifier** — there
is no id to tamper with, and `test_her_targets_are_only_ever_hers` asserts that
one model's recorded month does not appear in another's history.

**No write, so no idempotency question.** The writable-routes guard in
`tests/test_portal_api.py` still lists exactly four writable self routes, and
this batch did not touch that list. That guard failing is how anybody who adds
a fifth is made to write down why.

**No money is calculated, formatted or moved here.** The tab shows counts and
outcomes; every sentence about pay describes a rule (§15) rather than a figure,
and the figures themselves stay on the month card, which reads its snapshot.
The one money-adjacent property — that an unrecorded month blocks a guaranteed
minimum rather than reading as a miss — is asserted directly.

### Existing failures distinguished from regressions

**No pre-existing failures and no regressions.** `main` was at 1737 backend and
206 frontend before this batch and both were green; the branch is 1744 and 224,
green, and every added test is new rather than a repaired one.

Two ratchet guards failed **during** the work and both were meant to: the
reachability guard on `GET /api/me/targets` until the Targets tab called it,
and nothing else. The writable-routes guard was never touched. No test was
skipped, weakened or marked expected-to-fail.

### No real credentials or personal data in evidence

Nothing in this batch reads, stores or renders a name, address, phone number or
email. The tests use the file's existing fixtures — invented models, an example
InstaPay handle already in the repo — and no evidence in this report contains a
credential, a token or a real person's details.

### Visual comparison — performed by the owner, not by the agent

Automation still cannot sign in, so nothing in this batch was seen by me.

**The owner walked it on staging on 10 September and reported it correct** -
the model's Targets tab and, in the same pass, all four 04A grid behaviours.
That is the acceptance this batch has: a person on a phone with real data, not
a screenshot from here.

---

## Continuation

### Limitations

- **The history is a list, not a chart.** Twelve rows read down; a year of bars
  would need a second design and was not asked for.
- **No date on a history row.** `recorded_at` is in the payload and unused —
  *when somebody typed it* is not a question she has, and showing it would
  invite reading a late entry as a late month.
- **A model who has just joined sees one row**, her current month, usually
  empty. That is correct and it is a thin screen.

### Decisions recorded

**None new**, and none needed — Phase 04 asked nothing of the business.

**Two older ones were finally written down properly.** D05 and D11 were
answered on 10 September and had records under `decisions/`, but the register
in `DECISIONS.md` still listed D05 as an open question and did not mention D11
at all. Both are now marked closed in the table and listed under *Answered so
far*, and the register states which decisions remain open and which phase each
belongs to. Nothing about either answer changed; a coding agent reading the
register would simply have been told D05 was still to be decided.

### STATUS.md and coverage rows updated

- `docs/redesign/STATUS.md` — Phase 04 marked **Complete**, Phase 05 **Next**,
  migration head corrected to `a2f47b8e1c53`.
- `docs/redesign/ACCEPTANCE_CHECKS.csv` — **AC29 Pass** (outcome provenance,
  with the test that shows it from the model's side), **AC30 Partly** (the
  zero-required and unrecorded halves are done and tested; the low-performer
  threshold half belongs to 07B and is untouched).
- `CLAUDE.md` — test counts moved to 1744 / 224.

### Exact next batch and prompt

**Phase 05A — commission and financial rules.**

Prompt: `docs/redesign/prompts/05_FINANCIAL_RULES.md`. Read
`docs/redesign/STATUS.md` first, then that prompt, and run **only 05A** — the
prompt itself says to stop at the batch boundary.

Coverage it names: F01–F15, H03; UI26, UI30, UI31, UI52; AC28, AC33–AC35,
AC42–AC48, AC50, AC52, AC62, AC63. **AC28 (guarantee evidence) inherits
directly from this batch** — the three-valued `achieved` and the
verified/unverified split are the inputs it gates on, and neither should be
re-derived.

### Live changes

**None.** No deployment, no production branch moved, no financial data touched.
