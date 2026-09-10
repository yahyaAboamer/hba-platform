# Batch report — what was in the parcel

**Date:** 10 September 2026
**Branch:** `feat/parcel-contents`, based on `main` @ `517b913`
**Requested scope:** The tail of 03A/03B. `sync_order_line_items` existed from 03A and nothing called it, so a matched parcel had nothing in it and **every wardrobe was empty however much had been sent.**

**Delivered behaviour:** A parcel matched to a model now has its contents read,
and a parcel that ships today is matched without anybody re-running anything.

---

## Review

### Two gaps, and they were the same gap

**Nothing read what was inside a parcel.** 03A built the reader; 03B built the
matcher; neither called the other. So the wardrobe screens 03C built were
correct and permanently empty.

**Nothing matched a parcel that arrived after the last scan.** W05 asks for
*backfill from January **and** live matching*. Only the backfill existed — a
parcel shipping this morning would sit unmatched until somebody pressed the
button again.

### What it does now

**A parcel that matches gets read** — and **only** one that matches. The great
majority of the shop's orders are customers, and reading every line of every
order to build twenty wardrobes is the wrong trade. Both the bulk scan and the
live path queue that read the same way.

**An order that indexes gets matched**, as its own job, queued *after* the index
is written. That ordering is the point: matching needs a protected Shopify
field, and a denial of that field must never be able to stop an order being
indexed. Same separation 03A drew between the catalogue and commission, for the
same reason.

### What the owner should try

1. **Settings → Shopify & data → Match parcels from 2026-01-01.** Same button as
   before; it now queues a contents-read for every parcel it attaches.
2. Give the jobs a minute, then open a model who has been sent something. Her
   **Wardrobe** should have things in it — and her profile should show the same
   list under *What HBA has sent her*.
3. **A product's roster** should now put models in Received / Processing rather
   than all of them in Not sent.

**If wardrobes are still empty after the scan**, the likeliest cause is the one
flagged in 03B and still unconfirmed: Shopify may be withholding
`shippingAddress.phone` from this app. Nothing would match, so nothing would be
read. The unmatched list in Settings says which.

---

## Engineering evidence

**Rules and IDs covered:** W05 (live matching), W06 (a parcel's contents), W12.

### Files changed

| File | What |
|---|---|
| `app/services/jobs.py` | `MATCH_ORDER`, `SYNC_LINE_ITEMS` |
| `app/services/recipients.py` | `match_one_order`, both handlers, and the scan's enqueue |
| `app/services/shopify/queries.py` | `ORDER_RECIPIENT` — one order's shipping phone |
| `app/services/shopify/sync.py` | Queues a match after an order indexes |
| `app/core/signals.py` + `docs/limits.md` | `line_items_truncated`, documented as the repo requires |
| `tests/test_recipients.py` | 5 new |

**No migration. No API change. No new route**, so nothing new for the
reachability guard to catch — these are jobs, reached by the buttons that
already exist.

### Three decisions worth naming

**Its own job, not a call inside the scan.** A line-item read that fails must
not cost the page of matches around it, and the scan should not slow to
Shopify's pace per parcel. Deduped by order id, so a webhook, a sweep and a
backfill all reaching the same order queue one read.

**Live matching runs after indexing, never during.** `ORDER_FIELDS` is the
document every webhook depends on; the recipient query is separate so a
protected-field denial costs a wardrobe and never commission.

**Truncation is reported rather than hidden.** An order with more than a hundred
lines is not something HBA ships, but silently keeping the first hundred would
make a wardrobe wrong in a way nothing could see. `line_items_truncated` fires,
with a `limits.md` entry saying what to do — the cursor is already returned and
nothing consumes it yet, which is the fix if it ever happens.

### Commands, results, environment

| Check | Result |
|---|---|
| `pytest -q --color=no` against `hba_platform_test` | **1727 passed**, exit 0 — 1722 on `main`, **5 new** |
| `cd frontend && npm test` | **198 passed**, exit 0 |
| `cd frontend && npm run build` | exit 0 |

No frontend change in this piece — the screens were already right and had
nothing to show.

### Not verified against the real shop

No Shopify credentials here. The jobs are driven in tests by a fake client
returning Shopify's own payload shape; **whether the shop actually hands over
`shippingAddress.phone` is still the open question from 03B**, and running the
scan is what answers it.

---

## Continuation

### Limitations

- **A wardrobe only fills for parcels matched *after* this.** Parcels matched by
  an earlier scan have no queued read. Re-running the scan fixes them: an
  already-matched shipment is left alone, but the enqueue happens on every pass.
  Worth knowing rather than wondering.
- **No paging of line items.** A hundred per order, reported if exceeded.
- **The `unknown` classification is still invisible** to staff — excluded from
  the wardrobe, absent from the unmatched list because it *did* match. Still
  owed a line somewhere before real data arrives.

### Next

**Phase 04 — targets.** Not started; the owner asked to be told first.

### Live changes

**None.** No Shopify call, no deployment, no production branch moved.
