# Batch report — Phase 05A, pending-inclusive earnings and source performance

Date: 10 September 2026.

Branch: `phase05a/pending-inclusive-earnings`.
Base commit: `8ad14a6cd7453bc8140d52b6f5c64faf91927b67`.
The checkout started clean on `main`, exactly at the expected completed commit;
`git merge-base --is-ancestor <expected> HEAD` returned 0. The original batch
was committed untouched as `5320fd6` before this report's fix-up pass. Follow-up
commits preserve its reviewed decisions and address the seven requested fixes.
Code corrections are commit `8a20ca5`; this documentation handoff is a separate
commit after the final checks. The final SHA is the handoff commit on this branch.
No merge, deployment or live financial data changes. Branch push is authorized;
`main` and `production` must not be updated by this handoff.

Requested scope: **05A only**, under `prompts/05_FINANCIAL_RULES.md` and the
10 September continuation handoff. Implement pending-inclusive source earnings,
preserve exact money/target rules and legacy evidence, without switching live policy.

Delivered behavior: a real staff-facing, read-only financial-rules preview,
backed by the existing earnings API and shared compensation calculation.
Pending and delivered orders count once in their original month. Failed orders
do not count, even without Shopify cancellation. Source sales are independent
of old delivery-carry allocations, immutable approval and actual transfers.

## Review

### Local preview and what to try

**This batch is not on staging.** Review this local branch or merge it through
the separately authorized workflow before expecting it on a shared environment.

Open **Models → a model → Financial rules preview**. Expand the panel and select
an eligible month. It reports source sales, delivery counts, candidate earnings,
existing approval and recorded transfer allocations. It has no approval/payment
action. Requests load only when expanded, clear stale content across month/model
changes, and report errors with a Retry action rather than showing zero money.

Suggested checks using synthetic/local data:

1. A pending order worth EGP 20,000 at 10% contributes EGP 2,000 in the preview.
   The ordinary delivered-only payout remains unchanged.
2. Change it to delivered: source earnings stay the same; a later month's new
   rules preview does not gain delivery-carry commission.
3. A failure removes current source sales/earnings while previously approved
   money and real transfer allocations remain separate and unchanged.
4. A model with old carry allocations sees the source month, allocated month
   and statement reference, with an explicit reconciliation notice. Allocation
   is not called a recorded transfer.
5. Missing delivery facts or uncertain original delivery money show incomplete
   data. Missing/unverified guarantee evidence reports what needs checking.

Local review database: `hba_platform_05a_preview`, synthetic only, local port
5433, migration head `a2f47b8e1c53`. It is separate from both the existing dev
database and the disposable pytest database. Local app: `http://127.0.0.1:8010`.
Synthetic sign-in: `owner@example.com` / `a-long-enough-password`; model ID 1.

Start/restart the already-seeded local app in PowerShell:

