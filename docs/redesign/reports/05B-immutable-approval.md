# Batch report — Phase 05B, immutable per-model approval

Date: 10 September 2026.

Branch and base/current commit: `phase05b/immutable-approval`, based on
`phase05a/pending-inclusive-earnings` @ `6f69bdd`. 05A is not merged to `main`
and is still awaiting its rendered review, so 05B builds on it rather than
around it.

Requested scope: **05B only.** Freeze source version, terms, target outcome,
earnings and payable; make concurrent approval and a stale preview safe;
disable the active reopen API and route while preserving read-only history; a
failure after approval and before transfer becomes a correction rather than an
automatic changed instruction.

Delivered behaviour: an agreement is now of **the figure that was shown**, and
an agreed month is no longer unmade.

---

## Review

### What was already immutable, and what was not

Approval was in better shape than the roadmap assumes. `ALREADY_APPROVED` is a
blocker, so a second approval was already refused; `payroll_snapshot` is
append-only behind a database trigger; `(payroll_month_id, version)` is unique;
and the payload already froze the terms, the target outcome, every order at its
approval value, and the policy wording in force.

Two things were not covered, and both are about **the gap between looking and
agreeing**.

### Agreeing a figure nobody was shown

Approving is where a working number becomes a debt. The screen previewed, the
operator read a total, pressed the button — and **the commit recalculated**,
freezing whatever was true at that instant. Between the two, a webhook can
settle an order, a delivery can fail, a target can be recorded, a rate can be
corrected.

Nobody would ever have found out. The screen said one number, the snapshot said
another, and nothing anywhere recorded that they differed.

The preview now hands out a **source version** — a short fingerprint of
everything the figure was computed from — and the commit hands it back. A
mismatch is refused rather than reconciled, because there is no correct guess
about which figure somebody meant. 04A reached the same conclusion about the
targets grid for the same reason.

**The fingerprint covers the evidence, not the total.** An order failing while
another delivers for the same amount leaves the payout untouched and changes
everything behind it — and on a guaranteed minimum the evidence is what decides
the money.

### Two people, one month, one version number

`ALREADY_APPROVED` is read a few lines before the snapshot is written, and the
other person can commit in between. The unique constraint caught that
correctly, and it arrived as an `IntegrityError` that **aborted the whole
transaction**: on a run approving twenty models, one collision took the other
nineteen with it.

The insert now sits in a savepoint, so the collision is answered for that model
alone and the rest of the run stands.

### Reopening is retired

Reopening was the only way to change an agreed figure, and it worked by
*unmaking the agreement*: the month went back to draft, the orders it had
settled were released, and the next approval wrote over the top. Everything
about that is recoverable except the one thing that matters — **money already
paid against the old figure**. The ledger kept the payment; the month it was
paid against no longer existed in the same form.

§11.5 named the danger itself: *the dangerous state is not reopening, it is
forgetting*. A month left reopened and never agreed again is a model with no
figure at all, which is why the platform needed a diagnostic to find them.

`POST /api/payroll/{month}/reopen` now answers **409**, and the button is gone
from the payroll screen. The route and its page are kept rather than deleted: a
404 says *you are lost*, and a retired capability should say what replaced it.
**Everything that reads reopened history still works** — the diagnostic, the
payments warnings, the reconciliation screen, and the months that were already
reopened, which are still real and still need agreeing again.

### A failure after approval changes nothing, and stops being invisible

§11.1: money owed under an agreement is owed until somebody decides otherwise.
So an order refused after approval moves nothing — not the agreed figure, not
the settled link, not what the payments screen offers to send.

What it does now is **say so**. The payroll row carries
`source_changed_since_approval`, computed by comparing the frozen fingerprint to
the current one. Deciding what to do about it is a correction, which is 05C;
this is what stops it being invisible until then. The old answer was that nobody
found out at all.

### Preview and relevant screenshots

