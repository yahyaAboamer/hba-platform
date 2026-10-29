# 0070. A bonus is added on top of a month nobody has agreed yet

**Status:** Accepted
**Date:** 2026-10-29

## Context

The owner, 29 October 2026: *"I want to add a feature that lets me add a bonus
for models … inside every model, a button that says add bonus … an optional
reason that will only appear for us … and it should appear at the month
summary for the models."*

Until now the only ways a model's month could move were her orders, her terms,
her targets, and corrections after approval. None of them is a decision to pay
more. The approved exports draw no bonus anywhere, so this is a new screen
element as well as a new money rule.

He chose the answers to five questions (29 October 2026): which months, whether
a bonus can be removed, whether it counts towards the guaranteed minimum, whether
she is told, and who may add one. He named **admin, the affiliate manager and
finance**. The platform has no finance role yet (Finance is a deferred Phase 4
department, roadmap batch 4.2).

## Decision

1. **A bonus is its own record**, `payroll_bonus`: an amount in whole pounds on
   one payroll month, an optional reason, who added it and when, and who
   withdrew it and when. It is **not** a `payroll_adjustment`. Adjustments
   settle a difference against an agreed month and are read by the
   correction arithmetic (`adjusted_against`, `credited_into`); a bonus put
   there would be read as one.
2. **It is added on top, after the guaranteed-minimum comparison**, in the same
   place carried orders are (`commission/calculate.py`). Inside the comparison
   a model on a floor would be paid the floor with or without it, which makes
   the bonus nothing for exactly the model who earned least. It is part of
   `payout_piastres`, so every screen and the payments desk that read the
   month's figure include it without a second implementation.
3. **Only on a month nobody has agreed**: not a month before go-live, not a
   future month, not a house account. Approval freezes the bonus lines into
   the snapshot and into the month's fingerprint (`source_version`), so a bonus
   added between the preview and the commit refuses the commit (05B). A bonus
   for an agreed month goes on the current month, or the month is reopened.
4. **It can be withdrawn while its month is open**, and the row is kept,
   marked withdrawn. After approval it is part of what was agreed.
5. **The reason is staff-only.** The calculation and the snapshot carry each
   bonus's id and amount and never its reason, so nothing the portal reads
   holds it. It is kept on the row and in the audit trail.
6. **She sees it on her month**: a line *Includes a bonus of EGP 500.00 from HBA*
   under the figure, and a *Bonus from HBA* line in *See how it adds up*. The
   admin statement and Home's expected-payout breakdown name it as a part, so
   their parts still add up to the total.
7. **Who may add or withdraw**: a new permission, `payroll.bonus`, held by
   admin (every permission) and the affiliate manager. A finance role is given
   it when one is created. Anybody who can see a model can see her bonuses
   and their reasons.
8. **Whole pounds, at most EGP 100,000** for one bonus. Payouts round to the
   pound once (ADR 0004), so a fraction would be rounded away; the ceiling
   catches three extra zeros.

## Consequences

- **No email of its own.** The recommendation the owner accepted said she would
  be told in the portal. That is the line on her month. A separate email was
  left out because a bonus can still be withdrawn before approval, and an email
  announcing money that is then taken back is worse than none; the month's
  approval email already states the total with the bonus inside it.
- Withdrawing is a POST and the row stays. Nothing about money is deleted
  (`api.del` is reserved for non-financial records).
- A month with no terms can hold a bonus but cannot be approved until terms
  are recorded, exactly as before.
- The admin profile's **Add bonus** button and *Bonuses* panel, and the line on
  her month, are not in the approved exports. They follow the panels and hero
  tiles beside them; the owner reviews them before merge.
- Downgrading the migration drops the table and the record of any agreed bonus.

## Alternatives considered

- **A `bonus` type on `payroll_adjustment`.** Rejected in Decision 1: the
  correction arithmetic sums that table.
- **Adding the bonus inside the guarantee comparison.** Rejected in Decision 2.
- **A bonus as a separate payable outside the month's figure.** Every reader of
  `approved_obligation_piastres` (the payments desk, balances, her payments
  screen) would need a second figure, and a second figure is a second answer
  waiting to disagree.
- **Allowing a bonus on an agreed month.** It would change money under the word
  *Approved*, which the platform never does (§11.1).
