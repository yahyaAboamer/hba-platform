# Batch report — Phase 03C, wardrobes, rosters and feature requests

**Date:** 10 September 2026
**Branch:** `phase03c/wardrobes`, based on `main` @ `a577e03`
**Requested scope:** Active/All catalogue, grouped roster, shared profile, owned/incoming/failed items, size/images. Received/Processing server-filtered feature guidance; no completion or target actions. Correct replacement at product level.

**Delivered behaviour:** The wardrobe exists — on her phone and on her profile,
from the same records. Products has a real screen. Marketing can ask models to
feature a product, and only models who have it ever see the ask.

---

## Review

### Your answer, applied

> Anything that she bought? Then it's not shown in the wardrobe. We only return
> the products from the orders that have zero price.

Recorded as **D05**. The wardrobe is what HBA sent her, full stop. It has one
consequence that needed no second rule: **a purchase does not make her eligible
for a feature request either**, because eligibility reads the wardrobe.

One case your answer did not mention, decided the safe way: an order whose
original price **cannot be established** (which F04 warns is real for orders
first seen after a cancellation). Unknown is not zero, so it does not appear —
the platform would otherwise be telling a model she owns something it cannot
show HBA gave her.

### The hard part, and the test that proves it

W06 states it outright: *if only pants are resent, a previously failed T-shirt
stays Needs checking.*

A parcel with a T-shirt and trousers fails. HBA resends the trousers only, and
they arrive. A design built around **parcels** marks that second shipment
delivered and quietly says she has a T-shirt she does not have.

So the unit is **a product and a model**, never a parcel. Each pair takes the
state of its own most recent shipment, and the earlier attempts stay readable
underneath — a failed delivery is still evidence HBA tried, which is what a
model actually asks about.

"Most recent" is by **when the order was placed**, not by row id. A backfill
inserts history out of order, and row id would make the oldest parcel look like
the newest and mark a delivered item failed. Tested directly.

### What the owner should try

**On a phone, as a model — the Wardrobe tab:**
- What she has, with pictures and sizes.
- Below it, a compact *Not with you yet*: on its way, or *did not arrive — HBA
  is looking into it*. **A failed item is shown and never hidden** (W08) — she
  was told something was sent and has to be able to see what happened.
- **No Done button** on anything. W09: it is guidance, not a task list.

**On a laptop — Products:**
- Active by default, *All products* includes draft and archived. A product
  archived in Shopify is still in somebody's wardrobe.
- Open one: sizes, then **Received · Processing · Needs checking · Not sent**,
  every model in one of the four, names alphabetical, each linking to the one
  shared profile.
- **Ask models to feature this** — write it, show it, hide it, remove it. It
  says how many models can actually see it, because a request written for a
  garment nobody has is a request nobody reads.

**On a model's profile:** *What HBA has sent her* — the same records her own
screen reads, from literally the same function.

### Approved-design deviations

**None.** The exports' wardrobe and roster shapes are what this follows.

---

## Engineering evidence

**Rules and IDs covered:** W01, W02, W06, W08, W09, W10, D05. **UI12, UI13,
UI16, UI17, UI18** delivered. UI14 partially (the roster links to the profile;
a shipment-detail view is not built). UI15 delivered. UI19 is 07B.

### Files changed

| File | What |
|---|---|
| `app/services/wardrobe.py` | **New.** `wardrobe_for`, `roster_for`, `holds_product`, `eligible_requests`, the request CRUD |
| `app/models/promotions.py` + migration `a2f47b8e1c53` | **New.** One request per product, nothing per model |
| `app/api/products.py` | **New.** Catalogue, product detail with roster, feature request PUT/DELETE |
| `app/api/affiliate_self.py` | `GET /api/me/wardrobe` |
| `app/api/affiliates.py` | `GET /api/affiliates/{id}/wardrobe` |
| `frontend/…/MyWardrobe.tsx`, `Products.tsx` + CSS | **New.** Both screens |
| `frontend/…/AffiliatePortal.tsx`, `App.tsx` | Two `NotBuiltYet` placeholders replaced by real screens |
| `frontend/…/AffiliateDetail.tsx` | The wardrobe panel |
| `frontend/src/lib/api.ts` | **`api.del`** — the platform's first DELETE |
| `tests/test_wardrobe.py` | **New**, 22 tests |
| `tests/test_reachability.py` | The products router and the `del` verb, both added deliberately |