**None.** Browser automation cannot sign in to this platform, and 05A's attempt
to correct that diagnosis ended blocked before any rendered review. Nothing in
this batch has been seen.

### What the owner should try

1. **Payroll → choose a model → review → agree.** Unchanged, and it now carries
   the figure it showed you.
2. **Open payroll in two tabs. Agree in one, then agree in the other.** The
   second is refused for that model and says the month changed while you were
   looking at it — not that anything is wrong with it.
3. **Agree a month, then mark one of its orders failed.** The agreed figure,
   the version and what is owed do not move. The row says the evidence behind
   the agreement has changed.
4. **Payroll → the reopen button is gone.** The page it pointed at still opens
   from a bookmark and explains what replaced it.

### Approved-design deviations and reason

**One, and it is a removal.** The approved design has a reopen flow; 05B
retires it, because the batch prompt asks for exactly that and because 05C
replaces it with corrections. The screen is not deleted — it explains.

### Confirmation needed before the next dependent decision

**One thing to know rather than answer.** Between this batch and 05C there is
**no way to change an agreed month at all**. Reopen is gone and corrections are
not built. Nothing real is exposed to that — no model is onboarded, and neither
05A nor 05B is on `production` — but if a wrong figure has to be fixed on
staging before 05C lands, say so and it can be done through the service with
its audit trail intact.

---

## Engineering evidence

### Files, services and API contracts changed

| File | Change |
|---|---|
| `app/services/payroll.py` | `source_version`, `SourceMoved`, the `expected_source_version` guard, the savepoint around the snapshot insert, the fingerprint frozen into the payload, and `reopen_month` documented as unreachable |
| `app/api/payroll.py` | `source_versions` on `ApproveBody` and refused when absent on a commit; per-model stale outcome; `source_changed_since_approval` on the month row; the reopen route retired to 409 |
| `frontend/src/screens/PayrollApprove.tsx` | Sends back what the preview handed out; reports a stale model separately from a blocked one |
| `frontend/src/screens/PayrollReopen.tsx` | Rewritten as the explanation of what replaced it |
| `frontend/src/screens/Payroll.tsx`, `Payroll.css` | The reopen button removed; the retired page styled as prose |
| `frontend/src/lib/money.ts` | A phrase for `source_changed_since_preview` |
| `tests/test_reachability.py` | The retired route recorded as deliberately unreached, with the reason |
| `tests/test_payroll.py` | 6 new |
| `tests/test_payroll_lifecycle.py` | 6 new; the reopen tests rewritten against the retirement |
| `tests/test_portal_api.py`, `test_payments_api.py`, `test_affiliates_api.py`, `test_browser_journey.py` | Their approve helpers preview first and agree what the preview said |

### Schema, migration and compatibility

**No migration.** Head unchanged at `a2f47b8e1c53` (35 revisions). The
fingerprint is derived, never stored — the same reasoning as 04A's grid
revision: a column would need writing on every path that touches an order and
would be wrong the first time somebody forgot.

**Snapshots written before this batch have no `source_version` in their
payload**, and are handled rather than migrated: `source_changed_since_approval`
is `false` when the key is absent, because *we cannot tell* must not render as
*something moved*. Backfilling it would mean recomputing months that are closed.

A rollback needs no data work. `source_versions` is additive on the request and
ignored by an older server.

### Authorisation, idempotency and money

**No new route, no new permission, no new write.** `PAYROLL_REOPEN` is
untouched, so the permission map and its audit history still read.

**No money is computed differently.** `calculate_month` is not changed by this
batch; the fingerprint is a hash of its inputs and its result is unchanged.
Every figure still comes from the frozen snapshot.

**The refusals write nothing.** Asserted directly: a stale commit, an absent
fingerprint and a refused reopen each leave the month exactly as it was.

### Existing failures distinguished from regressions

**44 tests failed mid-batch and every one was the new guard working** — HTTP
tests that agreed a month without carrying what the preview showed. Each was
updated to preview first, which is what the screen does, so they keep testing
behaviour rather than the calling convention. Two reopen tests were rewritten
against the retirement, and one now constructs its reopened month through the
service, because that state still exists and still has to read correctly.

