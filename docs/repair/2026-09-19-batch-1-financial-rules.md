# Batch 1 — financial rules and correction accounting

**Findings closed:** A01, A03, A04, A05, A07.
**Rules applied:** F02, F07, F09, F10, F11, F12, F13, and D04.
**Branch:** `repair/batch-1-financial-rules`, from `6a13958` — the commit the
audit names, rechecked before any edit: local `HEAD` and both remote `main`
and `production` were `6a139586864d1544dea1e92e04b004d505cba6a0`, so every
finding applied as written.

**Not deployed.** Nothing was pushed to `main` or `production`, and no
staging or production database was touched.

---

## What was wrong, and what it does now

### A01 — the agreed policy was a preview, not the live rule

`calculate_month` counted delivered orders only; the pending-inclusive rule
lived in `preview_calculation` behind `live_transition_not_enabled`. The
audit's probe reproduced the gap exactly: **E£10,000 of pending sales at 10%
paid E£0 live and E£1,000 in the preview.**

One rule now (F02): pending and delivered count, a failed delivery does not.
The reasoning and the transition plan are [ADR 0040](../adr/0040-a-pending-order-is-a-sale.md).

Three things keep it from paying twice, and each has a test:

- **approval settles every order it counted**, pending included, so the order
  carries a link naming the payroll that paid it;
- **`carried_into` pays only what an order's own month left out**, read from
  that month's frozen order list and the policy recorded beside it — under
  the old rule that is every order still travelling, under the new one none;
- **a closed month is recalculated under its own recorded rule**, so
  comparing a delivered-only agreement with a pending-inclusive recalculation
  can never report the policy change itself as a difference.

The carry-forward is therefore no longer a mechanism but a **backlog**: the
orders delivered-only approvals left unpaid. It is finite, identified from
each snapshot's own evidence, and never added to.

**Everything that says "sales" moved with it**, which A01 asks for in one
line and which is most of the surface area of this change:

| Where | Was | Is |
|---|---|---|
| Admin Home sales card and its year chart | delivered only | counted (delivered + pending) |
| Ranking board, and *selling models* | delivered only | counted |
| Product sales and a model's best sellers | delivered only | counted |
| The statement's *10% of X* line | delivered only | the sales the commission was actually a percentage of |

That last one is the defect with the sharpest edge and no test would have
caught it: the commission was computed on counted sales while the line above
it named the delivered total, so a statement containing a travelling order
**did not add up** — in front of the one person guaranteed to add it up. It
is computed from the same helper on both screens now, and an agreed month
uses its own recorded policy, so an old statement keeps saying exactly what
it always said.

### A03 — a second failure could disappear behind the first

`_resolution_for` asked *has anything been resolved for this month* and
treated any earlier credit as the answer. A month corrected, carried, and then
hit by a second failed order reported nothing at all.

A correction now carries four figures instead of one boolean: the
**cumulative shortfall**, what has been **resolved** so far, what is
**outstanding**, and what is **recoverable**. A later failure exposes only the
additional amount (F11), and a retry cannot deduct twice.

### A04 — an insufficient month refused the whole correction

Earning E£100 against a chosen E£200 deduction was refused outright — *"choose
a month with room, or absorb it"* — on the reasoning that a partial recovery
leaves a remainder nothing is tracking.

It applies E£100 now, records **no zero-value transfer**, and leaves E£100
outstanding against the source month for any later month, across years
(F12). The remainder is tracked because it is derived: the month's whole
difference, less everything already carried or absorbed.

Capacity also stopped waiting for approval. An overpayment found in early
October could only be carried into a month agreed in November, which left two
choices — write off money that should have carried, or remember to come back.
An unapproved month now offers what it is currently worth less anything
already landing on it, and the allocation is part of what that month's
approval agrees (F07).

### A05 — a failure before payment was not in the queue

`open_corrections` filtered on recoverable money, so an order failing between
approval and payment produced an empty queue: approved E£2,000, revised
E£1,800, nothing recorded as sent, **nothing said to anybody**.

