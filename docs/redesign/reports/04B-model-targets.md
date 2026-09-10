# Batch report — Phase 04B, verification, historical outcome and the model's Targets tab

**Date:** 10 September 2026
**Branch:** `phase04b/model-targets`, based on `main` @ `3fef111`
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

**No migration. No new write path anywhere.**

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

### Visual comparison — not performed

Automation still cannot sign in. **The Targets tab has never been seen**, and
neither has the month card since its bars moved into a shared component. The
markup for the card is unchanged apart from the component boundary and the zero
case, but that is an argument, not a look.

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

**None new.** No business question is open for this batch.

### Next

**Phase 05A — commission and financial rules.** `docs/redesign/prompts/05_FINANCIAL_RULES.md`.

### Live changes

**None.** No deployment, no production branch moved, no financial data touched.
