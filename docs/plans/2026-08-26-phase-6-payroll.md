# Phase 6 — Payroll months, approval, snapshots, carry-forward, reopen

**Spec:** `docs/specs/2026-08-22-hba-platform-v1-design.md` §11 (all), §9.3, §9.4, §16, §17
**ADRs:** 0004 (half-up rounding), 0013 (on-demand payroll), 0014 (historical months),
0025 (delivery is final)
**Depends on:** Phase 4 (the calculation) and Phase 5 (the last blocker)
**Delivers:** the moment a figure stops being a calculation and becomes an obligation.

---

## What this phase is for

Everything so far recalculates. Ask what April is worth twice and you may get two answers,
because an order delivered in between changed it. That is correct while a month is open and
**intolerable once somebody has been paid.**

This phase draws the line. Approving a month freezes what was calculated, records who agreed
it, and stops it moving. Everything after that — a late delivery, a correction, a return —
lands somewhere visible instead of silently rewriting history.

It is also where the questions HBA raised about **what a model sees on a closed month** get
answered, because the answer needs a snapshot to point at.

### The distinction the whole phase rests on

§11.1. Two states, not one, because the old dashboard conflated them and produced the
awkward *"Approved · Partially paid"*.

**Calculation state** — has the amount been agreed?

| State | Meaning | Set by |
|---|---|---|
| `historical` | Before go-live; settled outside the platform | Configuration, once |
| `draft` | Live, recalculating | The system, when orders arrive |
| `approved` | Frozen; the obligation is fixed | **A person, deliberately** |

**Settlement** — has money moved? **Derived, never stored:**

```
balance_due = approved_obligation − Σ allocations − Σ credits and write-offs
```

Storing settlement would let it disagree with the payments it was computed from. Deriving it
means a reopened month is unambiguous: the calculation returns to `draft` while the platform
still knows exactly how much cash went out against the old snapshot.

**Only one transition is automatic** — the system creating a `draft` month. Every transition
that touches money is a human act.

---

## Task list

| # | Task | Delivers |
|---|---|---|
| 1 | `payroll_month` | One row per model per month, and the states |
| 2 | `payroll_snapshot` | The frozen calculation, versioned and append-only |
| 3 | Approval | Blockers refused, not warned; the snapshot written |
| 4 | Carry-forward | Orders that settle after approval, landing visibly |
| 5 | Reopen | The way back, with a reason and the old version kept |
| 6 | Historical months | Eight months of imported sales that are not owed |
| 7 | The payroll API | Run a month, see what blocks it, approve it |

---

## Task 1: `payroll_month`

**Files:** create `app/models/payroll.py`; migration; tests

`affiliate_id`, `month`, `calculation_state`, `active_snapshot_id`, `created_at`,
`updated_at`. **Exactly one row per affiliate per month** (§17), enforced.

**Settlement is not a column.** §11.1 is explicit, and this is the defect being fixed: a
stored settlement state disagrees with the ledger the moment an allocation is recorded and
nobody re-runs whatever was supposed to update it.

**`active_snapshot_id` points at the version in force**, so re-approving after a reopen moves
the pointer rather than overwriting anything.

**Created on demand, not on a schedule** (ADR 0013). A month exists because somebody asked
about it or an order arrived in it — twenty models times twelve months of empty rows is
storage that answers no question.

**Tests:** two rows for one month refused; the state transitions that are allowed and the
ones that are not; a month is created by asking for it.

---

## Task 2: `payroll_snapshot`

**Files:** modify `app/models/payroll.py`; migration; tests

`payroll_month_id`, `version`, `payload_json`, `content_hash`,
`approved_obligation_piastres`, `exact_unrounded_piastres`, `approved_by`, `approved_at`,
`reopened_by`, `reopened_at`, `reopen_reason`, `policy_version`.

