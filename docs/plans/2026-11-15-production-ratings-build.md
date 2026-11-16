# Production rebuild, batch 6a: ratings and the performance record (build plan)

Decision: `docs/adr/0084-production-is-rebuilt-around-the-production-order.md`
(decision 10). Approved screens: the supplier list (`#v-suppliers`) and one
supplier (`#v-supplier`: the "Usual lateness" figure, the "Orders and
ratings" card) in `docs/redesign/mockups/production-orders.html`. Batch 4
(Suppliers, `docs/plans/2026-11-14-production-suppliers-build.md`) built both
screens and left these parts out. Branch: `claude/production-ratings`.

Batch 6 is two pull requests: this one, then the factory's own login (6b),
which changes sign-in and is reviewed on its own.

## The owner's answers (15 November 2026)

- The rating form is **offered when an order is settled and can be
  skipped**; the owner can rate later from the order or the supplier page.
- Timing stars are **pre-filled from the real lateness** and can be changed:
  on time 5, 1-2 days late 4, 3-5 days 3, 6-9 days 2, 10 or more 1.
- The factory never sees ratings or its record (matters for 6b).

## Who is rated on an order

Once an order is **closed** (settled), each supplier that worked on it:
- the factory (`factory_id`), role `factory`;
- the outside print house (`print_supplier_id`, when printing is `outside`),
  role `print`;
- every supplier with a live (not voided) purchase for the order, role
  `materials` (a supplier that is also the factory appears once, as the
  factory).

A cancelled order is never rated.

## Data

New table `prod_rating`: `id`, `order_id` (FK `prod_order.id`), `supplier_id`
(FK `production_supplier.id`), `quality`, `timing`, `dealing` (smallint, each
1..5, check constraint), `note` (nullable text, up to 1000), `created_by`,
`created_at`, `updated_by`, `updated_at`. Unique (`order_id`,
`supplier_id`). One migration after `b8d5f1a30035`, id ending `0036`, with a
`downgrade()` that refuses while any row exists. Update the head-revision
assertions in `tests/test_prod_orders.py` and `tests/test_prod_tasks.py` (and
any other test that pins the head).

A rating can be changed later by the owner (edited in place, audited:
`production.rating_saved`, subject `production:order:{id}`, an
`after.summary` sentence naming the supplier and the three stars, never the
note). There is no delete.

## The record, calculated, never typed

Per supplier:
- **Lateness per job.** As the factory: the order's `lateness_days` (batch 1)
  once its warehouse receipt is done. As a materials supplier: for each
  received purchase with an expected date, `max(0, received_on -
  expected_on)`. A print house's own lateness is not known (no dates are
  kept for it) unless it has purchases.
- **Usual lateness**: the median of the supplier's last 10 known lateness
  figures (finished orders and received purchases together, newest first),
  rounded to whole days; null with none. Said "usually on time" (0),
  "usually N days late".
- **Reject rate** (factories only): rejected / cut over its closed orders,
  one decimal per cent; per order on the supplier page.
- **Ratings**: the average of each of quality, timing, dealing over the
  supplier's ratings, one decimal, with the count; null when not rated.

## Timing suggestion

For each supplier on a closed order: the factory's lateness is the order's
`lateness_days`; a materials supplier's is the largest lateness of its
received purchases for that order; a print house without purchases has none
(no suggestion, the owner picks). Stars from days: 0 → 5, 1-2 → 4, 3-5 → 3,
6-9 → 2, 10+ → 1.

## API (`/api/prod`)

- `GET /orders/{id}/ratings` (`production.view`): `{ratable: bool,
  suppliers: [{supplier: {id, name}, role, lateness_days | null,
  suggested_timing | null, rating: {quality, timing, dealing, note,
  updated_at} | null}]}`. `ratable` is true only for a closed order.
- `PUT /orders/{id}/ratings/{supplier_id}` (`production.owner`): `{quality,
  timing, dealing, note}`; 409 when the order is not closed, 404 when the
  supplier is not on the order.