*Needs review* and *money recoverable* are separate now. The queue is keyed on
the outstanding difference; `recoverable_piastres` says how much of it is
money, and `review_reason: "no_transfer_recorded"` says why it is not. No
recoverable debt is invented for money that never moved — attempting to
recover from such a month is refused with what to do instead: record the
transfer that was actually made, or leave the agreed figure to be paid in
full.

### A07 — the sales graph was frozen with the money

`my_month` read an approved month's sales from the snapshot and `my_year`
built its chart from those, so a later failure left no trace on the screens a
model reads.

Her **money** still comes from the snapshot — the total, the breakdown, every
carried line. Her **sales and order counts** come from the month as it is now
(F13). A parcel refused in November corrects September's sales and September's
point on the chart, and does not touch what September was agreed at.

---

## Evidence

### The audit's own probes, re-pointed

`docs/repair/batch-1/probe_after.py` runs the audit's four scenarios with the
same mocking and the same figures, asserting the repaired behaviour;
`probe-after-results.json` is its output. Side by side with the supplied
`financial-probe-results.json`:

| Scenario | Audited | Now |
|---|---|---|
| E£10,000 pending at 10% | live E£0 vs preview E£1,000 | **E£1,000 both**, and E£0 when recalculated under a delivered-only agreement |
| Second failure after a credit | `resolved: true`, 0 open | shortfall E£300, resolved E£100, **outstanding E£200**, 1 open |
| Failure after approval, nothing sent | difference −E£200, **0 open** | recoverable E£0, `needs_review`, **1 open** |
| E£200 deduction, E£100 available | refused | **applies E£100**, retains E£100, no zero transfer |

The supplied probe now fails at its first assertion, which is the point: it
asserts the defects.

### Tests

Backend, against the disposable docker-compose PostgreSQL on `127.0.0.1:5433`
(`hba_platform_test`) — never staging, production or an inherited URL:

```
DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform_test' \
  .venv/Scripts/python.exe -m pytest -q --color=no -p no:cacheprovider
```

**How it had to be run, and what that limits.** This machine had **0.23 GB
free of 7.87 GB** while the work was done — Docker alone holds about 1.2 GB —
and the suite was killed for memory in groups of five and again in groups of
three. It finished as one file per process, with each result recorded so a
kill costs one file rather than the run. `CLAUDE.md` now carries that method.

**Result: 1,960 collected, 1,960 passed, 0 failed, across all 76 files.**
Recorded per file in `docs/repair/batch-1/test-log.txt`, where the total
reconciles exactly with what `--collect-only` reports for this tree.

Four files reported *errors* rather than failures on their first run —
`test_commission_base`, `test_migrations`, `test_reconcile`, `test_payments`
— and each passed on re-run after clearing the connection. That is the
stale-backend deadlock `CLAUDE.md` describes, left behind by the memory
kills, and it is exactly the symptom that reads like a regression in whatever
you last changed. The log says which lines were re-runs.

Of note in the batch's own files: `test_payments_api.py` **41**,
`test_payroll_lifecycle.py` **48**, `test_portal_api.py` **89**,
`test_corrections.py` **30**, `test_financial_transition.py` **12**,
`test_financial_rules_preview.py` **22**, `test_overview.py` **30**,
`test_performance.py` **36**.

New: `tests/test_financial_transition.py` — the live policy, the snapshot
policy record, delivery after approval paying nothing again, the backlog only
shrinking, a legacy carried order never paid twice, and the portal's sales and
chart moving while the agreed figure does not.

Extended: `tests/test_corrections.py` — a second failure exposing only the new
difference; a partial carry and its remainder; the remainder settled in a
later **year**; a month with no room refused rather than settled for nothing;
a deduction accepted against an unapproved month; a duplicate submission
refused; an unpaid month reviewed but not recoverable.

Extended: `tests/test_payments_api.py` — the same two over HTTP, including
**409 on a repeated submission** and exactly one recovery standing afterwards.

