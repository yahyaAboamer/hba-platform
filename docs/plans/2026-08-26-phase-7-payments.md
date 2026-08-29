# Phase 7 — The payment ledger, proof, allocations, credits and write-offs

**Spec:** `docs/specs/2026-08-22-hba-platform-v1-design.md` §14, §8, §11.1, §11.5, §6.4, §17
**ADRs:** 0017 (payment proof visible to affiliates), 0002 (integer piastres)
**Depends on:** Phase 6 (an obligation to pay against)
**Delivers:** the record that money actually moved — and closes V1A.

---

## What this phase is for

Phase 6 produced an **obligation**: a frozen figure somebody agreed. This phase records
**settlement** — that the money left HBA and reached them.

They are separate on purpose (§11.1), and keeping them separate is what the old dashboard
got wrong. One column conflating them produced the awkward *"Approved · Partially paid"*, and
a stored settlement state that disagrees with the payments it was computed from.

> `balance_due = approved obligation − Σ allocations − Σ credits and write-offs`

**Derived, every time, never stored.** A number that is recomputed cannot go stale.

### The rule the whole phase turns on

§14, first line: **The Pay button changes nothing.**

It opens InstaPay with the address filled in and alters no state. The maintainer sends the
money by hand, screenshots the confirmation, and *then* records it. **The platform must never
record a payment that may not have happened** — a button that both opens a payment app and
marks a debt settled will eventually mark one settled that failed.

---

## Three entities, because one transfer is not one month

§8. The old system could not represent this and it is ordinary at HBA:

```
payment_transaction   money that actually moved
payment_allocation    how that money is applied to months
payroll_adjustment    credits, write-offs, corrections
```

A single E£10,000 InstaPay transfer allocates E£7,000 to August and E£3,000 to September
**without pretending two transfers occurred.** The reverse is equally ordinary: InstaPay
limits force a split, and two transfers may settle one month.

**All three are append-only** (§17). A payment that can be edited is a payment nobody can
reconcile against a bank statement.

---

## Task list

| # | Task | Delivers |
|---|---|---|
| 1 | `payment_transaction` | Money that moved, append-only, with its destination frozen |
| 2 | `payment_allocation` | Applying it to months, never exceeding what was sent |
| 3 | Settlement | `balance_due` derived, and the four states that follow |
| 4 | Proof | Upload, EXIF stripped, served only to its owner |
| 5 | `payroll_adjustment` | Credits and write-offs, for when re-approval went the other way |
| 6 | The payments API | Record, allocate, adjust, and see what is outstanding |

---

## Task 1: `payment_transaction`

**Files:** create `app/models/payments.py`; migration; tests

`affiliate_id`, `amount_piastres`, `occurred_at`, `destination_snapshot_json`,
`proof_file_id`, `reference`, `note`, `created_by`, `created_at`.

**`amount_piastres > 0`**, enforced (§17). A payment of zero is not a payment, and a negative
one is an adjustment wearing the wrong hat — Task 5 has the right hat.

**`destination_snapshot_json` freezes where the money went**, masked (§6.4.4). Not a foreign
key to `payout_destination`: that table is append-only precisely so a past payment can
resolve the destination in force at the time, and copying the masked values means the record
still reads correctly if the row is ever superseded twice over.

**Never the raw destination.** `mask_destination` is the only sanctioned representation
outside the owner's own screen, and a payment record is not that screen.

**Append-only, by trigger.** Reused from Phase 1's `reject_mutation()`.

**Tests:** zero and negative refused; the destination is masked and frozen; the row cannot be
updated or deleted; a payment survives its destination being superseded.

---

## Task 2: `payment_allocation`

**Files:** modify `app/models/payments.py`; migration; tests

`payment_transaction_id`, `payroll_snapshot_id`, `allocated_piastres`, `created_at`.

**Allocations point at a *snapshot*, not a month.** §11.5 requires that payments made against
a superseded version remain intact and visible after a reopen — which is only expressible if
the allocation names the version it settled.

**The sum of allocations may never exceed the transaction** (§17). Enforced in the database,
because "we allocated E£12,000 of a E£10,000 transfer" is a sentence that should be
impossible rather than caught in review.

**Under-allocating is allowed.** A transfer may arrive before anyone has decided which months
it covers, and forcing a split at the moment of recording would invent an answer.

**Tests:** over-allocation refused at the database; partial allocation allowed; one transfer
across two months; allocations survive a reopen of one of them.

---

## Task 3: Settlement

**Files:** create `app/services/payments.py`; tests

```
balance_due(db, affiliate, month) -> int
settlement_state(db, affiliate, month) -> str
```

§11.1's four states, **derived from the ledger every time**: `unpaid`, `partially_paid`,
`settled`, `overpaid`.

