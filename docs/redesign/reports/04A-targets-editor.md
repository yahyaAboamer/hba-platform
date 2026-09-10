# Batch report — Phase 04A, the monthly targets editor

**Date:** 10 September 2026
**Branch:** `phase04a/targets`, based on `main` @ `f6f5af8`
**Requested scope:** Persist requirements separately from weekly cumulative achievements; null/zero/invalid/stale distinctions. No cross-month unsaved draft application. Keep the admin model-profile summary consistent.

**Delivered behaviour:** Three gaps closed, one of which could write one
month's requirements into another. Most of this batch already existed and was
verified rather than rebuilt.

---

## Review

### What was already right

The targets service was in better shape than the roadmap assumes.
`set_requirements` and `record_actuals` are already separate functions with
separate audit entries; actuals are **set, not added**, so a weekly cumulative
count replaces rather than accumulating (A06); a half-recorded row is refused
by the service *and* the database; re-recording clears verification so a
correction cannot inherit somebody's approval; and an unknown outcome already
blocks a guaranteed minimum rather than reading as a miss.

Two of the three things the completion gate asks for were therefore already
true. I added tests naming them anyway, because "it happens to work" and "it is
guarded" are different states.

### The dangerous one

**A draft could cross months.** The month picker and the grid are two pieces of
state that change at different moments: the picker moves first, the rows arrive
later. Between those two moments the screen showed one month's figures under
another month's heading — and a save there wrote **August's requirements into
September**, silently, into the data that decides whether a guaranteed minimum
applies.

The prompt names this exactly (*no cross-month unsaved draft application*).
It is now refused rather than reconciled: there is no correct guess about which
month somebody meant. A slow response for a month you have already left is also
discarded rather than painted.

### Two people, one month

There was no concurrency check at all. Both of you run payroll and both open
Targets at month end; the second save silently overwrote the first, and **the
losing edit was invisible** — no error, no conflict, and no way to notice except
by re-reading a number you already believed.

The grid now carries a revision and a stale save is refused with a 409 that says
what to do. The revision is *derived from the rows*, not stored: a version
column would need writing on every path that touches a target and would be wrong
the first time somebody forgot. It counts rows as well as timestamps, because a
model added mid-edit changes no existing timestamp and putting somebody on the
programme mid-month is ordinary.

### Unrecorded and zero are different facts

A06 lists them separately and the platform could only move one way between them.
A count typed against the wrong model could be corrected to `0` — which does not
say *this was a mistake*, it says **she produced nothing**, and that is the claim
that fails a guaranteed minimum.

Emptying both count boxes now takes them off, and clearing carries the
verification away with it for the same reason recording does.

### What the owner should try

1. **Targets → set 8 videos for a model, save. Then change only the
   requirement and save again.** Her recorded counts do not move.
2. **Record counts, then empty both boxes and save.** It goes back to *nobody
   has recorded this* — not to zero. Her Achieved column shows a dash, not a
   miss.
3. **Open Targets in two tabs, save in one, then save in the other.** The second
   is refused and tells you to reload rather than quietly winning.
4. **Change month quickly while it is loading, then save.** Refused, with *that
   month is still loading*.

### Approved-design deviations

**None.** The exports draw a targets grid; nothing here changes what it shows.

---

## Engineering evidence

**Rules and IDs covered:** A06, F06 (unknown blocks a guarantee — verified, not
changed), UI21, UI22. UI23/UI24 are 04B.

### Files changed

| File | What |
|---|---|
| `app/services/targets.py` | **`clear_actuals`** — the way back to unrecorded |
| `app/api/targets.py` | `_revision`, the 409, `clear_actuals` on a row, and both refusals |
| `frontend/src/screens/Targets.tsx` | Stale-response guard, month/grid mismatch refusal, revision round-trip, clearing |
| `tests/test_targets_api.py` | 8 new; every save routed through a revision-aware helper |

**No migration.** The revision is derived; clearing writes columns that already
exist.

### Two decisions worth naming

**A save with no revision at all is refused**, not waved through. Absence is not
agreement — a caller that sends nothing is one that has not been taught to
check, and this decides guarantees.

**The cross-month save is refused, not reconciled.** Reconciling means guessing
which month somebody meant, and there is no correct guess.

### Commands, results, environment

| Check | Result |
|---|---|
| `pytest -q --color=no` against `hba_platform_test` | **1737 passed**, exit 0 — 1729 on `main`, **8 new** |
| `cd frontend && npm test` | **198 passed**, exit 0 |
| `cd frontend && npm run build` | exit 0 |

Sixteen existing saves in `test_targets_api.py` now go through a `_save` helper
that carries the revision, so they keep testing **behaviour** rather than the
calling convention. One of them needed an explicit revision instead: the
permission test would otherwise have been refused at the read and passed for the
wrong reason.

### Visual comparison — not performed

Automation still cannot sign in. The Targets screen changed in three places —
the stale guard, the refusal message, and clearing — and none has been seen.

---

## Continuation

### Limitations

- **Nothing tells you a month is being edited elsewhere** until you save. A
  conflict is caught, not prevented, which is the right trade for two people
  but would not be for twenty.
- **Clearing is inferred from two empty boxes**, not a button. It reads well
  and it is not discoverable; if it is ever used by mistake the audit says who
  and when, and the counts can be typed back.
- **The admin model-profile summary** was checked for consistency and needed no
  change — it reads the same service.

### Decisions recorded

None new.

### Next

**Phase 04B** — verification, historical outcomes and the model's own Targets
tab. The outcome half already exists (shipped in `1fe55de`); what 04B owes is
the model-facing read and the Targets tab, which is still `NotBuiltYet`.

### Live changes

**None.** No deployment, no production branch moved, no financial data touched.
