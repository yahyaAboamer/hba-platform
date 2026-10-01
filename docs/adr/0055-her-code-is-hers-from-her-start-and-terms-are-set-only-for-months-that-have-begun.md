# 0055. Her code is hers from her start, and terms are set only for months that have begun

**Status:** Accepted
**Date:** 2026-10-01
**Amends:** 0052 (*Future pay terms*), 0053 (decision 1, the month her code's ownership starts)

## Context

**ALI10 on staging, 1 October 2026.** The owner saw ALI10 under *Discount
codes belonging to nobody* (Settings → Shopify and sync) with five orders, all
from January 2026. Shopify shows the code *Active from Feb 27, 2025* with 99
uses. He suspected the sync.

The sync was not at fault. Read on staging and from Shopify with the platform's
own connection:

- `order_index` holds 104 ALI10 orders, January to September 2026.
- 99 of them are attributed to Ali: April 17, May 15, June 16, July 32,
  August 8, September 11. That is exactly Shopify's *99 used*.
- Shopify's ALI10 is a discount object **created on 4 April 2026**
  (`createdAt`). Its `startsAt` is 26 February 2025, the same second as
  SARAED's, so it was made by duplicating another discount. ALI10 orders on
  Shopify go back to October 2025, on an earlier object. Shopify's usage count
  covers only the current object, from April.
- When her code was confirmed, two different dates were used for one fact.
  Her **start month** came from `startsAt`, which gave January 2026 (ADR 0053).
  Her **code's ownership** came from `createdAt` (`start_month_for`), which
  gave April 2026. So January's five orders belonged to nobody.

**Pay terms.** The owner, the same day: when he sets a model's terms the screen
does not say which month she started, so terms can be put on months she was
not yet working. And the month grid offers months that have not begun (ADR 0052
allowed twelve ahead). He cannot decide those now. When a new month begins it
should carry on the terms of the month before it, by itself.

## Decision

1. **Her code is hers from the month her code starts on Shopify**, by the same
   rule as her start month: the code's start date where Shopify has one, else
   its creation date, in Cairo, never before January 2026. `start_month_for`
   takes both dates and is the one rule for both. A recreated or duplicated
   discount no longer cuts off the orders its code took before the recreation.
2. **Pay terms are set only for months from her start month to the working
   month.** The editor says when she started, and where that came from. The
   server refuses an arrangement that starts after the working month. Once her
   start month is known (from her code, or recorded on her profile), it also
   refuses one that changes a month before it. Terms already on record there
   are re-sent unchanged and kept. With no start known, the screen opens at her
   first sale, as before.
3. **The latest arrangement runs on.** Any arrangement reaching the working
   month is stored *until further notice*, so each new month takes the terms of
   the month before it when it begins. No month is ever arranged in advance.
4. **Existing records are brought into line by migration `d9e4f7a50009`.**
   - A confirmed code whose ownership starts after its model's start month is
     moved back to her start. This happens only where no other period of the
     same code covers those months. The hourly orphan sweep then attaches the
     orders.
   - The latest arrangement that ends in or after the current month is made
     open-ended.

## Consequences

- On staging, ALI10 owns January to March 2026 as well. Its five January
  orders move from *belonging to nobody* to Ali within the hour after the
  deploy. February and March have no ALI10 orders.
- An agreed raise from next month can no longer be entered ahead of time. It
  is entered once the month begins, and that month's estimate is right from
  then on. The owner chose this.
- A model's terms never stop at the end of the current month by accident. To
  end an arrangement, a later month is given a different one once it begins.
- If Shopify holds a start date that is earlier than the model's real start,
  her code claims orders from that earlier month. A code is hers and is never
  reused (ADR 0053), so those orders are hers. Overlapping periods of one code
  are still refused by the database.
- The migration's data changes are not reversed by its downgrade. Moving an
  ownership start back later would orphan orders that have since been
  attributed.

## Alternatives considered

- **Start ownership at her first indexed order with the code.** It would fix
  ALI10 too, but it brings back the first-order guess that ADR 0053 removed for
  her start month, and the two dates could disagree again.
- **Keep months ahead but warn.** The owner was explicit that months that have
  not begun cannot be decided now.
- **Repair ALI10 by hand on staging.** It fixes one row and leaves the cause.
  The migration fixes the cause and is rehearsed like every other one.