**No test was skipped, weakened or marked expected-to-fail.**

### Two mistakes made during this batch, recorded because they cost real time

**pytest was run against the dev database.** There is no pytest configuration
setting `DATABASE_URL`, and unset it falls through to `app/config.py`'s default
— which is `hba_platform`, the dev database. `conftest.py`'s `fresh_database`
truncates every table after each committing test, so the dev data was emptied.
The tests all passed throughout, because the suite builds its own rows; nothing
said anything was wrong. Staging and production are separate Railway databases
and were never touched. `CLAUDE.md` now carries the exact command.

**Two pytest processes ran at once.** A targeted run was started while the full
suite was still running in the background, against the same database. They
deadlocked and leaked committed rows into each other, and the resulting
failures looked precisely like a regression in the code under test. `CLAUDE.md`
already said one at a time; it now says why it matters and what it looks like
when ignored.

### No real credentials or personal data in evidence

Nothing here reads or renders a name, address, phone number or email. Every
fixture is synthetic and no credential, token or real person's detail appears in
this report.

### Exact commands, actual results and environment

Windows, Git Bash, `.venv/Scripts/python.exe`, local PostgreSQL on 5433,
migration head `a2f47b8e1c53`. No CI; every check below was run locally, one
process at a time.

```
DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform_test' \
  .venv/Scripts/python.exe -m pytest -q --color=no -p no:cacheprovider
```

| Check | Actual result |
|---|---|
| Full backend suite | **1780 passed in 463.81s**, exit 0 — 1769 on the 05A branch, **11 new** |
| The four API files most affected, run together | **220 passed in 226.33s**, exit 0 |
| `cd frontend && npx tsc --noEmit` | exit 0 |
| `cd frontend && npm test` | **233 passed**, exit 0 |
| `cd frontend && npm run build` | exit 0 |
| `tests/test_reachability.py` | Passes with the retired route recorded and its reason written down |

### Visual comparison — not performed

Nothing in this batch has been rendered in front of anybody. The approve screen
gained a stale-model notice and the reopen page was replaced outright, and
neither has been seen.

---

## Continuation

### Remaining limitations and blocked operations

- **There is no way to change an agreed month between this batch and 05C.**
  Reopen is retired and corrections are not built. Contained — nothing real is
  exposed — but it is a real gap and 05C closes it.
- **A stale commit is caught, not prevented.** Nothing tells you a colleague is
  looking at the same month until you press the button. The right trade for two
  people; it would not be for twenty.
- **`reopen_month` still exists as a service function**, reachable from a shell
  by somebody who ignores its docstring. It is kept because the reopened months
  that already exist still have to be constructible in tests, and because a
  future repair of an old month may need it.
- **Old snapshots cannot answer whether their source moved.** They predate the
  fingerprint, and the answer is *unknown*, reported as `false`.

### Decisions recorded or newly discovered

**None new.** D02 is untouched: whole-pound half-up rounding is preserved, as
05A left it, and no owner answer is recorded.

### STATUS.md and coverage rows updated

`docs/redesign/STATUS.md`, `docs/redesign/ACCEPTANCE_CHECKS.csv` (AC34, AC35,
AC42) and `CLAUDE.md`.

### Exact next batch and prompt

**Phase 05C — persistent late-failure review and allocation.**
Prompt: `docs/redesign/prompts/05_FINANCIAL_RULES.md`, **05C only**.

It inherits `source_changed_since_approval` and the frozen `source_version`
directly: those are how a month announces that it needs a correction, and they
should not be re-derived. D04 and D09 govern the correction decisions
themselves and are still open.

### Live deployment or data changes

**None.** No deployment, no branch promoted, no financial data touched. The dev
database was emptied by the test-database mistake recorded above; it holds
synthetic seed data and `scripts/seed_demo.py` regenerates it.
