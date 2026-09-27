# 0048 — The model's Home goes past the approved export

**Status:** accepted — a recorded divergence from the approved export
**Date:** 2026-09-27
**Related:** `app/services/home.py`, `GET /api/me/home/{month}`;
`frontend/src/screens/MyMonth.tsx`, `Home.css`;
`frontend/src/components/MonthSheet.tsx`; `AffiliateLayout.tsx` (tab icons,
code chip); `MyPayments.tsx` (*Coming up*); `tests/test_home.py`,
`screens/__tests__/Home.test.tsx`

## The situation

Home matched the approved export and still left the owner's own questions
unanswered: the month named three times, *when am I paid* below the fold, 16
code uses beside 10 + 3 + 0 with nothing to explain the gap, red on a zero,
and a chart that arrived after the page. The owner, 27 September:

> I don't mind changing things on the approved design if they are better. I
> am offering you the flexibility to give me better UX and also UI and
> architecture.

He saw a mockup and chose: all three tiles (rank, average order, content), bars
for both charts, the fourth order state, and a like-for-like comparison.

## Decision

- **One request.** `GET /api/me/home/{month}` gathers what Home draws from the
  functions each figure's own screen already reads. Home paints once.
- **Structure**: the month once, as the control that opens a bottom sheet
  (shared with Orders and Ranking); earned and *next payment* in one card;
  orders with **every outcome** - cancelled and refunded join delivered,
  pending and failed, so the parts add up to the uses (D03 unchanged: a use is
  every order but a failed delivery); three tiles; best seller; *Share your
  code* as Shopify's discount link; the year as bars for sales and uses.
- **The comparison is like for like** (the owner's rule): a running month
  against the same days of the one before, in Cairo days, a shorter month
  stopping at its last day, none when last month sold nothing. Worked out on
  the server (docs/RULES.md: nothing about money in the browser).
- **An ended month nobody approved reads *Awaiting approval***, not *in
  progress*.
- **Wording**: *Earned so far*, *Next payment · Around 3 October*, *N% vs 1–27
  Aug*, *Share your code*, *Coming up* / *No payments recorded here yet*.

## What it costs

- The screen no longer matches its export, on purpose. The export stays the
  reference for everything this ADR does not name.
- *Share your code* uses Shopify's `/discount/<CODE>` link on the connection's
  shop domain; it needs checking once against the live shop.
- A second filled button (Share) outside `.auth` - ADR 0047's divergence,
  extended to the one action Home exists to prompt.
