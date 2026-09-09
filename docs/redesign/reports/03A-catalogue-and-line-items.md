# Batch report — Phase 03A, catalogue, variants, media and line items

**Date:** 10 September 2026
**Branch:** `phase03a/catalogue-and-address`, based on `main` @ `864d04d`

**Note on the baseline number:** this branch is cut from `main`, which carries
02A and 02B but **not 02C** — that is still on `phase02c/setup-readiness`,
pushed and unmerged. So the count below starts from 1620, not from 02C's 1637.
The two touch different files and do not conflict; merging 02C first would put
the total at 1659.

**Requested scope:** Read catalog, variants, media and line items. Configured API schema, paginated durable sync. Verify all-orders/protected-field access; no writes to Shopify orders. New recipient field denial cannot break existing commission sync. Stable product/variant IDs, historical fallback and freshness metadata.

**Delivered behaviour:** The platform can now read what HBA sells and what was
in each order — the two things a wardrobe is built from, and the largest gap
the baseline found. Nothing about commission changed.

---

## Review

### An owner answer arrived mid-batch and corrected me

On the shipping address:

> It's a protected data for the models. But the admins can see it because these
> are the data that will be used when creating their orders. So her address is
> the one that we use to put inside the order details.

**I had this backwards.** The 02B report said the shipping address "belongs with
recipient matching in Phase 03, where a shipping address is a Shopify fact
rather than a profile field."

It is not a Shopify fact. **HBA types it into the order.** The platform is the
source and Shopify holds the copy — which inverts the direction of W03's
matching and makes it far stronger than the package assumed: the shipping phone
on a parcel is not a stranger's data being reverse-engineered into an identity,
it is a value HBA put there from a record HBA holds.

Recorded as **D11** (`decisions/D11-…md`), including who may edit it — **both
sides**, unlike measurements. It is implemented in **03B**, with the matching it
feeds; putting it here would have been scope creep into a batch that does not
read it.

### The `read_products` scope — one thing to check

You said you had added it. The platform's own code already warns why that is not
the end of the question:

> Editing the scope field in the Dev Dashboard only saves a draft: the change
> takes effect when a new app version is released and approved on the store, and
> **an already-issued token never gains a scope retroactively.**

So *added* and *granted* are different claims. **Settings → Shopify & data →
the scopes check** answers it against a fresh token. `read_products` is now in
the required set, so if it is not granted the check will say so by name.

I have not run it against the real shop — this environment has no Shopify
credentials configured (`shopify: {configured: false}`), and I would not point
it at the shared shop uninvited.

### What the owner should try

1. **Settings → Shopify & data.** There is a new **Product catalogue** block. It
   says what has been read and, more importantly, **when** — a catalogue nobody
   has synced for a fortnight looks identical to a fresh one until it says so.
2. **Press "Read the catalogue."** It is safe against the shared shop, unlike
   the import above it: the import is a bulk operation and Shopify allows one
   per shop; this is ordinary paginated reads. Running it twice is an upsert.
3. If the scope is not actually granted, it will refuse **by name** rather than
   reporting "0 products" — which is the version of this failure that costs an
   afternoon, because it is indistinguishable from an empty shop.

### Approved-design deviations

**None.** This batch has no screen of its own; the catalogue's own views are 03C.

---

## Engineering evidence

**Rules and IDs covered:** W01 (stable ids, retired products, colour-in-name /
size-as-variant), W11 (real line items with quantities and after-discount
values), F01 unchanged. UI12–UI20 remain **Not started** — this is the data
underneath them.

### Files changed

| File | What |
|---|---|
| `app/models/catalogue.py` | **New.** `Product`, `ProductVariant`, `OrderLineItem` |
| `migrations/…e7c2a5f1b930…py` | **New.** Three tables, additive; nothing existing changes |
| `app/services/shopify/catalogue.py` | **New.** Normalisers, idempotent upserts, the paginated walk, the job, `catalogue_state` |
| `app/services/shopify/queries.py` | `PRODUCT_FIELDS`, `PRODUCTS_PAGE`, `ORDER_LINE_ITEMS` |
| `app/services/shopify/client.py` | `read_products` added to `REQUIRED_SCOPES`, with why "added" ≠ "granted" |
| `app/services/jobs.py` | `SYNC_CATALOGUE` |
| `app/core/signals.py` + `docs/limits.md` | `catalogue_product_skipped`, documented as the repo requires |
| `app/api/operations.py` | `POST /sync-catalogue`, `GET /catalogue` |
| `frontend/src/screens/DataPanel.tsx` | The catalogue block and its freshness line |
| `tests/test_shopify_catalogue.py` | **New**, 22 tests |
| `tests/test_operations_api.py` | Scope fixtures carry the new requirement |
| `docs/redesign/decisions/D11-…md` | **New.** The shipping-address answer |

