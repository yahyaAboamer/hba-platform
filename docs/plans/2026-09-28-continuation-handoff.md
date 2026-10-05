> **Superseded by `2026-09-30-continuation-handoff.md`.** Kept for its record
> of batches O and P; its data follow-ups are moot after the 29 September reset.

# Where the work is — 28 September 2026 (batches O and P)

**Replaces `2026-09-27-continuation-handoff.md`**, which is kept with a banner
for its record of batches K–N, the tooling notes and the open items it lists.
Everything in its *Remaining*, *Release gates*, *Decisions not to reopen* and
*Needs the owner* still stands unless this file says otherwise.

## 29 September addendum — model account (You)

The owner approved the You redesign and its linked pages, then explicitly
authorized the notification and guide refinements plus a push and merge to
`main` for staging. Production remains out of scope. This batch groups terms,
payments, contact and delivery, sizes, notifications and appearance on the
account page. The technical Help entry is replaced by a plain-language
dashboard guide; the old `/glossary` route remains for existing links.

Payment destination changes still use the password-confirmed server flow.
Payment history and receipts remain available for paused models. Terms are
labelled for the server's working month, and missing terms or an abroad payment
arrangement have explicit states. Notifications now have padded headings,
loading and retry states. Local frontend verification: 538 tests across 33
files, production build green, and synthetic-data visual checks at 360, 390 and
1280 pixels with no browser errors or horizontal overflow. These checks do not
establish staging acceptance; check the staging deployment and real model
session separately.

## The exact position

Read on 28 September; re-read the remote before describing it
(`git ls-remote --heads origin main production`).

| | |
|---|---|
| **Branch** | `repair/batch-2` |
| **Batch O base** | `383bff2` (handoff after batch O tests) |
| **`origin/repair/batch-2` before batch P push** | `170c52c` (UI/UX Pro Max skill and batch O handoff correction) |
| **`origin/main` before batch P merge** (staging) | `170c52c`. Batch O was merged by the owner at `383bff2` on 28 September; recheck remote and deployment before stating the live staging version |
| **`origin/production`** | `156e65b`, unchanged since 26 September |
| **Migration head** | `f4a2b8d10005` (batch O, ADR 0051) ← `e3f1a9c70004` ← `d7a2c4e10003` ← … ; up/down/up rehearsed on the disposable database |
| **Backend** | **89/89 files** through `run-suite.sh` at `ccdcf32`; two failed first (`test_order_products`, `test_shopify_refresh`), both test-only updates for the intended change, both re-run green and committed in `7913c79` |
| **Frontend after batch P** | **520 tests, 32 files**, all passing; `npm run build` green. Mobile browser checked at 390px and 360px against a guarded local database: no page errors or horizontal overflow; Wardrobe feature jump and full Ranking control worked. Screenshots: `docs/repair/batch-2/visual/shots/batch-p/` |

## Standing restrictions

Unchanged: merge and deployment are separate permissions given each time;
historical finalisation locked; no destructive fixture against staging or
production; production not read.

## Batch P — model portal tabs

The owner approved the Wardrobe, Targets and Ranking concepts on 28 September,
including changing the approved HTML hierarchy to match the improved Home and
Orders tabs, and explicitly authorized a push and merge to **staging**. This
supersedes batch O's decision to place Wardrobe best sellers first.

- **Wardrobe:** received pieces and incoming gifts come first, feature requests
  next, best sellers last. Section buttons jump within the page. Gift cards
  show delivery state; best-seller sales are explicitly identified as product
  sales, not the model's payout. The best-seller error and retry stay intact.
- **Targets:** current progress and a visible, carefully worded pay note replace
  the hidden info button. An unrecorded result is never called a shortfall;
  missing counts display as a dash. The history remains newest first.
- **Ranking:** the model sees her own sales and position, nearby models before
  the top three, then an optional full board. Other models' sales remain private;
  their visible use counts only break sales ties.
- The standalone concept HTML and two concept PNGs are in `docs/design/`.
  Browser captures from the implementation use synthetic local data and have
  no customer information. The local visual seed now fills the original price
  field used by batch O's gift rule.

The `main` push triggers staging deployment; **production is not authorized**.
Before a staging acceptance claim, check deployment health and inspect the
three tabs there with authorized model sessions. Local visual verification is
not evidence of staging data or migrations.

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

## What happens when batch O reaches staging

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

1. **Confirm batch P reached `main` and staging.** Batch O was merged on 28
   September. The owner or an authorized session still needs to run *Match
   parcels from 2026-01-01* as described above; the merge authorization does
   not itself run that data job. The six-hourly re-read first runs six hours
   after the new version started, not at deploy (`schedule.py`).
2. **Verify batch O on staging**: Mazen's Wardrobe (received, on the way, best
   sellers once his orders' products are read), #22369 / #29499 delivered,
   and the staff list. **Check #29936** (FITBROS10, an E-stebdal exchange): at
   16:49 the portal showed 4 products, *On its way*, EGP 765.09 net sales,
   because nothing had re-read it yet. Shopify showed F1 delivered 6 Sep 17:45,
   COD 859.19 settled then, and an exchange fulfilment created 7 Sep 13:42.
   Expected after line fill and re-read: **2 original products**, **Delivered**,
   net sales **EGP 764.19** (859.19 less 95 shipping), commission **EGP 76.42**,
   final. If still in flight next day, read F1's stored `displayStatus` and
   `deliveredAt` in `order_index.fulfilments` first.
3. **Staging visual acceptance of batch P:** inspect Wardrobe, Targets and
   Ranking with authorized model sessions after the batch O matching step.
4. **Owner decision (ADR 0051, *not decided here*):** orders already *earned*
   with a base read after their return (imported after it). Rule 1 says their
   base is the cash at delivery; earned is final, so nothing rewrites them.
   After the resync fills `paid_by_delivery_piastres`, count them and the
   difference, and bring it to the owner.
5. **Model deletion.** None exists (archive only). The owner asked for a way to
   remove test models; recommended for testing: clear the test models' phones
   (they share the owner's number and make his parcels ambiguous). A real
   delete, for models with no money history only, is a future feature.
6. **Leftover audit groups** the owner said to leave: orders with a return but
   no recorded delivery, failed-then-refulfilled, split shipments (#19177,
   #17542) - all older than a month except #20497.
7. Everything in the 27 September handoff's *Remaining* list, from 0 onward.
8. **`orders_audit.md`** (formerly repo root, untracked, customer names and addresses):
   archived privately during the owner-authorised 4 October cleanup; its exact
   bytes are preserved in the [private evidence archive](../cleanup/archive-index.md).
   Never commit the archive or restored scratchpad. This replaces the earlier
   instruction to delete it when staging editing was finished.

## Release gates

As 27 September, with `f4a2b8d10005` added to the migrations to rehearse on a
restored copy (additive: three nullable columns; its downgrade drops them).

## Decisions not to reopen (added in O)

- **ADR 0051's two rules**, as the owner approved them. A post-delivery
  fulfilment is ignored only on an order with a return.
- **The frozen money is the payments up to delivery** (twelve-hour grace), not
  any order total.
- **Gift = the order's original price is zero**, read when the wardrobe reads.
- **Wardrobe's owner-approved batch P hierarchy is received pieces, requests,
  then her own best sellers.** The received section shows only products she
  holds, while incoming gifts are clearly separate inside that section.
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