Superseded expectations corrected rather than deleted, each with the reasoning
written into the test: delivered-only settlement marking (`test_payroll.py`),
the preview/live split (`test_financial_rules_preview.py`,
`test_earnings_api.py`), the all-or-nothing refusal and the empty queue
(`test_corrections.py`).

Frontend: `npx tsc --noEmit` clean, `npm test` **321 passed**, build passes.

### Migration: none, and that is deliberate

**No schema change and no data rewritten.** The policy a month was agreed
under is recorded inside the snapshot payload that already exists, and its
*absence* is the marker for every month agreed before the switch — so nothing
has to be backfilled, and no approved month is touched to make the new code
work. Rolling back is redeploying the previous build: months approved in
between carry a `policy` key the old code ignores, and the old code's
delivered-only carry would resume from the same frozen evidence.

The one visible consequence of a rollback is that months approved under the
new rule would have counted pending orders the old rule would then try to
carry again — which `settled_in_snapshot_id` already prevents, because
approval marked them. That is the reason the marking was made structural
rather than left to the payload.

### Reconciliation dry run

`docs/repair/batch-1/reconcile.py` reads a database and reports: how many
agreed months are legacy, what is in the carry backlog and what it is worth,
any order counted in its own month *and* settled elsewhere (expected: none),
and which agreed months would now show an open difference. It opens a
transaction, writes nothing and rolls back. **It has not been run against
staging or production data** — that is a release-gate step and needs a
restored copy and the owner's say-so.

### Immutability

Verified incidentally and then deliberately: the first attempt at a legacy
test fixture tried to edit a snapshot's payload and PostgreSQL refused it —
`append-only table: payroll_snapshot cannot be modified by update`. The
fixture reaches for the code path instead (`tests/support_policy.py`), and no
approved snapshot, allocation or transfer is rewritten anywhere in this batch.

---

## Screens touched, and why they had to be

The audit sequences UI work into Batches 2 and 3, and this batch deliberately
kept out of that — with one exception. The corrections queue is the direct
interface of everything above, and leaving it would have meant a screen
showing **E£0.00 beside a button that refuses**: a dead control, which the
owner's standing brief rules out.

So `Corrections.tsx`, `Payments.tsx` and `PaymentCorrection.tsx` now show the
outstanding difference rather than the recoverable amount, say when part of a
month has already been settled, say plainly when nothing was sent and
therefore nothing can be recovered, and send the figure they displayed so a
retry is refused. No layout or design work was done on them; that is Batch 3.

## Remaining risks and what is deliberately still open

- **The statement and the sales card can now differ for an agreed month**, and
  correctly: the statement's *counted sales* line is what the agreed figure
  was computed from, the card shows what the month sold today. That needs a
  word on screen. Batch 2, with the rest of the portal wording (A12).
- **A deduction accepted against a draft month can exceed what that month is
  finally approved at.** Capacity is taken from the month's current
  calculation, which is what F07 and F12 ask for, and the month can be agreed
  lower. The money is not at risk — the correction is tracked against its
  *source* month, so nothing can be recovered twice — but that destination
  month's balance then reads as overpaid, which is accurate and easy to
  misread. Binding those figures deliberately is A02, in Batch 2; noting it
  here so it is not discovered there as a surprise.
- **D09 is untouched** — a delivery failure later found to be wrong, after a
  deduction has been used. Still open, as it was.
- **No integration run against real data.** The reconciliation dry run has
  been written and not pointed at anything but the test database.
- **A02, A06, A08, A09, A11, A12 are Batch 2** and unchanged here. A01's fix
  changes the figures A02 mis-binds; the mis-binding itself remains.
- **Nothing here is visually verified.** No screenshots were taken and no
  parity claim is made for the three screens touched.

## Exact next task

Batch 2, beginning with **A02**: bind forecast, approved total, recorded money
and remaining money separately in the Payments table, with rendered-row tests
using real API-shaped fixtures — including the forecast, unavailable,
approved, partial, paid and zero-transfer settlement cases. Then A06, A08,
A09, A11 and A12 as the continuation brief sequences them.
