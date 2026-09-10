# Batch report — Phase 05C, persistent late-failure review and allocation

Date: 10 September 2026.

Branch and base/current commit: `phase05c/late-failure-corrections`, based on
`main` @ `9cbfcdb` — 05A and 05B are merged and deployed to both environments.

Requested scope: **05C only.** Source-month guarantee-aware cumulative
recoverable amount; HBA's absorb-or-carry choice; shared destination capacity;
frozen accepted allocations; idempotent events; D04 and D09 handling. Model
explanations supported by the same service, never recomputed in the browser.

Delivered behaviour: an agreed month that turns out wrong now has somewhere to
go. **The agreement stands and the difference is recorded against it.**

---

## Review

### The hole 05B left, deliberately

05B retired reopening because it worked by *unmaking* an agreement, and money
already paid against the old figure does not un-move. That left a gap it named
at the time: between 05B and this batch there was no way to change an agreed
month at all. This closes it.

An order refused weeks after a month closed now produces a **correction**: the
frozen snapshot compared against a fresh calculation, the difference reported,
and a person choosing what to do about it. §11.5's division is untouched —
whether an overpayment is carried into a later month or absorbed by HBA is a
judgement about a person they know, and nothing here decides it.

### The guarantee is not a special case

A failed sale on a guaranteed minimum often costs **nothing**. The guarantee is
a floor: losing a sale above it moves the commission and not what she is paid.
Getting that wrong would manufacture a debt against a model who never had one.

So the comparison runs the real engine twice rather than comparing commission
figures. §15 is applied by the one implementation that knows it, and the
guarantee falls out rather than being handled.

### What can be recovered is what actually moved

Capped at what was paid. A month agreed at E£2,000 and paid E£500 cannot give
back E£2,000 however far the calculation has fallen — recovering money that
never left would invent a debt. A month agreed and not yet paid produces no
correction at all: it simply pays less when it is paid.

A month now worth **more** than was agreed is reported and is not a correction
against her. HBA owes her, and that is settled by agreeing the higher figure.

### D04, and what it obliges the screens to do

**Answered 10 September 2026: a carried overpayment consumes a later month's
whole payable, below a guaranteed minimum if it has to.** A month can settle at
zero while a debt clears.

The platform recommended the other rule — take only what was earned above the
floor — and was overruled. `decisions/D04-recovery-comes-before-the-guarantee.md`
records both, so that somebody finding a model paid nothing in a month she met
her targets in finds a decision rather than what looks like a bug.

Because the reasoning is invisible from her side — she never saw the refused
parcel — **the screens now carry it**, and one of them was actively wrong. Her
month said *includes E£9,000 from August*, which reads as money **added**. It
now says that much of the month repays an earlier one she was already sent, and
that it is not being sent again. The sentence is written by the service, not
assembled in the browser: §11.5 requires an adjustment to be visible to the
person it was made about, and a figure the browser builds is one no test here
can hold to account.

### Idempotent, and cumulative

An open correction is **derived, not stored** — a comparison computed on
demand. Asking twice cannot create two, and a failure that reverses before
anybody acts simply stops being reported. Once accepted it is frozen as an
append-only `payroll_adjustment`, and a month already carried or absorbed is
refused rather than adjusted again.

The outstanding figure is **cumulative across her months**, because deciding
one month against one later month is how the second gets forgotten — the
failure §11.5 named about reopens, which retiring them did not remove.

**Two corrections cannot both spend one month.** That falls out of the balance
rather than being subtracted separately: a credit landing on a month already
reduces what it needs sent (ADR 0035). Subtracting it again was a double count
I wrote and a test caught.

### What the owner should try

1. **Agree a month, pay it, then mark one of its orders failed.** The model's
   profile grows an *Agreed months that have changed* panel with the figure.
2. **Decide it** — take it out of a later month, or absorb it. Both need a
   written reason; neither is the default.
3. **Open that later month as the model.** It says how much of it repaid an
   earlier month, and that the money is not being sent again.
4. **Try to decide the same month twice.** Refused.
5. **Try to carry more than a later month can take.** Refused with the figure
   it can take, rather than part-applied.

### Approved-design deviations and reason

