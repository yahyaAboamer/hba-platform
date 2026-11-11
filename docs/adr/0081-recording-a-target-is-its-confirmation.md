# 0081. Recording a target is its confirmation

**Status:** Accepted (owner, 11 November 2026); amends §9.5, §11.3 and §15 of the spec, and the target half of ADR 0018
**Date:** 2026-11-11

## Context

Since the platform was built, a month's achieved counts were *recorded* by one
act (`targets.record`) and *confirmed* by another (`targets.verify`). A
guaranteed minimum (`base_guarantee`) applied only where the target was met
**and** confirmed; a met, unconfirmed month blocked payroll
(`targets_achieved_but_not_verified`).

The Targets refinement asked what confirming actually did:

- **It changed money in one case only**: a model on a guaranteed minimum who
  met her target. The screen offered the tick on every recorded row,
  commission-only models and missed targets included.
- **It was not a second pair of eyes.** The content manager and the affiliate
  manager both held recording and confirming, so the person who typed the
  numbers could confirm them a second later. The code recorded this as an
  accepted exposure.
- **It could be pressed mid-month**, and the next weekly count wiped it.
- **It protected one direction only.** A typo that made a met month look met
  needed a confirmation; a typo that made it look missed cost her the
  guarantee and nobody looked.

Asked whether confirming should stay, be narrowed, or require a different
person, the owner chose to remove it: *when we record what the model has done,
it is already confirmed* (11 November 2026).

## Decision

1. **Recorded counts are the confirmed counts.** A guaranteed minimum applies
   where the target is met; there is no second step.
2. **A guarantee month blocks only where nothing is recorded**
   (`no_target_recorded_for_this_month`). The `targets_achieved_but_not_verified`
   blocker is gone, and so is the setup gap `target_not_verified`; the live
   setup gap is now `target_not_recorded`.
3. **The confirm and take-back actions are removed**: the screen controls, the
   `/verify` and `/unverify` endpoints, and the `targets.verify` permission.
4. **The Targets save lists what it will change before it writes.** Recording
   now releases money on its own, so the save is the check: each change old →
   new, with what it does called out (an outcome that turns, a month that has
   ended). Nothing is written until *Save N changes* is pressed.

## Consequences

- **Open months change on their next calculation.** A guarantee month that was
  met and waiting for a confirmation now pays its minimum (where it is above
  the commission) and stops blocking payroll. Agreed months are frozen in
  their snapshots and do not change.
- **Agreed months keep reading *unchanged*.** Their stored fingerprint hashed
  the old confirmation flag; the comparison also accepts that old form
  (`agreed_source_unchanged`), so removing the flag does not mark every agreed
  month *changed since approval*.
- **History stays.** `verified_by` / `verified_at` and their constraint stay in
  the database, unread, so past confirmations remain in the audit trail; there
  is no migration. The audit words for `target.verified` and
  `target.unverified` stay so old entries still read.
- **The model portal stops saying *waiting to be confirmed*** and *being
  checked*: a met guarantee month reads as met.
- **One person now decides a guaranteed minimum by typing the counts.** The
  review list before saving is the guard against a slip; the audit trail
  records who recorded what. Approving payroll stays a separate permission,
  so the obligation and its payment are still separate acts.

## Alternatives considered

- **Keep confirming, but only for guarantee rows that were met, after the month
  ends.** Removes the busywork but keeps a check that the same person can
  satisfy alone.
- **Require someone other than the recorder to confirm.** A real check, at the
  cost of a second person on every guarantee month. Not chosen by the owner.
- **Read-only boxes until *Edit* is pressed.** Stops a stray keystroke but adds
  a click to every weekly entry and does nothing for a wrong number once
  editing; the change list catches both.
