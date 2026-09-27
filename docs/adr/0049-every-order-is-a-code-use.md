# 0049 — Every order is a code use

**Status:** accepted — supersedes D03's definition of a use (its ranking rule stands)
**Date:** 2026-09-27
**Related:** `app/services/performance.py` (`_use_count`, `uses_for`,
`month_performance`); `docs/redesign/decisions/D03-uses-are-deliveries-not-money.md`;
ADR 0048 (amended the same day); `frontend/src/screens/MyMonth.tsx`

## The situation

D03 (11 September) made a use a *delivery* outcome: every order counted
except a failed delivery. On 27 September Home's orders card moved to three
states - *delivered*, *pending*, *failed*, with *failed* holding failed
deliveries, cancellations and refunds (ADR 0048, amended) - and a month with
one failed delivery then read *10 delivered · 3 pending · 4 failed* beside
*16 code uses*. The owner, the same day:

> You should count every single order that uses the discount code as a code
> use. I don't care what the status of this order. If it had the use, then it
> is recorded as a code use. And orders counted are for delivered and pending
> only. So all the failed statuses should count as code uses, even if they
> are canceled, refunded, or failed delivery.

## Decision

- **A code use is every order attributed to her code**, whatever became of
  it: delivered, pending, failed delivery, cancelled or refunded. One
  expression counts it (`performance._use_count`), and every screen that
  shows uses reads through it - her card and Home, the year chart, Ranking,
  the admin roster and the owner's overview.
- **Orders counted is unchanged**: delivered and pending (F02, ADR 0040).
- **Ranking's rule is unchanged** (D03): order by sales, uses break a tie,
  equal on both shares a place. The tie-break now counts every order.
- Home's card adds up again: *delivered + pending + failed = code uses*.

## What it costs

- **Uses no longer say anything about delivery.** D03 kept a refused parcel
  out of the count on purpose; that distinction is gone, by the owner's
  choice. A model whose parcels are refused keeps the uses.
- **Historical and past months change** wherever a failed delivery exists:
  her year chart, a past month's card and a past Ranking tie-break read the
  new count. Nothing about money reads uses - no commission, payroll, target
  or snapshot - so no agreed figure moves.
- A Ranking tie decided by uses can resolve differently for a month with
  failed deliveries.