**Nothing is stored.** The moment settlement is a column, it disagrees with the payments it
came from — and the disagreement is invisible, because the column looks authoritative.

**A reopened month has no active snapshot**, so its balance is unanswerable rather than zero.
Reporting zero would say *"nothing outstanding"* about a month with real money paid against a
superseded version. Recorded in `docs/limits.md` from Phase 6 and answered here.

**Tests:** each of the four states; a month with two transfers; one transfer across two
months; a reopened month reports unanswerable rather than settled; rounding never produces a
one-piastre balance that can never be cleared.

---

## Task 4: Proof

**Files:** create `app/services/proof.py`; storage; tests

§14, and **ADR 0017 is a decision to re-read before touching this.** The screenshot is shown
to the affiliate, because visible proof removes an entire category of *"did you send it?"*
messages. An external review noted it may expose HBA's sender name, account details,
transaction identifiers or balance to about twenty external people. **The business accepted
that knowingly.**

Mitigations applied regardless, and they are not optional:

- **EXIF stripped on upload** — a screenshot can carry location and device
- **Compressed, and a hard size cap**
- **Served only to the affiliate it belongs to**, checked per request rather than by an
  unguessable URL

**Storage:** ~20 models × 12 months × ~200 KB ≈ **50 MB/year**.

**Where the file lives is an open decision.** The database is simplest and keeps backups
coherent; object storage is cheaper and keeps the database small. At 50 MB/year the argument
for object storage is weak and the argument against an extra service is strong (ADR 0019) —
but this needs measuring rather than asserting, and it gets its own ADR.

**Tests:** EXIF is gone after upload; an oversized file is refused; a model cannot fetch
another model's proof; a payment with no proof is allowed, because a bank transfer with a
reference number is still a payment.

---

## Task 5: `payroll_adjustment`

**Files:** modify `app/models/payments.py`; migration; tests

`type` (`credit` | `writeoff` | `correction`), `source_payroll_month_id`,
`destination_payroll_month_id`, `amount_piastres`, `reason`, `created_by`.

This is where Phase 6's unfinished sentence ends. §11.5 says re-approval may find a model
**overpaid**, and that *the maintainer chooses* a credit applied to a later month or a
write-off. Phase 6 reports the difference and returns `resolution: None`; this is what fills
it in.

**A reason is required on every one.** An adjustment is money moving without a transfer, and
the only thing that makes it auditable is why.

**Both audited and visible to the affiliate** (§11.5). A credit they cannot see is a credit they
cannot check.

**Tests:** a credit reduces a later month's balance; a write-off clears the source month
without touching a later one; a reason is required; adjustments are append-only.

---

## Task 6: The payments API

**Files:** create `app/api/payments.py`; tests

```
GET  /api/payments/{month}                      what is outstanding, per model
POST /api/payments                              record a transfer, with allocations
POST /api/payments/{id}/proof                   attach the screenshot
GET  /api/payments/{id}/proof                   owner or maintainer only
POST /api/adjustments                           a credit or a write-off
GET  /api/affiliates/{id}/payments              their history
```

**The amount is pre-filled with `balance_due` and editable** (§14). Partial payments,
InstaPay limits forcing a split, one transfer covering two months, transfer fees, and
mistakes where the record must show the truth.

**Any amount differing from `balance_due` requires a short note.** Not a warning — the note is
the difference between a deliberate partial payment and a typo, and only the person recording
it knows which.

**`payments.record` gates writing.** Reading their own history is Phase 9's affiliate portal;
this phase builds the maintainer's side.

**Tests:** a differing amount without a note is refused; over-allocation is refused with the
figures named; proof is refused to another model; recording is refused to an affiliate.

---

## Deliberately not in this phase

- **The Pay button and InstaPay deep-linking.** §13.1 marks deep-link behaviour as an
  *implementation discovery item* — it must be tested on Android and iPhone, with and without
  the app installed, before anything is built around it. It is also interface work, and
  screens come after this phase.
- **Emailing the receipt.** §14 step 4. `notification_outbox` exists from Phase 2 and is
  written transactionally with the payment; sending is Phase 10.
- **The affiliate seeing any of it.** Phase 9.

---

## Risks

**Recording a payment that did not happen.** The reason the Pay button changes nothing.
Everything here is a record of something a person did outside the platform, and it must stay
that way.

**Proof leaking HBA's banking details.** Accepted knowingly (ADR 0017), mitigated
unconditionally. The mitigations are the part that must not be quietly dropped as
inconvenient.

**Allocation arithmetic disagreeing with itself.** Prevented structurally: allocations sum
against the transaction in the database, and `balance_due` is derived rather than stored, so
there is no second number to disagree with.

**This closes V1A.** The gate is *"run one full month of real payroll and verify it against
manual calculation"* — which needs screens, and screens come next.