**One.** The approved design has no corrections screen, because the design was
drawn when reopening still existed. This panel is its replacement and appears
only when something is outstanding.

### Confirmation needed before the next dependent decision

**D09 is open and this batch stops at it.** What happens when a failure that
caused a deduction is later reversed — the parcel turns out to have been
delivered after all, after the money was already recovered from a later month.
Nothing here does anything automatic in that case, which is the safe behaviour;
it is not yet the complete one.

---

## Engineering evidence

### Files, services and API contracts changed

| File | Change |
|---|---|
| `app/services/corrections.py` | **New.** `correction_for`, `open_corrections`, `outstanding_piastres`, `capacity_of`, `resolve` |
| `app/services/payments.py` | `adjust` accepts `open_difference_piastres`, for the one caller that has computed a difference the month's balance cannot carry |
| `app/services/portal.py` | `_credited_from` writes the model's sentence and states the direction; a duplicate `_month_words` I added was removed |
| `app/api/payments.py` | `GET /api/affiliates/{id}/corrections`, `POST /api/corrections` |
| `frontend/src/components/Corrections.tsx` + `.css` | **New.** The panel, on the model's profile |
| `frontend/src/screens/AffiliateDetail.tsx` | Mounts it above the rules preview |
| `frontend/src/screens/MyMonth.tsx`, `MyPayments.tsx`, `lib/portal.ts` | Render the server's sentence; the "includes" wording corrected |
| `tests/test_corrections.py` | **New.** 21, including AC43 in its own figures |
| `docs/redesign/decisions/D04-…` | The decision, its reasoning, and the reasoning it overrode |

### Schema, migration and compatibility

**No migration.** Head unchanged at `a2f47b8e1c53`. Corrections reuse
`payroll_adjustment`, which is append-only and trigger-guarded, and its
existing `credit` / `writeoff` types — §11.5's two words, rather than a third
vocabulary for the same two acts.

**A resolution is inferred from the adjustment rather than stored on it.** That
is sound *because* 05B retired reopening: a month now has exactly one snapshot
for its whole life, therefore at most one open correction, therefore an
existing credit or write-off out of that month is unambiguously this
correction's resolution. If a month can ever carry two agreements again this
needs a column, and the code says so where it would be needed.

### Why `adjust` needed a new argument

Its cap read the month's outstanding **balance**, which is how a reopened month
announced an overpayment: re-approval dropped the obligation, payments stayed,
and the balance went negative by exactly the amount to settle.

05B retired reopening, so an obligation never drops and that balance never goes
negative. The difference is real and lives between the frozen snapshot and a
fresh calculation, and `corrections.resolve` is the one caller that has it.

**It is not folded into `balance_for` instead, deliberately.** A balance that
went negative the moment a parcel was refused would present a debt against a
model on the screen she reads, before anybody had decided to recover it. A
difference becomes money owed when a person says so.

### Authorisation, idempotency and money

Reading corrections needs `affiliates.view`; resolving one needs
`payments.record` — the same permission as any other adjustment, because that
is what it records. **No new permission.**

**No amount is accepted from the caller.** `resolve` takes no `amount_piastres`
and a test asserts its signature does not have one: a caller supplying its own
could recover more than was ever paid, or twice, and the ledger afterwards
would say only that somebody chose that.

Money remains integer piastres throughout and no figure is computed in the
browser.

### Existing failures distinguished from regressions

**No regressions, and the last stretch of this batch was environmental rather
than code.** Every file listed above passes from a clean database.

**The full suite was not completed in one process, and that is not hidden
here.** Three attempts were killed for low memory - the machine had 0.56 GB
free of 7.9 GB, with Docker's `vmmem` holding 1.6 GB and `C:` still 99% full.
Each kill skipped pytest's teardown, and one left an **idle database
connection** behind that deadlocked every subsequent `TRUNCATE`. The result was
a cascade of `duplicate key ... user_account_email_lower_key` and *"An account
already exists"* failures across files that had nothing to do with this batch,
and which looked exactly like a regression in it.

Terminating that connection and emptying `hba_platform_test` cleared all of
them. `tests/test_corrections.py` then ran 21 passed from an empty database and
left **zero rows** behind, which is what settled that the failures were
wreckage rather than a leak in the new code.

