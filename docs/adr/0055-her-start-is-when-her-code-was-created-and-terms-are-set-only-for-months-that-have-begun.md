# 0055. Her start is when her code was created, and terms are set only for months that have begun

**Status:** Accepted
**Date:** 2026-10-01
**Amends:** 0052 (*Future pay terms*), 0053 (decision 1, where her start month comes from)

## Context

**ALI10 on staging, 1 October 2026.** The owner saw ALI10 under *Discount
codes belonging to nobody* (Settings → Shopify and sync) with five orders, all
from January 2026. Shopify shows the code *Active from Feb 27, 2025* with 99
uses. He suspected the sync.

The sync was not at fault. Read on staging and from Shopify with the platform's
own connection:

- `order_index` holds 104 orders with the code ALI10 in 2026: five in January,
  99 from April to September. The 99 are attributed to Ali and equal Shopify's
  *99 used*.
- Shopify's ALI10 was **created on 4 April 2026**. Its *Active from*, 26
  February 2025, is the same second as SARAED's: it was copied when the
  discount was duplicated, and says nothing about when ALI10 began.
- The owner: the ALI10 orders before April were **another model's**, on a
  code since renamed *ALI10 OLD*. Shopify keeps the text the customer typed,
  so those orders still read ALI10.
- When her code was confirmed, two dates were used for her. Her **start
  month** came from *Active from* (ADR 0053), so January 2026. Her **code's
  ownership** came from the creation date, so April 2026. The code's month was
  right and her start month was wrong.

**Pay terms.** The owner, the same day: when he sets a model's terms the screen
does not say which month she started, so terms can be put on months she was
not yet working. And the month grid offers months that have not begun (ADR 0052
allowed twelve ahead). He cannot decide those now. When a new month begins it
should carry on the terms of the month before it, by itself.

## Decision

1. **A code starts in the month it was created on Shopify, and so does the
   model who holds it.** Both come from the code's creation date, in Cairo,
   never before January 2026, through one function (`model_start_month_for`,
   which `start_month_for` uses). *Active from* is not used for either: a
   duplicated discount copies it. A start somebody typed on her profile is
   still never overwritten (ADR 0053).
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
   - A start month that the platform took from her code is set to her code's
     creation month. On staging that moves Ali from January to April 2026. A
     start somebody typed is not touched.
   - The latest arrangement that ends in or after the current month is made
     open-ended. On staging that is Sara's, which ended in October.

## Consequences

- Ali starts in April 2026. Her terms can be set from April. The five January
  ALI10 orders stay under *belonging to nobody*: they are the ALI10 OLD
  model's, and attach to her only if she is ever registered with that code.
- A model whose discount was created after she really began (recreated, or set
  up late) starts late. Her profile's start field is the correction, as ADR
  0053 already says.
- An agreed raise from next month can no longer be entered ahead of time. It
  is entered once the month begins. The owner chose this.
- A model's terms never stop at the end of the current month by accident. To
  end an arrangement, a later month is given a different one once it begins.
- The migration's data changes are not reversed by its downgrade.

## Alternatives considered

- **Start both from *Active from*.** First proposed for ALI10. Refused by the
  owner: the earlier ALI10 orders were another model's, and *Active from* is
  copied by duplication.
- **Start from her first order with the code.** The first-order guess ADR 0053
  removed, and it would take the ALI10 OLD orders for Ali.
- **Keep months ahead but warn.** The owner was explicit that months that have
  not begun cannot be decided now.
