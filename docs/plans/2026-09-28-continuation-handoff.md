# Where the work is — 28 September 2026 (batch O)

**Replaces `2026-09-27-continuation-handoff.md`**, which is kept with a banner
for its record of batches K–N, the tooling notes and the open items it lists.
Everything in its *Remaining*, *Release gates*, *Decisions not to reopen* and
*Needs the owner* still stands unless this file says otherwise.

## The exact position

Read on 28 September; re-read the remote before describing it
(`git ls-remote --heads origin main production`).

| | |
|---|---|
| **Branch** | `repair/batch-2` |
| **Last code commit** | `7913c79` (batch O's tests). This handoff is committed after it: `git rev-parse --short HEAD` |
| **`origin/repair/batch-2`** | Level with `origin/main` (fast-forwarded 28 September, evening) |
| **`origin/main`** (staging) | Batch O merged by the owner at `383bff2` (28 September, 16:24 +03:00), so **batch O is on staging**. The commit after it adds the UI/UX Pro Max skill and this correction only, no app code |
| **`origin/production`** | `156e65b`, unchanged since 26 September |
| **Migration head** | `f4a2b8d10005` (batch O, ADR 0051) ← `e3f1a9c70004` ← `d7a2c4e10003` ← … ; up/down/up rehearsed on the disposable database |
| **Backend** | **89/89 files** through `run-suite.sh` at `ccdcf32`; two failed first (`test_order_products`, `test_shopify_refresh`), both test-only updates for the intended change, both re-run green and committed in `7913c79` |
| **Frontend** | **511 tests, 31 files**, all passing; `npm run build` green |

## Standing restrictions

Unchanged: merge and deployment are separate permissions given each time;
historical finalisation locked; no destructive fixture against staging or
production; production not read.

## What batch O is (commits `ed79531`, `ccdcf32`, `7913c79`)

The owner asked why Mazen's Wardrobe was empty. Four causes, one per section
plus one underneath, and a delivery defect found on the way (`docs/limits.md`,
*Delivered orders stuck in flight*):

- **ADR 0051 - a return freezes the order; a cancelled fulfilment carries
  nothing** (owner-approved 28 September, from a read-only audit of all 1,114
  orders staging held in flight). Delivery ignores cancelled fulfilments and,
  on an order with a return, fulfilments created after the first delivery
  (E-stebdal exchanges). An order with a return not already final is locked at
  the **cash paid by delivery** (from the payments; totals were wrong on 27% of
  audited orders). Exchange lines are marked `after_delivery` and left out of
  products, best sellers and the wardrobe. Rebuilt from Shopify's own history,
  so the answer is the same whenever the order was first seen.
- **Matching.** The sweep and the import queue a parcel match over what they
  indexed; a new or changed phone collects parcels already stored for it
  (`rematch_for`); archived models take no new parcels.
- **Gift decided when read**, from the order's price, not the label stored at
  match time (every label on staging was *unknown*).
- **`RESYNC_IN_FLIGHT`** re-reads every undelivered order six-hourly;
  `order_index.fulfilments` keeps each fulfilment's facts.
- **Staff list** *Shipped, and nobody will report on it* (Settings → Shopify &
  sync → Technical detail): orders over 14 days old with no tracking, another
  courier, or Bosta silent, each linking to Shopify to be marked delivered or
  cancelled there.

Review: one code-review pass (no money or correctness findings; one contract
point - the sweep committed mid-handler - fixed in `ccdcf32`).

## What happens when batch O reaches staging (needs the owner's go-ahead)

1. The migration adds three nullable columns.
2. **The owner (or a session he authorises) clicks *Match parcels from
   2026-01-01*** under Settings → Shopify & sync → Technical detail, once. It
   re-checks every stored parcel and reads orders since 10 September that were
   never scanned. Mazen's six gifts (#16910, #21689, #22369, #27288, #28413,
   #28994) attach to him then; nothing else re-checks a model who already
   existed.
3. Within six hours `RESYNC_IN_FLIGHT` re-reads the ~1,100 undelivered orders
   under the new rules: expect ~673 of the 675 *delivered-but-in-flight* to
   become delivered, the 12 cancelled-then-failed to become failed, and the
   staff list to fill.
4. The hourly line-item fill reads the parcels' products and re-reads lines
   stored before `after_delivery` existed.
5. Then the Wardrobe can be checked signed in as Mazen, and the UI/UX review
   the owner asked for runs against real data.

The same click is needed on production when batch O is promoted.

## Remaining, in order

1. ~~Owner: merge batch O to `main`~~ - **done, 28 September.** Still owed:
   the owner's *Match parcels from 2026-01-01* click (step 2 above). The six-hourly
   re-read's first run is six hours after the new version started, not at deploy
   (`schedule.py`: a restart never triggers a sweep).
   **The check that proves it, #29936** (FITBROS10, an E-stebdal exchange): at
   16:49 the portal showed 4 products, *On its way*, EGP 765.09 net sales, because
   nothing had re-read it yet. The owner's Shopify timeline shows F1 delivered
   6 Sep 17:45 (Bosta's *shipment delivered* email), COD 859.19 settled the same
   minute, and the exchange fulfilment created 7 Sep 13:42. Expected after the
   line fill and the re-read: **2 products** (the original jersey and compression;
   the exchange lines `after_delivery = true`), **Delivered**, net sales
   **EGP 764.19** (859.19 paid by delivery less 95 shipping), commission
   **EGP 76.42**, final. If it is still in flight the next day, read F1's stored
   `displayStatus`/`deliveredAt` in `order_index.fulfilments` before anything else.
2. **Verify on staging**: Mazen's Wardrobe (received, on the way, best
   sellers once his orders' products are read), #22369 / #29499 delivered,
   the staff list.
3. **The owner is revising the Targets and Ranking tabs** in a new session meanwhile
   (28 September), with UI/UX Pro Max, which is now vendored in
   `.claude/skills/ui-ux-pro-max/` (see `CLAUDE.md`). Findings and options come to
   him before anything is built.
4. **UI/UX Pro Max review of the Wardrobe tab** - the owner's request of 28
   September, deliberately after real data is visible.
5. **Owner decision (ADR 0051, *not decided here*):** orders already *earned*
   with a base read after their return (imported after it). Rule 1 says their
   base is the cash at delivery; earned is final, so nothing rewrites them.
   After the resync fills `paid_by_delivery_piastres`, count them and the
   difference, and bring it to the owner.
6. **Model deletion.** None exists (archive only). The owner asked for a way to
   remove test models; recommended for testing: clear the test models' phones
   (they share the owner's number and make his parcels ambiguous). A real
   delete, for models with no money history only, is a future feature.
7. **Leftover audit groups** the owner said to leave: orders with a return but
   no recorded delivery, failed-then-refulfilled, split shipments (#19177,
   #17542) - all older than a month except #20497.
8. Everything in the 27 September handoff's *Remaining* list, from 0 onward.
9. **`orders_audit.md`** (repo root, untracked, customer names and addresses):
   delete when staging editing is finished - the owner's instruction. Never
   commit it.

## Release gates

As 27 September, with `f4a2b8d10005` added to the migrations to rehearse on a
restored copy (additive: three nullable columns; its downgrade drops them).

## Decisions not to reopen (added in O)

- **ADR 0051's two rules**, as the owner approved them. A post-delivery
  fulfilment is ignored only on an order with a return.
- **The frozen money is the payments up to delivery** (twelve-hour grace), not
  any order total.
- **Gift = the order's original price is zero**, read when the wardrobe reads.
- **Wardrobe section 1 is her own best sellers; section 2 shows only products
  she holds** (owner, 28 September - both confirmed).
- **The platform never marks an order delivered itself.** No tracking or
  another courier is resolved in Shopify; the staff list only shows them.
- **Parcel matching is its own job**, never inline in the sweep.

## What went wrong, so the next session does not repeat it

- **Rules applied at observation time.** "Locked when we see it delivered"
  made the answer depend on when the platform happened to look. Prefer facts
  Shopify keeps (timestamps, payments) over the moment of reading.
- **A label decided once, read for ever.** The gift label was frozen before
  its input existed. Derive at the point of use when the input can change.
- **Paths that write but do not trigger.** Only the webhook matched; staging
  has no webhooks. When adding a follow-on step, list every path that writes
  the thing it follows.