### Four decisions worth naming

**One request per product, and nothing per model.** W09 lists what this must not
become: *no model Done button, acknowledgement, completion tracking or automatic
target change.* A table with a row per model per request is how it becomes all
four, so there is not one. The audience is computed from her wardrobe every time
it is asked (W10) — a stored audience would be wrong the moment a replacement
shipped.

**Hiding and removing are different verbs.** W09 names three; hiding keeps the
wording for later and removing withdraws it. Collapsing them loses a paragraph
somebody wrote.

**Eligibility is server-side, and that is not a detail.** Filtering in the
browser would still hand every request to every model through the API. W10's
audience is *received or processing* — so a failed-only model drops out and a
replacement puts her back, with nothing stored and nothing to re-run.

**A deleted product is still hers.** The line item carries its own title and
size from 03A, so the entry is complete without a catalogue row. It has no
picture, and the interface draws an honest gap rather than a broken frame.

### The guard caught two real gaps

`test_every_capability_has_a_way_in` failed on **`DELETE /api/products/{}/feature-request`**
and **`GET /api/affiliates/{}/wardrobe`** — two endpoints I had written with no
control to reach them. Both were built rather than exempted: the *Remove it*
button, and the wardrobe panel on the profile.

Reaching the first needed **`api.del`**, the platform's first DELETE from the
interface, which meant adding the verb to the client *and* to the guard's own
map. Worth stating why that is safe: nothing this platform records about money
is ever removed — approvals, transfers, allocations and destinations are
append-only and trigger-guarded. A request to feature a garment is not that.

### Commands, results, environment

| Check | Result |
|---|---|
| `pytest -q --color=no` against `hba_platform_test` | **1716 passed**, exit 0 — 1694 on `main`, **22 new** |
| `cd frontend && npm test` | **198 passed**, exit 0 — 190 before; the accent and payout guards walk the new files |
| `cd frontend && npm run build` | exit 0 |
| `test_reachability.py` | Passes, after building both missing controls |

### Visual comparison — not performed

Automation still cannot sign in. **Four new screens are unseen**: the model's
Wardrobe tab, Products, one product's roster, and the wardrobe panel on a
profile. This is the one thing that keeps accumulating, and 03C is the batch
where it matters most — it is almost entirely interface.

**They will look empty on staging until a catalogue is read and a scan is run**,
because nothing has been matched yet. Settings → Shopify & data does both.

---

## Continuation

### Limitations

- **Line items are still not fetched.** `sync_order_line_items` exists from 03A
  and has no caller, so a matched parcel has no products in it yet and every
  wardrobe will be empty on real data. **This is the next thing to build** and
  it is small: the scan already knows which orders matched, so it should fetch
  lines for those and no others.
- **No shipment-detail screen** (part of UI14). The roster links to the model;
  it does not yet link to the parcel.
- **No staff resolution path** for an ambiguous match beyond the list itself
  (W12's *bounded staff path*).
- **The `unknown` classification is invisible** to staff — it is excluded from
  the wardrobe and does not appear in the unmatched list, because it *did*
  match. It needs a line somewhere before real data arrives.

### Decisions recorded

**D05** — the wardrobe is what HBA sent. Nine of the eleven decisions are now
answered; **D01** (which months are settled externally) and **D02, D03, D04,
D08, D09, D10** remain, each due at its own phase.

### Next

Two candidates, and I would do the first:

1. **Fetch line items for matched parcels** — a short, self-contained piece
   that turns every wardrobe from empty to real. Properly the tail of 03A/03B.
2. **Phase 04** — targets.

### Live changes

**None.** No Shopify call, no deployment, no production branch moved.
