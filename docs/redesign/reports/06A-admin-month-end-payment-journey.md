# Batch report — 06A admin month-end payment journey

Date: 11 September 2026

Branch and base/current commit: `phase06a/admin-month-end-payments`, based on
`0f0ce641f81a2209cb211a5f51251e82c5f44159`; final batch SHA is reported at
handover because this report is part of that commit.

Requested scope: Phase 06A only — the admin month-end payment journey. Do not
start the model-facing 06B work, merge or deploy.

Delivered behavior: Payments is now an admin control desk around the existing
payment ledger. It separates forecast, approved gross, funds required, money
already recorded and money still to transfer; retains inactive obligations;
excludes house accounts; surfaces unresolved corrections across models; and
names a correction-covered zero month as **No transfer due**. From one row an
authorized payer can review/agree the immutable calculation, reveal the full
destination, copy or open the exact submitted InstaPay URL, record the actual
amount/date/reference/proof, and land on genuine append-only history. A durable
operation key makes retry-after-timeout and double-click safe.

## Review

- Preview and relevant screenshots/video: no live browser capture was made.
  React server-rendering tests cover exact InstaPay, bank/card and WE Pay wallet
  destination shapes. Source and API-contract review cover the complete
  journey; this is engineering evidence, not visual acceptance.
- What the owner should try:
  1. Open Payments for a mixed month and reconcile Total funds required,
     Recorded as sent and Still to transfer against forecast, approved,
     partially paid, fully paid and no-transfer rows.
  2. Filter and search the list, then open an awaiting-approval model, agree
     the reviewed figure and confirm the journey returns to Payments.
  3. Review InstaPay, bank/card and wallet destinations. Copy/Open must not mark
     anything paid; the exact submitted InstaPay URL must remain visible.
  4. Record a partial transfer with a chosen date, reference and proof, then
     verify that history shows the transaction and its month/snapshot
     allocation context.
  5. Double-click or retry the same record request and confirm only one
     transaction/notification exists.
  6. Inspect a D04 month fully covered by a carried correction: it must say No
     transfer due, explain the gross-versus-net difference and offer no
     zero-payment form.
  7. Review the cross-model correction queue, including any inactive or
     archived model with money still outstanding.
- Approved-design deviations and reason: the approved Payments reference did
  not contain a cross-model correction queue. A conditional dense queue was
  added above transfers because profile-only correction visibility can let a
  recoverable amount be forgotten at the exact point month-end money is sent.
  The existing separate Payments, approval, record and history routes were
  retained rather than rebuilding their ledger behavior in one screen.
- Confirmation needed only for the next dependent business decision: none for
  06A. D09 still governs future cross-month correction splitting/remainder
  policy and was not reopened.

## Engineering evidence

- Rules and screen/action IDs covered: A07, A08, F07, F08, F14; UI25–UI29,
  UI31 and UI32. AC31/AC32/AC36/AC37/AC40 are partly evidenced because their
  remaining Home, model-facing or live-browser portions belong to later
  review/batches. AC38 and AC39 pass with direct retry tests.
- Files/services/API contracts changed: `app/api/payments.py`,
  `app/services/payments.py`, `app/models/payments.py`; `Payments`,
  `PaymentRecord`, `AffiliatePayments`, the approval return path and correction
  anchor; focused backend and frontend tests; payment contracts and handoff
  evidence.
- Schema migration/backfill and compatibility: migration `1c4b06a5f8d2` adds a
  nullable unique `payment_transaction.operation_key`. Historical rows and
  legacy callers remain valid without a backfill. New browser requests send a
  stable key. Same-key/same-facts replay returns the original transaction;
  different facts conflict; the unique constraint handles races.
- Exact test/build commands, actual results and environment:
  - With `DATABASE_URL=postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform_test`,
    `.venv/Scripts/python.exe -m pytest -q --color=no tests/test_payments_api.py tests/test_payments.py tests/test_payout_destinations.py tests/test_corrections.py tests/test_affiliates_api.py`
    — **252 passed** in 86.14 seconds; one harmless pytest-cache permission
    warning.
  - `cd frontend && npm.cmd test` — **246 passed** across seven files.
  - `cd frontend && npx.cmd tsc --noEmit` — exit 0.
  - `cd frontend && npm.cmd run build` — exit 0; 132 modules transformed.
  - `.venv/Scripts/python.exe -m alembic heads` —
    `1c4b06a5f8d2 (head)`.
  - With the same explicit test URL, after available memory recovered from 557
    MB to 962 MB, `.venv/Scripts/python.exe -m pytest -q --color=no` —
    **1807 passed** in 282.26 seconds; the same pytest-cache warning. One
    process ran and zero stale test-database connections were found before it.
- Visual comparison performed / not performed: no live comparison was
  performed. The implementation follows the existing dense house style and
  approved Payments reference; destination variants were verified by React
  rendering tests only.
- Authorization, idempotency and money checks relevant to this batch: existing
  payout reveal/proof permission tests are in the passing focused set. API
  tests prove one transaction, allocation and notification on replay; reject a
  key reused for different money; retain a successful proof upload across a
  failed save; reject invalid/oversized/cross-model proof use; exclude house
  accounts; retain inactive obligations; and require zero funds for a D04
  correction-covered month while preserving its approved gross figure.
- Existing failures distinguished from regressions: no product regression was
  found. The build initially exposed one missing approval-return prop and was
  corrected before the passing rerun. The only remaining check message is the
  existing unwritable `.pytest_cache` warning.
- No real credentials/PII in evidence: confirmed. Tests use synthetic models,
  destinations, references and proof bytes. No live transfer was initiated.

## Continuation

- Remaining limitations or blocked operations: 06A has not been walked in a
  live browser or accepted by the owner. Model self-service payout editing,
  model payment history/receipt navigation, destination-change reauthentication
  and receipt context after a later account change remain 06B. Home/ranking
  amount evidence remains 07B.
- Decisions recorded or newly discovered: no new product decision. D04 remains
  closed (recovery before guarantee); D09 remains open. Reopening remains
  retired, approval remains the exact reviewed figure, and the existing ledger
  remains authoritative.
- STATUS.md and coverage/check rows updated: yes — `STATUS.md`,
  `BACKEND_CONTRACTS.md`, `ACCEPTANCE_CHECKS.csv`,
  `SCREEN_AND_ACTION_MAP.csv`, `CLAUDE.md` and the continuation handoff.
- Exact next phase/batch and prompt: **06B — Model payment views and destination
  changes**, from `docs/redesign/prompts/06_PAYMENTS.md`. Do not redo 06A.
- Any live deployment/data changes (normally none): none. No merge, push,
  deployment, live data edit or external transfer.
