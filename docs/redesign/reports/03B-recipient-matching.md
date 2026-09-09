# Batch report — Phase 03B, recipient matching and her address

**Date:** 10 September 2026
**Branch:** `phase03b/recipient-matching`, based on `main` @ `33939da`
**Requested scope:** Normalised shipping phone in a separate restricted path, original gift/purchase basis, matching provenance and unresolved state. Resumable backfill from January; no full-store query per screen; idempotent/reordered events. Preserve old model links after phone changes.

**Delivered behaviour:** The platform can now work out **which parcels went to
which model** — and D11's address, which is the thing it matches against.

---

## Review

### The two questions this batch keeps apart

**Attribution** asks who *sold* an order: a discount code on it. **Matching**
asks who it was *sent to*: the phone on the parcel. They are unrelated, and
conflating them would be the worst bug in this phase — a model can sell a
hundred orders she never touched, and receive a parcel bought under nobody's
code.

D11 is what makes the second answerable at all:

> Her address is the one that we use to put inside the order details.

HBA types it. So matching compares a stored phone against a phone HBA's own
staff typed from that record — not a stranger's data reverse-engineered into an
identity.

### What the owner should try

1. **Open a model's profile → "Parcels go to".** Record her address. If the
   phone is not an Egyptian mobile it refuses, and says why — it is the number
   a parcel is matched back to her by.
2. **On her phone, You → "Where we send things".** She can edit the same
   address. **Both sides**, per D11, unlike her measurements.
3. **Settings → Shopify & data → "Match parcels from 2026-01-01".** It works
   through the history a few pages at a time and carries on by itself. Safe
   against the shared shop — ordinary paginated reads, not a bulk operation.
4. Below that, any parcel it **could not** attach appears with the reason.
   Usually empty, and that is correct.

### One thing that will only be known on the real shop

`shippingAddress.phone` is **protected customer data**. Shopify gates it behind
an app-level approval that is *separate from any scope*, so a shop granting
every scope can still return `null`.

D11 answered HBA's own policy — who inside HBA may see and edit an address. It
did not, and could not, answer whether Shopify will hand the field to this app.
The two are easy to conflate and expensive to conflate.

**How you will know:** run the scan. If every parcel comes back `no_phone`,
the field is being withheld rather than absent. `/api/operations/order-facts`
asks the shop directly and is the definitive check.

### Approved-design deviations

**None.** No screen in the exports covers matching; the wardrobe views it feeds
are 03C.

---

## Engineering evidence

**Rules and IDs covered:** W03, W04, W05 (backfill), W12 (bounded staff path),
D11. UI20 partially — the unmatched list exists; UI13–UI19 are 03C.

### Files changed

| File | What |
|---|---|
| `app/services/recipients.py` | **New.** Normalisation, matching, classification, recording, the resumable scan, its job |
| `app/models/shipments.py` | **New.** `ModelShipment`, `Classification` |
| `migrations/…f1a93d6c48e2…py` | **New.** Seven address columns + `model_shipment` |
| `app/models/affiliates.py` | The seven shipping columns, with D11's reasoning |
| `app/services/affiliates.py` | `SHIPPING_FIELDS`, `update_shipping_address` |
| `app/services/shopify/queries.py` | `ORDERS_RECIPIENT_PAGE` — the narrowest document in the file |
| `app/services/jobs.py` | `SCAN_RECIPIENTS` |
| `app/api/affiliates.py`, `affiliate_self.py` | Address on both sides; `PUT /api/me/shipping-address` |
| `app/api/operations.py` | `POST /scan-recipients`, `GET /unmatched-parcels` |
| `frontend/…AffiliateDetail, MyDetails, DataPanel` + CSS | Address editors both sides; the scan control and unmatched list |
| `tests/test_recipients.py` | **New**, 35 tests |
| `tests/test_portal_api.py` | The writable-routes guard, updated deliberately |

### Six decisions worth naming

**A number that cannot normalise becomes `None`, not a best guess.** Two
unusable numbers normalising to the same wrong thing would match two different
people to each other. Unmatched is a state the platform can show and act on;
wrongly matched is not. Arabic-Indic digits *are* translated — a phone typed on
an Arabic keyboard is the same number, and refusing it would refuse a real model.

