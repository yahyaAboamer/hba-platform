# 0072. Each Khazenly run is kept, and customer service can run it too

**Status:** Accepted. Amends 0071 (decisions 1 and 8)
**Date:** 2026-11-01

## Context

The Khazenly tab (ADR 0071) went live on 1 November 2026, and the owner
used it on production that day. Two things followed from using it.

- **Nobody could see the last run.** The summary — orders read, which went
  in the file and which were left out, and why — showed once and was gone.
  The audit trail kept only who ran it and two counts. The team could not
  answer "when did we last confirm on Khazenly, and which orders went in?"
- **Customer service confirms the orders.** They answer customers in the
  Inbox and tag orders in Shopify; building the Khazenly file is the next
  step of the same job. ADR 0071 gave the tab to `order_ops.view` only —
  the operations manager and the admin.

## Decision

1. **Every file built is kept as a run.** Each time an export is read and
   matched — whether or not anything was confirmed — the platform stores the
   same summary the screen shows: when, who, when Shopify's tags were read,
   the counts, the file's name, the confirmed orders and the left-out orders
   by reason. Orders are stored **by number only** (Shopify's and
   Khazenly's), as the summary shows them; a merchant order cell that is not
   an order number is neither shown nor kept. Nothing else from the export is
   kept: not the file, not a name, not an amount. A refused upload is not a
   run and is not kept. Runs are kept indefinitely; each is a few kilobytes.
   This replaces ADR 0071's "only counts are kept" (decision 8). The audit
   entry stays as it was.

2. **The Khazenly tab shows the history**, newest first, under the upload:
   the latest 60 runs (older ones are kept, not listed). Each run opens to
   the same summary, the confirmed orders included. The
   file itself is not offered again from the history: Shopify's tags will
   have moved on since, and a file confirming orders should only ever come
   from tags read in the last few minutes.

3. **A permission of its own, `khazenly.use`.** The tab and its routes
   (`/api/khazenly`) are behind it, not behind `order_ops.view`. It is held by
   **customer service, the operations manager and the admin**.

4. **Customer service sees Operations with one section: Khazenly.** A
   department's section may now name its own permission. Someone who holds a
   section's permission but not the department's sees the department with
   only that section. Customer service therefore sees *Operations → Khazenly*
   and none of Shopify, Bosta, E-stebdal or WhatsApp, and no Operations
   numbers on Today. A department seen only in part does not count towards
   starting on Today, so customer service still starts in the Inbox.

5. The run table, `ops_khazenly_run`, belongs to Operations (ADR 0066).

## Consequences

- "When did we last confirm, and which orders?" is answered on the tab.
- Order numbers of every run are now stored. They identify orders, not
  people; the names in the export are still never read.
- Customer service can build a file that confirms orders for shipping. That
  is a real power: it is exactly what they did by hand on Khazenly's own
  dashboard, and the file still only ever confirms what Shopify says is
  confirmed.
- RULES.md's "Nobody but him and an admin sees Operations" and "Customer
  service sees the inbox and nothing else" now have an exception: the
  Khazenly section.
- The frame learns one new idea, a section with its own permission. It is
  used only here.

## Alternatives considered

- **Moving the tab into the Inbox.** Customer service already work there,
  but the owner put it in Operations, and the operations manager would then
  depend on holding the Inbox to reach it.
- **The tab in both places.** Two addresses for one screen, and the operations
  manager and the admin would see it twice.
- **Giving customer service `order_ops.view`.** It would show them every
  Operations number, which they were deliberately kept from (ADR 0057).
- **Keeping the history in the audit trail.** The trail is read by
  department and kind, a sentence per entry; an order list does not belong
  in it, and its append-only masking rules are for a different purpose.
- **Offering the file again from the history.** Rejected in decision 2.