**No change to commission.** Not one line of `commission/`, `sync.py`,
`normalise.py`'s order path, or `order_index`.

### The separation that is the point of this batch

03A's prompt: *new recipient field denial cannot break existing commission sync.*

GraphQL rejects an **entire document** when one field is wrong, and
`ORDER_FIELDS` runs on every webhook. Bolting a product selection onto it would
risk stopping order ingestion outright in order to gain a wardrobe.

So: **separate documents, separate functions, separate job kind.** If Shopify
refuses a product field tomorrow, the catalogue goes stale and orders keep
indexing. That is structural rather than careful — there is no shared document
to get wrong.

### Four decisions worth naming

**A line item carries its own title and variant title.** W01 asks that historical
wardrobe items stay accessible when a product is no longer sold. A product
renamed in March must not rewrite what a model was sent in January, and a
product deleted from Shopify must not turn her wardrobe into a list of blanks.
The ids come along for the live join; the row does not depend on it surviving.
Both are nullable for the same reason.

**Both prices are kept.** W11 wants after-discount values, and the original is
the only evidence a discount applied at all. Where Shopify reports no original,
it falls back to the discounted value — which says *nothing was taken off*, true,
rather than *this was free*, not.

**A malformed product costs that product, not the page.** It is skipped, counted,
and reported through `catalogue_product_skipped` with an entry in `limits.md`,
because the repo's own rule is that a name added to `Anomaly` gets one.

**Nothing here can hold customer data.** A structural test reads the *columns*
of all three tables against a list of forbidden names, so it fails when somebody
adds a place to put a phone number rather than when somebody fills one in. The
recipient phone W03 matches on belongs to 03B's restricted path and to nothing
else.

### Commands, results, environment

| Check | Result |
|---|---|
| `pytest -q --color=no` against `hba_platform_test` | **1642 passed**, exit 0 — 1620 on this branch's base, **22 new** |
| `cd frontend && npm test` | **190 passed**, exit 0 |
| `cd frontend && npm run build` | exit 0 |
| `test_reachability.py` | Passes — both new routes have a way in from Settings |

**A second guard failed on purpose.** `test_the_required_scopes_are_the_ones_this_phase_needs`
pins the whole scope set, so it breaks when anybody adds one rather than when
they add a wrong one. Asking for a scope means asking the business to release a
new app version and get it approved on the store — not free, and not reversible
for an already-issued token. Updated with the reason beside each entry.

Fixtures are the shape Shopify actually returns: GIDs beside legacy ids, money
as decimal strings inside `shopMoney`, `nodes` connections. A normaliser tested
against a tidier shape than the API produces is one that passes here and fails
on the shop.

### Not verified against the real shop

**No Shopify call was made.** This environment has no credentials configured,
and the prompt is explicit: *do not start a staging import against the shared
production shop.* The scope check and the first catalogue read are yours to run
from Settings, and the platform will name what it finds.

### Visual comparison — not performed

Four batches now. Browser sign-in through automation still will not submit. The
new catalogue block is built, type-checked and unseen.

---

## Continuation

### Limitations

- **Line items are not fetched anywhere yet.** `sync_order_line_items` exists,
  is tested, and has no caller: attaching it to a job belongs with 03B, where
  matching decides *which* orders are worth reading lines for. Fetching lines
  for every order in the shop to build twenty wardrobes would be the wrong
  trade.
- **No backfill.** Reading history is 03B's resumable job.
- **One image per product**, not a gallery. The roster shows a thumbnail and
  storing every media node would be storing what nothing reads.
- **A hundred variants and a hundred lines per page.** Beyond that the line-item
  read reports `truncated` rather than silently keeping the first hundred — an
  order that large is not something HBA ships, but a wardrobe wrong invisibly is
  worse than one that says so.

### Decisions recorded

**D11** — her address is a profile field, and both sides edit it. It changes
what 03B is, which is why it is written down now rather than when 03B starts.

**Still open, and not an owner question:** whether Shopify's Admin API will
actually return `shippingAddress.phone` to this app. That depends on Shopify's
protected customer data approval, not on HBA's internal policy — the two are
easy to conflate and expensive to conflate. `/api/operations/order-facts` is the
route that establishes it, against the real shop.

### Next

**Phase 03B** — recipient matching and product history. It starts with D11's
columns and the protected-field check above.

### Live changes

**None.** No Shopify call, no deployment, no production branch moved, no
financial data touched. The branch is local and unpushed.
