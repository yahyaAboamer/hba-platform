# Phase 5 — Targets, verification, and the bulk entry grid

**Spec:** `docs/specs/2026-08-22-hba-platform-v1-design.md` §15, §9.5, §11.3, §12.2, §8
**ADRs:** 0018 (content-manager scope), 0025 (delivery is final)
**Depends on:** Phase 3 (compensation terms) and Phase 4 (the calculation that blocks on this)
**Delivers:** whether a base guarantee applies — and therefore the last thing standing between
a `base_guarantee` model and being paid through the platform.

---

## What this phase is for

Phase 4 ends with a hole it deliberately left open. §9.5 pays a `base_guarantee` affiliate
**max(commission, base amount)** — but only when her targets were *achieved **and**
verified*. Targets do not exist, so `calculate_month` reports her commission and refuses to
resolve the guarantee, blocking the month.

That refusal was correct and it is expensive: **no base-guarantee model can be paid through
the platform until this phase ships.** Everything here exists to close that.

It is a smaller phase than Phase 4 and a different kind of work. Nothing here touches money
directly. It records what a model was asked to produce, what she actually produced, and
whether a second person confirmed it — and Phase 4's arithmetic reads the answer.

### Targets mean different things to different models

| Compensation type | What a target does |
|---|---|
| `commission` | **Informational.** Recorded, shown, pays nothing |
| `fixed_plus_commission` | **Informational** |
| `base_guarantee` | **Decides pay.** The guarantee applies only if achieved and verified |

So most models' targets are a management tool, and a minority's are a payment input. The
same table serves both, and the difference lives entirely in §9.5's rule.

---

## The three rules that decide everything

**1. Verification is a second pair of eyes, and it must be.** Recording an actual and
confirming it are separate permissions (`targets.record`, `targets.verify`) because
recording alone unlocking a payment is one person deciding what somebody is owed. ADR 0018
notes that Sara's `content_manager` role deliberately holds both — which makes this a
*structural* separation the platform enforces rather than an organisational one it observes.
That is recorded as an accepted exposure in `docs/limits.md`, not papered over.

**2. Missing information blocks; poor performance does not.** §11.3, and the distinction is
the whole design:

| Situation | Approval |
|---|---|
| No target recorded at all | 🚫 **Blocked** — nobody knows what she was asked for |
| Recorded, not achieved | ✅ **Allowed** — the base simply does not apply |
| Achieved, not yet verified | 🚫 **Blocked** — verification is what unlocks the base |

A model who missed her targets is paid her commission, promptly, with no ceremony. The block
exists for the cases where the platform *does not know*, never as a punishment.

**3. An approved month is closed to recording.** §15. Changing a target after payroll would
change what a month was worth after it was paid. Reopen first (§11.5), which requires a
written reason.

---

## Task list

| # | Task | Delivers |
|---|---|---|
| 1 | `monthly_target` | The table, one row per model per month, and what may change |
| 2 | Setting and recording | Requirements, actuals, and the achieved rule |
| 3 | Verification | The second pair of eyes, and what it unlocks |
| 4 | Resolving the guarantee | Phase 4's blocker, answered |
| 5 | The bulk grid | Every model down the side, one month across, one save |

---

## Task 1: `monthly_target`

**Files:** create `app/models/targets.py`; one Alembic migration; test `tests/test_targets.py`

**Columns** (§8): `affiliate_id`, `month`, `required_videos`, `required_stories`,
`actual_videos`, `actual_stories`, `recorded_by`, `recorded_at`, `verification_status`,
`verified_by`, `verified_at`, `created_at`, `updated_at`.

**One row per affiliate per month**, enforced by a unique constraint (§17). Two rows would
mean two answers to "did she achieve August?", and whichever the query happened to read
first would decide a payment.

**`month` is a plain `YYYY-MM` string**, matching every other dated thing in the platform
(`compensation_period`, `attributed_order`). Not a date, because a target belongs to a month
rather than to a day in it.

**Actuals are nullable; requirements are not.** A target with no requirement recorded is the
"nobody knows what she was asked for" case that blocks approval, and it must be
distinguishable from a requirement of zero — which is a real answer meaning *nothing was
asked of her this month*.

**Not append-only**, but verification is one-way: see Task 3.

**Tests:** two rows for one month are refused; requirements of zero are allowed and distinct
from absent; negative counts are refused; the row dies with its affiliate.

---

## Task 2: Setting and recording

**Files:** create `app/services/targets.py`; tests

```
set_requirements(db, affiliate, month, *, videos, stories, actor) -> MonthlyTarget
record_actuals(db, target, *, videos, stories, actor) -> MonthlyTarget
is_achieved(target) -> bool | None
```

**`is_achieved` returns `None` when actuals are absent**, and that is the point. "Not
achieved" and "not yet recorded" are different answers with different consequences — the
first pays commission, the second blocks the month — and a boolean cannot express both.

**Achieved means every requirement met**, videos *and* stories. Partial achievement is not
achievement; §9.5 has no fractional guarantee.