**Ambiguity is refused, never resolved.** Two models sharing a number is a data
problem somebody must look at. Picking one puts a parcel in the wrong woman's
wardrobe and nothing downstream would question it.

**A confirmed match survives her changing her phone** (W03). Once a row names a
model, a later pass leaves it alone. She may move, change her number or leave —
none of that changes which parcel arrived at her door in March. An *unmatched*
row is re-decided every time, which is exactly W05's *a model joining later can
acquire links to earlier orders*, and there is a test for each direction.

**Classification reads the original net, never the current one** (W04). Shopify
zeroes current totals on cancellation; reading those would record a parcel she
paid for as one HBA gave her, in her wardrobe, permanently. `None` stays
*unknown* and is **not** a gift — this decides whether something is hers.

**The scan is resumable, five pages a run.** A whole history in one handler
holds a lease for minutes and loses everything if it dies at the end. Each run
commits its slice and queues the next with its cursor — **in the dedupe key**,
because a shared key would silently drop the second slice and report success.

**The unmatched list is not a work queue.** Most unmatched orders are ordinary
customers and always will be. A missing phone is recorded and *not* listed;
only real ambiguities and near-misses surface. A backlog of a thousand rows
that were never HBA's parcels is worse than no list.

### The boundary held

`order_index` and `attributed_order` are untouched. A structural test reads
their **columns** against `recipient_token`, `shipping_phone`, `phone`, `email`
and `customer_name`, so it fails when somebody adds a place to put one rather
than when somebody fills one in.

**And the honest part:** a normalised Egyptian mobile is *not* anonymous, and
nothing here claims it is. `BACKEND_CONTRACTS.md` warns against exactly that
claim. What protects it is that the column lives on one permission-gated table
and appears in no model payload — not that the value is unreadable.

### Commands, results, environment

| Check | Result |
|---|---|
| `pytest -q --color=no` against `hba_platform_test` | **1694 passed**, exit 0 — 1659 on `main`, **35 new** |
| `cd frontend && npm test` | **190 passed**, exit 0 |
| `cd frontend && npm run build` | exit 0 |
| `test_reachability.py` | Passes — both new operations routes reach from Settings |

**The writable-routes guard failed again, correctly.** Her address is a new
thing she can write, so `test_nothing_about_a_target_can_be_changed_from_their_side`
broke. Updated with the reason beside each of the four, including why only one
of them asks for a password: the payout destination is where *money* goes, and
demanding a password before she corrects a house number teaches her to type it
into anything that asks.

### Not verified against the real shop

**No Shopify call was made.** No credentials in this environment, and the shared
shop is not somewhere to experiment. The scan is driven in tests by a fake
client returning Shopify's own payload shape.

### Visual comparison

Not performed by the agent — automation still cannot sign in. The owner
confirmed the previous five screens on staging on 10 September; **the four new
ones here have not been seen**: the two address editors, the matching control
and the unmatched list.

---

## Continuation

### Limitations

- **Line items are still not fetched per shipment.** `sync_order_line_items`
  exists from 03A and has no caller. Attaching it belongs with 03C, where a
  wardrobe actually needs the products — fetching lines for every order in the
  shop to build twenty wardrobes would be the wrong trade.
- **Nothing shows a wardrobe yet.** That is 03C, and it is what all of this was
  for.
- **No replacement logic** (W06's *if only pants are resent, a previously
  failed T-shirt stays Needs checking*). Needs per-product shipment state, which
  needs the line items above.
- **D05 is unanswered** and will block part of 03C: whether a personal purchase
  appears in the same wardrobe. The classification is recorded either way, so
  nothing is lost by deciding late.

### Decisions recorded

None new. **D11 is now implemented**, not merely recorded.

### Next

**Phase 03C** — the product roster, both wardrobes, and passive feature
requests. It needs **D05** answered before the personal-purchase half.

### Live changes

**None.** No Shopify call, no deployment, no production branch moved, no
financial data touched.