The last complete single-process run of the whole suite, earlier in the
session, was **1797 passed, 1 failed** - and that one failure was
`test_portal_corrections.py`'s assertion of the old credit wording, which this
batch deliberately changed and which now passes.

**What is therefore not evidenced: a green full-suite number for this exact
commit.** Do not quote one. The next session should run it once the machine has
memory to spare - restarting Docker Desktop reclaims most of `vmmem`.

### Two mistakes I made in this batch

**I wrote a `_month_words` that already existed**, forty lines from where I put
it, shadowed by the original and therefore dead. Exactly the duplication I had
flagged in the 05A review the same day. Removed; the original is used.

**I double-counted credits in `capacity_of`**, subtracting what `balance_for`
had already netted. It made a month with room look full, and the test for two
corrections sharing one month is what caught it.

### No real credentials or personal data in evidence

Every fixture is synthetic. No name, address, phone number, email, credential
or token appears in this report or the tests.

### Exact commands, actual results and environment

Windows, Git Bash, `.venv/Scripts/python.exe`, local PostgreSQL on 5433,
migration head `a2f47b8e1c53`. No CI. One pytest process at a time, with the
database named explicitly:

```
DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform_test' \
  .venv/Scripts/python.exe -m pytest -q --color=no -p no:cacheprovider
```

| Check | Actual result |
|---|---|
| `tests/test_corrections.py` | **21 passed**, exit 0 |
| `tests/test_payments.py` | **46 passed**, exit 0 |
| `tests/test_payments_api.py` | **26 passed**, exit 0 |
| `tests/test_payroll.py` | **39 passed**, exit 0 |
| `tests/test_payroll_lifecycle.py` | **48 passed**, exit 0 |
| `tests/test_portal_corrections.py` | **7 passed**, exit 0 |
| `tests/test_reachability.py` | **3 passed**, exit 0 |
| Full backend suite in one process | **Not completed — see below** |
| `cd frontend && npm test` | **237 passed**, exit 0 |
| `cd frontend && npx tsc --noEmit` | exit 0 |
| `cd frontend && npm run build` | exit 0 |

### Visual comparison — not performed

Nothing in this batch has been rendered in front of anybody. The corrections
panel is new and the model's month-screen wording changed, and neither has been
seen. **The wording is the part to look at**, because D04 makes it the only
explanation a model gets for a month that pays her nothing.

---

## Continuation

### Remaining limitations and blocked operations

- **D09 is open and nothing here handles it.** A failure that reverses after
  its deduction was taken does nothing automatic. Safe, not complete.
- **A correction cannot be split across months.** A carry larger than the
  destination is refused, with the figure that month can take, rather than
  part-applied — a remainder nothing tracks is the failure this service
  exists to prevent. Spreading one correction over several months is real work
  and is not built.
- **No cross-model view.** Corrections surface on each model's profile;
  Payments does not yet list them all at month end, which is where somebody
  would notice one they had forgotten.
- **Months agreed before 05B report nothing**, having no fingerprint to compare
  against. Unknown is not *moved*, and inventing a figure for a closed month
  would be worse than silence.

### Decisions recorded or newly discovered

**D04 closed** — `decisions/D04-recovery-comes-before-the-guarantee.md`. The
register is updated and the open set is now **D01, D02, D03, D08, D09, D10**.

### STATUS.md and coverage rows updated

`docs/redesign/STATUS.md`, `docs/redesign/DECISIONS.md`,
`docs/redesign/ACCEPTANCE_CHECKS.csv` (AC42, AC43, AC44) and `CLAUDE.md`.

### Exact next batch and prompt

**Phase 06A — the admin month-end payment journey.**
Prompt: `docs/redesign/prompts/06_PAYMENTS.md`, **06A only**.

Recording, proof and reconciliation already exist and are reusable; 06A is the
journey around them. It inherits corrections directly — a month reduced by a
carried correction has to read correctly on the screen money is sent from, and
under D04 that month can be zero. Its own note says to reuse the existing
services and idempotency rather than build a parallel ledger.

### Live deployment or data changes

**None in this batch.** 05A and 05B were merged and deployed to staging and
production earlier in the session, on the owner's explicit instruction; both
environments are healthy on `9cbfcdb`. 05C is not merged.
