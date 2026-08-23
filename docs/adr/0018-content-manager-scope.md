# 0018. content_manager holds wide, overlapping authority

**Status:** Accepted — risk knowingly accepted by the business
**Date:** 2026-08-22

## Context

Sara works under Boda and tracks what each affiliate publishes. The first draft
gave her a narrow `target_recorder` role: view affiliates, record target
actuals, nothing else.

The business corrected this. Her job in practice combines setting the monthly
requirements, recording what was published, verifying it, maintaining affiliate
records, and setting compensation terms.

## Decision

The role is named `content_manager` rather than `target_recorder`, because the
original name no longer describes the work, and holds seven permissions:

`affiliates.view` · `affiliates.manage` · `compensation.manage` ·
`targets.record` · `targets.manage` · `targets.verify` · `audit.view`

## Consequences

**The separation of duties an earlier draft protected is gone, deliberately.**
This role sets the target, records the result, and verifies it - and
verification is what releases a base guarantee. There is no second pair of eyes
between defining the bar, judging it met, and the money that follows.

The business made this call with the risk stated plainly. It is recorded here so
that a future maintainer reading the permission list does not treat it as an
oversight and quietly "fix" it.

**The boundary that does still hold:** no role except `admin` can both decide an
obligation and settle it. `content_manager` cannot approve payroll, reopen an
approved month, record a payment, or invite anyone. Deciding what is owed and
paying it remain separate acts performed by different people.

Ten explicit negative assertions cover the denied permissions, so widening the
role further is a deliberate act with a failing test, not a quiet edit.

## Alternatives considered

**Keep `target_recorder` narrow and add a second role.** Cleaner in theory, and
it does not match how one person actually works.

**Split verification into a separate role.** The obvious mitigation. It needs a
fourth person who does not exist at this organisation's size.
