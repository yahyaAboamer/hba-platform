# 0005. The business month is derived in Africa/Cairo

**Status:** Accepted
**Date:** 2026-08-22

## Context

Every order belongs to a payroll month, and that month decides who is paid what.
It is therefore a financial rule, not a formatting preference.

Egypt abolished daylight saving in 2015 and reinstated it in 2023. Verified
against the timezone database, 2026 runs UTC+3 from 24 April to 29 October and
UTC+2 otherwise. The consequence:

| Instant | Cairo local | Month |
|---|---|---|
| `2026-08-31 21:30 UTC` | 1 Sep, 00:30 (+3) | **September** |
| `2026-12-31 21:30 UTC` | 31 Dec, 23:30 (+2) | **December** |

The same clock time falls in different months depending on the season. Reading
the UTC prefix of the timestamp - the obvious shortcut - files the first order
in August, which is wrong.

## Decision

Timestamps are stored in UTC. The business month is derived by converting to
`Africa/Cairo` via `zoneinfo`, with `tzdata` as an explicit dependency so
Windows and slim containers both resolve the zone.

A fixed offset is never used. Naive datetimes are refused rather than assumed,
because a naive timestamp names no instant and guessing one moves orders between
payroll periods.

## Consequences

The timezone database becomes a dependency of correctness. If Egypt changes its
policy again, every month boundary moves. A deliberate canary test asserts the
2026 offsets, so such a change surfaces as a failing test rather than as a
quietly misfiled payroll.

Converting UTC to local is always unambiguous, so the missing hour in spring and
the repeated hour in autumn do not affect this direction. The system never
converts local to UTC.

## Alternatives considered

**Fixed UTC+2.** Two tests exist purely to demonstrate that this misfiles
orders, in both directions depending on season.

**Store the month as Shopify reports it.** Shopify reports UTC - the same
problem, moved upstream where it is harder to see.