```powershell
$env:DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform_05a_preview'
$env:APP_ENV='development'
$env:GO_LIVE_MONTH='2026-09'
$env:WORKER_ENABLED='false'
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

The isolated additive seed helper is `design-preview/seed-05a.py`, a gitignored
local artifact. It asserts the exact database name and refuses a nonempty
database. The existing destructive `scripts/seed_demo.py` was **not run**.
No existing dev data was cleared to prepare this review.

### Design and rendered evidence

Read the two selected references: `Affiliate Portal v3.dc.html`'s counted sales
and delivered/pending/failed split, and `Admin Dashboard.dc.html`'s model
performance layout and order/commission fields. The new disclosure uses the
existing panel, typography, money component and theme tokens. The fix-up gives
it its own row/layout CSS and the shared MonthPicker; it no longer borrows
AffiliateDetail's styles or restates the platform start date in the browser.

**Deviation for batch staging:** the new rules are an explicitly labelled staff
preview beside the current figures, rather than replacing payment instructions
before 05B/05C and D01. No new top-level destination, palette or prototype runtime.
The model order screens and charts are still Phase 07.

**No completed rendered comparison of the new panel.** Browser navigation was
initially rejected by automatic approval review for a usage limit. After the
stated retry time, the same local browser check was retried successfully. A
sign-in screenshot showed typed values even though DOM snapshots and DOM value
inspection reported empty fields. Normal form submission produced:

- `POST /api/auth/login` → 200;
- `GET /api/auth/me` → 200;
- authenticated `GET /api/payroll/2026-09` → 200.

The next browser inspection was again rejected by automatic approval review for
an account usage limit. No alternate browser or authentication bypass was used.
**These observations do not establish a rendered 05A review. No screen in 05A
has been seen by anybody.** The new panel, both themes, responsive widths and error/retry interactions still
need rendered review. The three React server-rendering tests are not browser QA.

### Decisions

D02's **existing whole-pound half-up rounding is preserved**, following the
explicit continuation instruction to proceed. D02 remains open; no new owner
answer is recorded. D01 remains the live-transition gate. No unanswered business
decision prevented this read-only 05A implementation.

## Engineering evidence

### Files and contracts

| File | Change |
|---|---|
| `app/services/commission/source.py` | Read-only current source facts; status/basis completeness; explicit late failure despite legacy terminal attribution |
| `app/services/commission/calculate.py` | Separate public `calculate_month` and `preview_calculation` share private `_calculate`; only the explicit preview entry point accepts source facts, includes pending and omits incoming delivery carry |
| `app/services/commission/preview.py` | Source performance, candidate entitlement, immutable approval, actual ledger allocations and legacy link reconciliation; unused per-order commission removed in fix-up |
| `app/services/commission/attribute.py` | Preserve a known pre-failure basis when an in-flight order becomes void; neither engine pays void orders |
| `app/api/earnings.py` | Optional `rules_preview=true` on existing staff model/month GET; normal response unchanged without it |
| `frontend/src/components/FinancialRulesPreview.tsx` and `.css` | Month-scoped disclosure with MonthPicker, own layout, reasoning comments, real API, separate money concepts, missing-data/error/retry handling |
| `app/api/affiliates.py`, `frontend/src/screens/AffiliateDetail.tsx` | Reachable preview on existing staff profile; server supplies `platform_start_month` for preview and collaboration-start input |
| `tests/test_financial_rules_preview.py`, `tests/test_earnings_api.py` | 23 new backend cases including parameterized variants |
| `frontend/src/components/__tests__/FinancialRulesPreview.test.tsx` | 3 new rendering tests; existing accent guards also cover the new source files |

Rules covered: F01–F06, F13–F15 and H03 within the read-only engine scope.
Coverage: AC28/AC33/AC48/AC50/AC52/AC62 partial foundations; AC63 passed.
UI26/UI30/UI31/UI52 remain for their assigned later batches; no claim that
approval, reopen retirement or correction decisions shipped in 05A.

### No schema or policy activation

No migration, backfill, snapshot rewrite or bulk settled-link reset. Migration
head remains `a2f47b8e1c53` (35 revisions). Old statements and transfers remain
readable. Normal `calculate_month`, approval, reopen and payment callers still
use the legacy path. The preview always returns `can_approve=false` and
`activation_blockers=[live_transition_not_enabled]`.

The only ingestion behavior change preserves a known void-order display basis.
Its commission state remains void, so both policies still exclude it. A failed
order whose authoritative original basis was already lost remains unavailable.
Original total alone is not treated as a recovered original commission base
when original shipping/tax are not established.

### Exact examples and financial distinctions

The first two rows are executable assertions against
`evidence/financial-examples.json`, not copied prototype calculations.

| Example | Before / after checked |
|---|---|
| `pending_once` | Source sales 2,000,000 piastres at 1,000 bp: legacy pending payout 0; new candidate commission/payout 200,000. After delivery it remains 200,000; later-month preview adds 0. A legacy approval still approves 0 while the order is pending. |
| `base_and_rounding` | Customer total 115,700 − shipping 9,500 − tax 0 = base 106,200. Exact commission 10,620 piastres (EGP 106.20); existing payout rule gives 10,600 (EGP 106), regardless of inflated item subtotal. |
| Mixed fractional commissions | 40 orders, half pending/half delivered, each base 10,015 at 333 bp: exact aggregate 13,339.98 piastres, final payout 13,300. No per-order rounding feeds that total. |
| Legacy carry | Original-month approval 0, next-month legacy carry approval 200,000. New source preview shows 2,000,000 sales and 200,000 entitlement; destination own sales/entitlement 0. Both old snapshots and the settlement link survive repeated previews. |
| Failed after approval / partial transfer | Approved 10,600; actual allocation 5,000; current source entitlement becomes 0 after explicit failure. Approval stays 10,600, actual allocation stays 5,000 and existing ledger balance stays 5,600. No automatic recovery or changed transfer instruction. |

The fixed-plus-commission example's **gross earnings** are verified at
50,000 commission + 100,000 fixed = 150,000 piastres. Its 20,000 earlier
deduction and 130,000 transfer due are **not implemented here**. Likewise,
`guarantee_met_late_failure`, `guarantee_missed_late_failure`, `insufficient`,
`two_deductions_one_capacity` and `guarantee_cumulative` remain 05C correction
examples, not evidence of implemented recovery. The inherited target rules are
tested separately for unknown, missed, met-unverified and met-verified outcomes.

### Original checkpoint checks and results (`5320fd6`)

Windows/PowerShell, repository Python 3.14 virtualenv, real local PostgreSQL.
Before pytest, a connection through `app.db.engine` queried and asserted
`current_database() == 'hba_platform_test'`. Every pytest process ran sequentially.
The separate preview database was migrated independently; no concurrent Alembic
ran against the pytest database. Existing append-only guards were not weakened.

```powershell
$env:DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform_test'
.venv/Scripts/python.exe -m pytest -q --color=no -p no:cacheprovider
```

| Check | Actual result |
|---|---|
| First preview API test, before implementation | 1 expected failure, 1 permission test pass; missing preview assertion |
| Source behavior tests before basis preservation | 2 expected failures, 18 passes; known pre-failure value was lost |
| Actual-allocation test before settlement extension | Expected failure on missing allocation field |
| Display-commission assertions before adding the field | 3 expected failures on missing display commission |
| Targeted financial/regression run below | **313 passed in 108.16s**, exit 0 |
| Preview/API run after final display addition | **44 passed in 49.53s**, exit 0 |
| Final full backend run, including final per-order display fields | **1767 passed in 241.10s**, exit 0 |
| `npm.cmd test -- --reporter=dot` in `frontend` | **231 passed**, 6 files, exit 0 |
| Final `npm.cmd run build` in `frontend` | TypeScript + Vite pass, exit 0, 129 modules |
| `git diff --check` | Pass; Git reports expected LF/CRLF working-copy warnings |
| Local `/api/health/ready` | HTTP 200, database/configuration ready, Shopify unconfigured |

Targeted command:

```powershell
.venv/Scripts/python.exe -m pytest -q --color=no -p no:cacheprovider tests/test_financial_rules_preview.py tests/test_commission_state.py tests/test_commission_base.py tests/test_commission_calculate.py tests/test_commission_attribute.py tests/test_commission_backfill.py tests/test_earnings_api.py tests/test_payroll.py tests/test_payroll_lifecycle.py tests/test_payments.py tests/test_businesstime.py tests/test_money.py
```

The first pytest run reported a local cache-directory permission warning.
Subsequent runs disabled only pytest's cache plugin; no tests were skipped or
marked expected-to-fail. An initial test-helper import failed during test-file
assembly and was replaced by a self-contained fixture before feature checks.
No existing application test failures remained in the full run.

### Package-integrity limitation, investigated

`$env:PYTHONUTF8='1'; .venv/Scripts/python.exe docs/redesign/evidence/verify-package.py`
returns **exit 1**, with eight source-asset raw SHA mismatches. All cross-reference
checks pass: 19 assets exist, 52 screen rows, 64 acceptance rows, 10 prompts.

Read-only SHA checks demonstrated that **all eight match their recorded hash
after CRLF → LF normalization**. `git diff --name-only 8ad14a6 --
docs/redesign/designs` is empty. These are checkout line-ending differences,
not changed approved designs. The checker, manifest and design files were left
unchanged; its raw-byte gate is not falsely recorded as passing.

### Authorization, money and data

The optional preview inherits `affiliates.view` from the existing route; an
affiliate-role direct call returns 403. No new writable route or capability.
Read-only previews create no payroll or payment rows. Repeated reconciliation
keeps the same snapshot IDs, content hashes and settlement links. Tests retain
real synthetic payment allocations even when a month is classified historical.
No customer contacts, real credentials, personal data or real payment proof are
in this report or its fixtures. All database changes were local test/demo data.

## Fix-up pass — 10 September 2026

The owner requested seven bounded corrections, not a redesign. The first act
was to commit the original uncommitted batch untouched as `5320fd6` on
`phase05a/pending-inclusive-earnings`. All fixes follow that checkpoint.

1. **Approval safety:** `calculate_month(db, affiliate, month)` now always
   selects the legacy delivered-only calculation. It cannot accept source
   orders. Explicit `preview_calculation(..., source_orders=...)` selects the
   pending-inclusive policy; private `_calculate` keeps terms, targets and
   exact aggregate arithmetic shared. Both entry-point docstrings explain why
   approval must not gain a hidden preview mode.
2. **Unused display money removed:** the preview no longer builds `order_lines`
   or computes `display_commission_piastres`. Raw source diagnostics remain;
   known failed basis survives and unknown basis is null. The portal's existing
   commission/forgone helper is unchanged. AC52 no longer claims evidence of
   per-order display commission or order-screen rendering.
3. **House-style panel:** multi-line JSX, reasoning comments, dedicated CSS and
   the existing MonthPicker. Source candidates, approved obligations and actual
   transfer allocations remain independent server facts; no browser arithmetic.
4. **One platform calendar:** staff model detail sends `platform_start_month`
   from `PLATFORM_START_MONTH`; the profile uses it both for the preview window
   and its collaboration-start input, with no browser hard-coded start month.
5. **State classification explained:** the VOID branch comment records that it
   matches the old `else` for today's three real states, while excluding the
   preview's fourth pseudo-state, `unavailable`. It warns that a future real
   state requires explicit classification.
6. **Readable engine:** the legacy query and source-fact path have explicit
   branches and named locals; the counting loop receives `(state, base)` pairs,
   without distant conditional expressions or repeated `isinstance` ternaries.
7. **Evidence corrected:** STATUS restores C: 99% full (1.9 GB free), no CI,
   and limits browser evidence to a sign-in screenshot plus three HTTP 200s,
   then blocked inspection before rendered review. **No screen in 05A has been
   seen by anybody.** No new browser review was attempted during this fix-up.

### Fix-up verification

Real local PostgreSQL, `current_database()` verified as `hba_platform_test`
before tests. One pytest process at a time; no production or dev database was
used for the destructive test fixtures. No migrations or financial data changes
outside synthetic test data. All commands below ran from the repository root
or `frontend` as appropriate, using PowerShell's `.cmd` npm/npx launchers.

| Check | Actual result |
|---|---|
| New approval-entry-point and server-start-month regressions before fixes | 2 expected failures, 44 deselected |
| Targeted preview/API suite after fixes | 46 passed in 22.97s; one local pytest cache warning |
| Final `.venv/Scripts/python.exe -m pytest -q --color=no` | **1769 passed in 383.46s**, exit 0; one non-failing cache warning |
| Final `npm.cmd test` | 233 passed, 6 files, exit 0; existing source guards include the new stylesheet |
| Final `npx.cmd tsc --noEmit` | Exit 0 |
| Final `npm.cmd run build` | Exit 0; 130 modules, Vite build 6.68s |
| `git diff --check` | Exit 0 |

The exact full pytest command kept its cache plugin enabled. Its only warning
was `PytestCacheWarning`, WinError 183 while creating `.pytest_cache/v/cache`;
no tests failed, were skipped or were marked expected-to-fail. An additional
read-only reviewer was requested under the review skill but hit an account
usage limit and returned no review. Direct diff review completed; no independent
reviewer sign-off or rendered acceptance is claimed.

The source-facts split, unavailable-is-not-pending rule and aggregate-once
arithmetic were preserved. No test functions were removed: three obsolete
per-order commission assertions were dropped with the unused output, and a
failed-order regression now asserts that misleading field is absent. Two new
backend regressions enforce the entry-point and server-calendar boundaries.
React server-rendering tests remain source-level evidence, not browser QA.

## Continuation

05A's local implementation is complete and verified; **stop for its review**.
Rendered financial-panel comparison/owner acceptance is still outstanding.
No claim of live pending-inclusive payments, migration rehearsal, persistent
correction events, cumulative recovery, chosen deductions or reopen removal.

Updated `STATUS.md`, `ACCEPTANCE_CHECKS.csv`, `BACKEND_CONTRACTS.md`,
`DECISIONS.md`, `CLAUDE.md` and the 10 September continuation handoff. Corrected
the contradictory old Phase 01/02 summary at the top of STATUS; retained earlier
owner acceptance and 03E's unresolved data gate.

**After 05A acceptance: Phase 05B — Immutable per-model approval.**
Prompt: `docs/redesign/prompts/05_FINANCIAL_RULES.md`, **05B only**.
Use the shared source/entitlement service, add source-version/concurrency and
snapshot freezing, and retire active reopen paths while preserving history.
05C owns late-failure decisions and persistent allocations. D01 owns live
transition; D04/D09 still govern their affected correction operations.

The fix-up authorizes committing and pushing this feature branch only. Do not
merge, deploy or begin 05B. The original batch's formerly uncommitted state is
recoverable at checkpoint `5320fd6`; use the follow-up commits for current code.
