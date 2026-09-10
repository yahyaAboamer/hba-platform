# Batch report — making the product screens load

**Date:** 10 September 2026
**Branch:** `perf/product-screens`, based on `main` @ `16cce25`
**Requested scope:** Not from the package. The owner walked Phase 03 on staging, approved it, and reported one thing: *"it's just taking too much to load because we have so many products."*

**Delivered behaviour:** Four fixes, in the order they cost. Nothing about what
any screen says changed — only how much work it does to say it.

---

## Review

### Why it was slow, in the order it mattered

**1. Full-size photographs in a grid of thumbnails.** A Shopify product image is
commonly 2000px and several hundred kilobytes. The list asked for the original
of every one. Sixty products is tens of megabytes to draw a page of cards the
size of a playing card.

Shopify's CDN resizes on request, so asking for a 400px version is free — and
**not** asking is what the screen was doing. This is almost certainly most of
what you felt.

**2. Everything at once.** The list handed back up to 500 products in one
response, which is fine on a shop with twelve and is the problem on a shop with
hundreds. It is 60 a page now, with *Show 60 more*, and the count says *60 of
340* rather than implying sixty is all there is.

**3. A request per keystroke.** Typing "dress" fired five searches, four of them
stale before they returned — and on a real catalogue each one is a database
query and a page of images. It now waits a third of a second after you stop
typing.

**4. Two loops that queried per row.** The wardrobe asked the database for one
parcel's contents, then for one product, then repeated — a model with a year of
parcels cost hundreds of round trips. The product roster asked *"does this
parcel contain this product"* once per parcel in the whole shop.

Both are now single queries. **This is the one that would have got worse
silently**: it is invisible on a seeded database with three orders and grows
with the business.

### What did not change

No screen says anything different. No figure, no state, no rule. The
`image_url` a product detail page uses is still the full-size one — only grids
ask for thumbnails.

---

## Engineering evidence

### Files changed

| File | What |
|---|---|
| `app/services/wardrobe.py` | `_gift_lines` replaces `_gift_shipments`: one joined query instead of a loop. `_products_by_id` batches the catalogue lookup. `thumbnail()` added |
| `app/api/products.py` | `limit`/`offset` with `total`; list rows carry a sized image |
| `frontend/src/screens/Products.tsx` + `.css` | Debounced search, paged grid, *Show N more* |
| `frontend/src/screens/MyWardrobe.tsx` | Uses `image_thumb_url` |
| `tests/test_wardrobe.py` | 6 new: four on the thumbnail rule, two counting queries |

**No migration, no API contract removed.** `offset`, `total` and
`image_thumb_url` are additions; every existing field is still there.

### The guard that matters

Two tests **count SQL statements** rather than timing anything. A timing test on
a laptop proves nothing, and the failure being guarded is a *shape*: six parcels
must not cost thirteen queries, and sixty must not cost a hundred and
twenty-one.

That is the difference between a bug this catches and one that reappears the
next time somebody writes a loop over shipments — which is a natural thing to
write, and reads perfectly well until there is data in the shop.

### The thumbnail rule is narrow on purpose

It rewrites **only** `cdn.shopify.com`, **only** by adding a documented query
parameter, and leaves alone any URL that already carries a width. Guessing at a
foreign host's resizing scheme produces a broken image rather than a smaller
one, and a broken product photograph is worse than a slow one.

### Commands, results, environment

| Check | Result |
|---|---|
| `pytest -q --color=no` against `hba_platform_test` | **1722 passed**, exit 0 — 1716 on `main`, **6 new** |
| `cd frontend && npm test` | **198 passed**, exit 0 |
| `cd frontend && npm run build` | exit 0 |

The local Postgres container had stopped between sessions; restarted, identity
re-checked as `hba_platform_test` before pytest touched it.

### Not measured against the real catalogue

**I have no numbers from your shop.** No Shopify credentials in this
environment, and the fixes were reasoned from the code rather than from a
profile of staging.

The query-count reduction is proven by test. The image saving is arithmetic —
400px instead of 2000px is roughly a twenty-fifth of the pixels — but *how much
faster the screen feels* depends on how many products you have and what the
connection is like.

**Confirmed on staging by the owner, 10 September**, walking the real
catalogue: reported correct and no longer slow. So the guess was right, and it
was still a guess — if it ever regresses, measure rather than guess again.

---

## Continuation

### Limitations

- **Still no line items fetched**, so wardrobes remain empty on real data. That
  is unchanged from 03C and it is still the next thing.
- **No index on `product.title`** for the search. `ILIKE '%…%'` cannot use a
  plain index anyway; if search becomes slow the answer is a trigram index, and
  it is not worth adding before it is a problem.
- The product **detail** page is one query for the roster and one for the
  models. It does not page the roster, because a roster is twenty models.

### Next

**Fetch line items for matched parcels** — the piece that turns every wardrobe
from empty to real. Then Phase 04, targets.

### Live changes

**None.** No deployment, no production branch moved, no Shopify call.