**Recording is refused on an approved month.** Payroll months arrive in Phase 6, so this
phase builds the seam and a test proving it is called — the same way Phase 3 left
`assert_correctable` for compensation. Recorded in `docs/limits.md` as what it is: **not yet
enforced, because there is nothing yet to enforce it against.**

**Every change is audited** with before and after. A target that decides a payment needs the
same trail as the payment.

**Tests:** achieved needs both; zero requirements are achieved by zero actuals; absent
actuals are neither achieved nor missed; recording twice keeps the latest and audits both.

---

## Task 3: Verification

**Files:** modify `app/services/targets.py`; tests

```
verify(db, target, *, actor) -> MonthlyTarget
unverify(db, target, *, actor, reason) -> MonthlyTarget
```

**Verification records who and when**, not merely that it happened — the same reasoning as
`shopify_verified_at` in Phase 3. "Verified, by whom, eight months ago" is a different answer
from "verified", and only one of them can be audited.

**Verifying requires actuals to exist.** Confirming a number nobody has recorded is
confirming nothing, and it would unlock a guarantee on an empty month.

**Unverifying requires a written reason** and is audited. It is the only way back, and it
exists because a mistaken verification otherwise silently pays a guarantee.

**Verification does not mean achieved.** A verified target that was missed is a *confirmed
miss* — she is paid commission, and the month is approvable. Conflating the two would block
every model who had a quiet month.

**Tests:** verifying without actuals is refused; verifying a missed target is allowed and
unlocks approval without applying the guarantee; unverifying without a reason is refused;
both directions are audited.

---

## Task 4: Resolving the guarantee

**Files:** modify `app/services/commission/calculate.py`; tests

The blocker Phase 4 left, answered. `calculate_month` reads the month's target and applies
§9.5:

```
achieved and verified  →  payout = max(commission, base_amount)
achieved, unverified   →  blocked
not achieved           →  payout = commission, no blocker
not recorded           →  blocked
```

**The base is never added on top of a higher commission, and never caps it.** A model whose
commission beats her guarantee is paid the commission. §9.5 says this explicitly because the
opposite is the intuitive mistake.

**`TARGETS_UNVERIFIED` stops being a permanent blocker** and becomes a real answer. The
`docs/limits.md` entry recording that base-guarantee models cannot be paid is closed here.

**Only `base_guarantee` is affected.** A `commission` model with no target recorded is
payable — the target is informational for her, and blocking her month over a management
figure would stop a payment for a reason that has nothing to do with what she is owed.

**Tests:** each of the four rows above; commission beating the guarantee; the guarantee
beating commission; a `commission`-type model unaffected by a missing target; a month
spanning a compensation-type change using that month's own type.

---

## Task 5: The bulk grid

**Files:** create `app/api/targets.py`; tests

§12.2: *"Sara's target entry is a bulk grid — every model down the side, one month across,
tab straight through, single save."*

```
GET  /api/targets/{month}                 every model, requirements and actuals
PUT  /api/targets/{month}                 one save for the whole grid
POST /api/targets/{month}/verify          verify one or many
GET  /api/affiliates/{id}/targets/{month}
```

**One save, and it is all-or-nothing.** Twenty models in one transaction: if row eleven is
invalid, nothing is written and the response says which row and why. A partial save on a
grid is worse than a rejection, because the person cannot see which half landed.

**The grid returns rows for models with no target yet**, with nulls rather than omitting
them. A model missing from the grid is a model nobody records a target for, which is exactly
the case that blocks her month later.

**Permission-gated per action.** `targets.record` writes actuals; `targets.verify` verifies.
The split is meaningless in today's roles (ADR 0018) and enforced anyway, because roles
change and the endpoint is what will still be there.

**Tests:** the whole grid saves at once; one bad row rejects all of them and names it; a
model with no target appears with nulls; recording without `targets.record` is refused;
verifying without `targets.verify` is refused; an `affiliate` role is refused everything.

---

## Deliberately not in this phase

- **Evidence collection.** §15 is explicit: *"Evidence collection remains external for V1."*
  Sara counts posts on the models' own social accounts and records the totals. The platform
  stores what she recorded and who confirmed it, and does not attempt to see Instagram.
- **Payroll months and approval.** Phase 6. This phase provides the answer that unblocks
  approval; it does not approve anything.
- **The grid's interface.** The frontend is still a placeholder. This builds what it saves
  through.
- **Targets for house accounts.** They are not owed money, so a guarantee cannot apply.
  Allowed and ignored rather than specially refused.

---

## Risks

**The verification separation is organisational, not technical.** One person holds both
permissions today. The platform enforces the split; HBA's staffing does not. Already recorded
in `docs/limits.md` from Phase 3 and not made worse here — but this is the phase where that
exposure starts deciding payments, so it is restated where it now bites.

**A target recorded for the wrong month pays the wrong month.** Month is a free field on a
grid, and the guard is that the grid is per-month by URL rather than per-row.

**Nothing yet stops recording against an approved month**, because approved months do not
exist until Phase 6. The seam is built and tested; the enforcement is Phase 6's to wire, and
the gap is recorded rather than assumed closed.
