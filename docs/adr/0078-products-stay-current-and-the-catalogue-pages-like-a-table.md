# 0078. Products stay current, sort by coverage, and page like a table

**Status:** Accepted
**Date:** 2026-11-09
**Amends:** W01 (the catalogue), the approved export's catalogue pager

## Context

On 9 November 2026 the owner said new products and edited ones were not
reaching the dashboard, asked to sort products by how many models received
them, and sent a screenshot of the pager he wants: *Rows per page [50] ·
1–50 of 1103 · ‹ ›*. The catalogue was read only when somebody pressed
*Read the catalogue* in Settings.

## Decision

- **A product created or edited in Shopify is re-read at once.** The webhook
  receiver accepts `products/create` and `products/update` and queues one
  `shopify_sync_product` job per product (several saves are one read).
  `products/delete` is not acted on: a product that left the shop is still in
  somebody's wardrobe, as an archived one is.
- **The whole catalogue is read daily** (`schedule.SCHEDULE`), the backstop
  for a delivery that never arrived or a topic nobody subscribed to.
- **Refresh products** on the catalogue, for anyone who may manage models,
  reads it now. Because the daily read waits as a pending job under the same
  dedupe key, *now* brings that job forward rather than queueing a second;
  Settings' button does the same.
- **Sort**: *Name, A–Z* (default), *Most received*, *Fewest received*, over
  the whole shop by the coverage column's own count.
- **Pager**: rows per page 10 / 25 / 50 / 100 (default 50, remembered in the
  browser), the range, and previous/next arrows — replacing the export's ten
  rows with *Previous* and *Next*. A deliberate divergence from the approved
  export, on the owner's explicit instruction.

## Consequences

- Webhooks only arrive once the topics are subscribed in the Shopify Dev
  Dashboard (`docs/shopify-webhooks.md`); until then the daily read and the
  button carry it.
- No migration.