**Append-only, enforced by trigger** (§17, ADR 0008) — `reject_mutation()` already exists and
is reused. A snapshot that can be edited is not a snapshot, and the audit trail would be
describing something that no longer holds.

**Versions unique and increasing per month** (§17). Re-approving a reopened month creates
version 2; version 1 is preserved with the payments that were made against it.

**`payload_json` holds the whole calculation** — every order, its base, the terms applied, the
target that unlocked a guarantee. Not a reference to them. **The point is that it survives
what happens next**: a code changing hands, a rate correction, a target being re-verified. A
snapshot storing ids would recompute to something different the day any of those changed.

**`content_hash` over the payload**, so "did this month's figures change?" is one comparison
rather than a diff nobody reads.

**Both money figures**, exact and rounded (§9.6, ADR 0004), because the audit has to show what
was calculated as well as what was agreed.

**Tests:** a snapshot cannot be updated or deleted; versions increment; the payload survives
the underlying data changing; the hash changes when the figures do and not when they do not.

---

## Task 3: Approval

**Files:** create `app/services/payroll.py`; tests

```
blockers_for(db, affiliate, month) -> list[str]
approve_month(db, affiliate, month, *, actor) -> PayrollSnapshot
```

**Blockers refuse, they do not warn** (§11.3). Everything Phase 4 and 5 already report, plus
the multi-code hold from §9.2:

| Situation | Approval |
|---|---|
| No compensation terms | 🚫 Blocked |
| `base_guarantee`, no target recorded | 🚫 Blocked |
| `base_guarantee`, achieved but unverified | 🚫 Blocked |
| An order on multi-code hold | 🚫 Blocked |
| Target recorded and missed | ✅ Allowed — the base does not apply |
| A house account | 🚫 Not approvable — never owed |

**Bulk approval shows every model, amount and blocker before committing** (§11.3). A bulk
action that reports failures afterwards is a bulk action nobody can trust.

**Approving is what closes a month to editing.** This is where `assert_correctable`
(compensation, Phase 3) and `assert_recordable` (targets, Phase 5) stop being seams and start
refusing — both are recorded in `docs/limits.md` as waiting for exactly this.

**Tests:** each blocker refuses; a missed target does not; approving twice is refused;
approval writes a snapshot and points the month at it; a bulk preview commits nothing.

---

## Task 4: Carry-forward

**Files:** modify `app/services/payroll.py`; tests

§11.4, and **the common path, not an edge case**: Egyptian cash-on-delivery routinely
straddles month end, so an order placed 29 August may still be travelling when payroll runs
on 5 September.

An order whose `business_month` is August but which was still `pending` when August was
approved appears in **September's** draft as a labelled line: *"Carried forward from August —
2 orders, E£840."*

**Its `business_month` never changes.** August sales means orders placed in August, and that
is frozen by trigger (Phase 4 Task 1). Carry-forward is about *which payroll pays it*, never
about which month it belongs to — and conflating the two is what would make a model's own
arithmetic disagree with her payment.

**This is the answer to HBA's question about closed months.** A model looking at August will
see that order, because it is an August sale. `attributed_order.settled_in_snapshot_id` —
deferred from Phase 4 precisely until snapshots existed — records **which payroll actually
paid it**, so her dashboard can say *"paid in your September payment"* rather than leaving her
to work out why the numbers differ.

**Nothing carries backwards.** §9.3 and ADR 0025: a return, a refund or a correction arriving
after approval is absorbed. Good news carries forward; bad news stops at the door. That
asymmetry is deliberate and favours the model.

**Tests:** an order settling after approval appears in the next draft, labelled; its business
month is unchanged; the snapshot it was paid in is recorded; nothing negative carries.

---

## Task 5: Reopen

**Files:** modify `app/services/payroll.py`; tests

§11.5. Returns an approved month to `draft`, **requires a written reason**, and preserves the
prior snapshot as a version.

**On reopen, carried orders behave by where they sit** (§11.4):

