# 0050 — An opened order shows what was in it, and three facts

**Status:** accepted — a recorded divergence from the approved export
**Date:** 2026-09-27
**Related:** `frontend/src/screens/MyOrders.tsx`, `MyOrders.css`;
`app/services/commission/attribute.py` (`_read_its_products`);
`app/services/recipients.py` (`FILL_LINE_ITEMS`); `app/services/portal.py`
(`describe_variant`); migration `e3f1a9c70004`; `tests/test_order_products.py`,
`screens/__tests__/MyOrders.test.tsx`, `OrdersParity.test.tsx`

## The situation

The owner, 27 September: an opened order should show *the products with
their size*, better wording and better information; he opened the whole Orders
page to improvement, through a mockup he approves (the rule since batch L).

Two facts found on the way, both read from staging and HBA's real Shopify
store rather than assumed:

- **No attributed order had its products.** 6,943 attributed orders, zero
  line items. Only the webhook path ever asked Shopify for an order's lines,
  and staging receives its orders through the history import and the
  reconciliation sweep, neither of which did.
- **The size is not the variant title.** `variantTitle` is the option values
  run together ("XL", "M / Black"), SKUs are empty, and the catalogue names
  its size option 32 ways ("Size", "size", "Sizs", "T-shirt Size",
  "BLACK HBA CLUB PUMP COVER (Size)"). Only `variant.selectedOptions` (name and
  value, `read_products`) says which value is the size.

## Decision

**Products.**

- `attribute_order` asks for an order's lines the moment the order becomes a
  model's, so every way in - webhook, history import, reconciliation, a
  code's backfill - is covered. Deduped on the key every caller already uses.
- An hourly sweep (`fill_missing_line_items`) queues the read for attributed
  orders with no lines, or with lines read before options were; 500 a run,
  newest first. A deleted variant is stored as `[]` and not asked about again.
- `order_line_item.selected_options` (JSONB, nullable; migration
  `e3f1a9c70004`) keeps Shopify's options as returned. The server decides the
  size: the value whose option name contains "siz"; every other value follows.
  Without options the variant title is shown as it is and nothing is called a
  size - "Black" alone is a colour.

**An opened order.** Each product: its name, then *Size XL · Black · Qty 2*,
then its price. Then three facts in place of the export's sentence -
**Delivery** (the date, *On its way*, *Failed*, *Cancelled before delivery*,
*Refunded before delivery*), **Commission** (*10% of net sales*, or *Not
earned*), **Counted in** (the month, or *Not counted*). The why - the export's
own pending sentence, a month agreed on delivered orders only, a failure after
approval, a carried-forward order, a missing rate - sits behind an ⓘ beside
*Counted in* (the owner's choice), the export's own info pattern, at 24px.

**The page.** A row answers a tap (`:active`); a chevron on the pill's line
says it opens and turns when it has; the detail fades in (off under reduced
motion); loading is the page's own shape; an empty month still open says
*Orders appear here as soon as someone uses your code at checkout*; the chosen
filter is kept in the address (`?status=`, replaced, not pushed); a focused row
scrolls clear of the header and the tab bar; a cancelled order's figure reads
*at checkout*.

## What it costs

- The opened order no longer matches the export's sentence. The export stays
  the reference for everything this ADR does not name.
- One more migration on the release-gate rehearsal list (`e3f1a9c70004`,
  additive; downgrade drops the column).
- About 7,000 Shopify reads to fill staging, paced by the client's throttle
  handling and the 500-an-hour sweep. An order Shopify no longer has returns no
  lines and is asked about again each hour, bounded by the batch.
- Rejected: an earned total at the top of Orders (summed rows can miss the
  approved total by rounding, and Home already shows the real one); search,
  sorting and swipe actions; product images, for now.