- Supplier list rows (`GET /suppliers`) gain `ratings: {quality, timing,
  dealing, count} | null` and `usual_lateness_days: int | null`.
- Supplier page (`GET /suppliers/{id}`) gains the same two, and each of its
  orders gains `lateness_days`, `reject_rate` (factory only, closed orders),
  `closed_on`, and `rating` (as above, or null). Its orders list must also
  include orders the supplier sold materials for (role `materials`), not
  only factory and print.

**No money in any of it**: ratings and the record are visible with
`production.view` (the QC manager sees them, as the mockup says). Keep the
recursive no-money test for viewer and staff on every changed endpoint.

## Screens

- **Settling**: after the owner settles an order, the order page opens a
  "Rate the suppliers" panel: one block per supplier (name, role, "6 days
  late" / "on time"), three 1-5 star choices (quality, timing, dealing,
  timing pre-filled from the suggestion), an optional note, Save; and "Skip
  for now". The panel can be opened again on a closed order ("Rate the
  suppliers" / "Change ratings") by the owner. Stars are real radio buttons
  with labels ("4 of 5"), 44px targets, not colour alone.
- **Order page**, closed order: a "Ratings" card listing each supplier's
  stars and note, or "Not rated yet".
- **Supplier list**: under each supplier, the mockup's line "Quality 4.0 ★ ·
  Timing 2.5 ★ · Dealing 4.5 ★ · usually 5 days late", or "Not rated yet"
  (with the lateness words when known).
- **Supplier page**: the fourth figure "Usual lateness" ("5 days", refused
  colour when > 0, "On time", or "Not known yet"); the card becomes "Orders
  and ratings" as in the mockup: per order "PO code · closed 30 Oct · 2 days
  late · 1.2% rejected", the note in quotes, the stars on the right, or for
  the owner a "Rate it" button on a closed unrated order, or "Rate it when
  the order is settled" on an open one. The QC manager sees the same without
  buttons. The money figures stay owner-only as today.
- Phone first at 390 as in batches 1 to 5.

## Verification

- Backend `tests/test_prod_ratings.py`: who is on an order (factory, print
  house, materials, no duplicates, cancelled order not ratable), the
  suggestion table at each boundary (0, 1, 2, 3, 5, 6, 9, 10 days), save and
  change with audit, refusals (not closed 409, supplier not on order 404,
  stars outside 1..5 422, QC manager / viewer 403), the record (usual lateness
  median over the last 10, reject rate, averages), the supplier list and
  page fields, the migration's downgrade refusal, the no-money recursive
  check. Keep green: `test_prod_orders`, `test_prod_tasks`,
  `test_prod_incoming`, `test_prod_suppliers`, `test_prod_overview` (if
  merged), `test_migrations`, `test_reachability`, `test_permissions`,
  `test_several_roles`.
- Frontend: the rating panel after settling (pre-fill, skip, save, change),
  the order's Ratings card, the list line, the supplier page figure and
  card, per permission. `npm test`, `npm run build`.
- Browser: local throwaway DB, owner and QC manager, 1440 and 390.

## What was built (16 November 2026)

- Migration `c9e6a2b40036` (`prod_rating`); `services/ratings.py`; the two
  routes; the supplier list and page fields. Screens: `RatingForms.tsx` (the
  panel and the order's Ratings card), the list line, the supplier page's
  "Usual lateness" figure (the QC manager sees it too) and "Orders and
  ratings" card.
- Choices the contract left open:
  - The `PUT` answers with the order's sheet (the `GET`'s shape).
  - The factory's lateness on an order is known once its warehouse receipt
    is done; before that the order has no figure and no suggestion.
  - A factory that also sold materials for the order is rated once, as the
    factory, with the order's lateness; its purchases still count in its
    usual lateness.
  - The reject rate is shown per order only (no supplier-wide figure).
  - The supplier page's orders card keeps the role word ("Factory",
    "Materials") because it now also lists orders a supplier sold materials
    for; the mockup lists only the factory's.
  - `reject_rate` is a share of pieces, so the suppliers tests' no-money key
    check exempts that one key by name.