| Destination month | Behaviour |
|---|---|
| Still `draft` | **Reclaimed** into the reopened month, where they belong. Shown explicitly. |
| Already `approved` | **Stay there, permanently.** That month is settled. |

Three outcomes on re-approval (§11.5), and the platform reports which:

| Outcome | Resolution |
|---|---|
| Higher | Underpaid. `balance_due` shows the gap. |
| Lower | Overpaid. **The maintainer chooses** a credit or a write-off — the platform never decides. |
| Unchanged | Nothing to reconcile. |

**Payment allocations against the old snapshot remain intact and visible.** Money that moved
does not un-move because a calculation was revisited.

**A month reopened and left unapproved raises an alert** (§11.5). The dangerous state is not
reopening; it is forgetting.

**Tests:** a reason is required; the old version survives with its allocations; reclaim from a
draft month and not from an approved one; each of the three re-approval outcomes; the stuck
alert.

---

## Task 6: Historical months

**Files:** modify `app/services/payroll.py`; config; tests

§11.2, ADR 0014. Re-importing from January gives every model months of orders with no payroll
records. Without this they all read as unfinalised and owed — **money already settled outside
the platform**.

A configured **go-live month** divides time. Months before it are `historical`: imported and
visible, **never payable, never approvable, never in "owed"**.

**Historical months show sales only — never a commission figure.** Decided, and worth
restating: computing March's commission needs March's rates, which exist only in the old
system and in memory. Applying today's rates to last March would be actively misleading, and
reconstructing them by hand invites errors nobody could later verify. Labelled *"Settled
before the platform — commission not calculated."*

**The go-live month is not yet chosen** (§21, open question 1). This task builds the mechanism
and the platform must refuse to approve anything until the month is configured — an unset
go-live silently makes every historical month approvable, which is the failure this exists to
prevent.

**Tests:** a historical month is not approvable; it reports sales and no commission; the
boundary month behaves as live; an unconfigured go-live blocks approval rather than defaulting.

---

## Task 7: The payroll API

**Files:** create `app/api/payroll.py`; tests

```
GET  /api/payroll/{month}                    every model, figures, blockers
POST /api/payroll/{month}/approve            one or many, with a preview first
POST /api/payroll/{month}/reopen             reason required
GET  /api/affiliates/{id}/payroll/{month}    one model, with her snapshot history
```

**Approval is a POST that can be previewed.** §11.3 requires seeing every model, amount and
blocker before committing; a preview flag returning exactly what would happen is the honest
way to do that, because the preview and the commit then run the same code.

**Permission-gated:** `payroll.approve` and `payroll.reopen` separately (§5.1). Reopening a
settled month is a different act from approving an open one.

**Tests:** the preview commits nothing; approving a blocked month is refused with the blocker
named; reopening without a reason is refused; a model may not see any of it.

---

## Deliberately not in this phase

- **Payments.** Phase 7. This phase produces an obligation; nothing here records money moving,
  and `balance_due` is therefore always the full obligation until then.
- **Notifications.** §16 emails a model when her month is approved. `notification_outbox`
  exists from Phase 2; wiring it is Phase 10, and the outbox is written transactionally with
  the approval so nothing is lost in between.
- **The interface.** Screens come after Phase 7, against a settled model.

---

## Risks

**A snapshot that recomputes is not a snapshot.** The single largest risk in the phase, and
the reason `payload_json` stores the whole calculation rather than references. Guarded by a
test that changes the underlying data and asserts the snapshot did not move.

**Reopen is the most dangerous operation in the platform.** It touches a month somebody has
been paid for. Mitigated by: a written reason, the old version preserved, allocations
untouched, and an alert if it is left unapproved.

**Two seams start refusing at once.** `assert_correctable` and `assert_recordable` have
blocked nothing since Phase 3 and Phase 5. Wiring them here changes behaviour that existing
tests currently assert is permitted, and those tests are right to change — but the change must
be deliberate rather than a surprise.
