# Production rebuild, batch 4: Suppliers (build plan)

Decision: `docs/adr/0084-production-is-rebuilt-around-the-production-order.md`
(decision 9). Approved screens: the `#v-suppliers`, `#v-supplier`, `#v-pay`
and `#v-purchase` views in `docs/redesign/mockups/production-orders.html`
(sample data). Batches 1 to 3 are merged: `app/modules/production/orders/`,
`frontend/src/departments/production/next/`, and their contracts in
`docs/plans/`. Branch: `claude/production-suppliers`.

Where this file and the ADR disagree, the ADR wins; say so and stop.

## Scope

Suppliers by section, each supplier's page, purchases, the supplier's running
account, and recording payments. Screens at `/production/next/suppliers`,
`/production/next/suppliers/:id`.

Not in this batch: ratings and the lateness / reject record (batch 6),
comparing suppliers, the factory's login, Overview, carrying old data over
beyond the section mapping below. The old framed tab keeps working: its code,
its API and `tests/test_production_api.py` are untouched.

## The supplier itself

Suppliers stay in the existing `production_supplier` table (orders already
point at it, and the old tab reads it). **Do not alter or drop that table or
`production_supplier_category`.** The new screens read and write these of its
columns only: `id`, `code`, `name`, `contact_person`, `phone`, `whatsapp`,
`city`, `notes`, `active`, `updated_at`. A supplier made here gets a UUID
`id` and the next free `SUP-NNN` code, as the old tab does (see
`app/modules/production/services/actions.py::_create_supplier`), and leaves
`category_id` null. A supplier is never deleted here: it is made inactive.

## New tables (one migration, id ending `0035`, revises `a7c4e9f20034`)

Money is integer piastres with CHECK constraints (ADR 0002).

`prod_section` — the owner's sections. `id`, `name` (unique, 1..60),
`position`, `created_by`, `created_at`, `deleted_at`. Seeded, in this order:
Manufacturers, Fabric, Printing houses, Accessories, Packaging.

`prod_supplier_section` — a supplier can be in several. `supplier_id`
(FK `production_supplier.id`), `section_id`, unique together.

The migration also places today's suppliers: for each supplier with a
`category_id`, by its category's name (case-insensitive): contains
"manufactur" -> Manufacturers; "fabric" -> Fabric; "print" -> Printing
houses; "accessor" or "trim" -> Accessories; "packag" -> Packaging; anything
else -> a section with that category's own name, created if missing. Nothing
is lost; the owner can rename or remove sections afterwards.

`prod_purchase` — something HBA bought. `id`, `supplier_id`, `order_id`
(nullable FK `prod_order.id`), `item` (1..200), `quantity` (Numeric(12,3),
> 0), `unit` (`kg` | `m` | `piece`), `unit_price_piastres` (> 0),
`total_piastres` (> 0; quantity x unit price, rounded half up to a whole
piastre, computed by the server), `cost_part` (`fabric` | `printing` |
`accessories` | `packaging` | `other`), `expected_on` (nullable date),
`received_on` (nullable date), `note`, `voided_at`, `voided_by`,
`void_reason`, `created_by`, `created_at`.

`prod_supplier_entry` — the supplier's account. **Append-only**: a line is
never changed or deleted; a mistake is undone by a reversing line. Follow the
platform's precedent for an append-only ledger
(`migrations/versions/6285abebe4ed_payment_ledger.py`,
`c16349c64e62_append_only_guards.py`): a database trigger refuses UPDATE and
DELETE. `id`, `supplier_id`, `kind` (`opening` | `purchase` | `work` |
`payment` | `adjustment`), `amount_piastres` (signed, never 0: positive means
HBA owes more, negative means HBA owes less), `happened_on` (date),
`order_id` (nullable), `purchase_id` (nullable), `method` (nullable:
`bank_transfer` | `cash` | `instapay` | `wallet` | `cheque`),
`payment_kind` (nullable: `weekly` | `deposit` | `final`), `note`,
`reverses_id` (nullable FK to this table, unique: a line is reversed once),
`created_by`, `created_at`.

`prod_supplier_receipt` — an optional photo of a payment. `entry_id` (unique
among live rows), `storage_key`, `mime_type`, `size_bytes`, `uploaded_by`,
`created_at`, `deleted_at`. Same bucket, sniffing and size limit as order
files; keys under `production/suppliers/{supplier_id}/`.

`downgrade()` refuses while any purchase or account line exists.

## Rules

1. **Sections.** Add by typing a name; rename; remove (soft) only when no
   supplier is in it. A supplier may be in any number, including none.
2. **Purchases** (owner). Supplier must be active; the order, if given, must
   be open. The total is computed, never typed. Saving a purchase writes one
   account line: `purchase`, `+total`, dated the purchase's day (a
   `bought_on` date in the request, not in the future, default today). An
   optional deposit paid now (0 < deposit <= total) writes a second line:
   `payment`, `-deposit`, `payment_kind = deposit`, with its method, tied to
   the purchase. The rest stays on the balance with no due date.
   A purchase's price, quantity, unit, supplier and order are never edited:
   it is **voided** with a reason (owner), which writes a reversing line for
   the purchase, and a voided purchase is shown struck through. **When a
   deposit stands on it, the void must say what became of the deposit**
   (`deposit_returned`, required then; ignored when no deposit stands).
   `true`: the supplier gave it back, so the deposit's line is reversed too.
   `false`: the supplier keeps it, so the deposit payment stays on the
   account and, with the purchase gone, the supplier holds that much of
   HBA's money as credit (the account reads "Overpaid"); the purchase then
   shows `deposit_kept`. *Built as recommended on 15 November 2026, awaiting
   the owner's confirmation.* Its `expected_on`, `received_on` and `note` can
   be changed; the QC manager can set `expected_on` and mark it received
   (`received_on`, not in the future), since materials arriving is his work.
   Neither date may be before the day the purchase was bought, and
   `PATCH /purchases/{id}` refuses any other field (422) instead of
   ignoring it.
   **Lines and dates.** A purchase date, a payment's date, an opening's
   date and an adjustment's date are not in the future and not more than 366
   days in the past (a typo guard). A receipt cannot be attached to a
   payment that has been reversed. Reversing a deposit payment that is tied
   to a live purchase stays allowed: the purchase then shows no deposit and
   the account's reversing line says it was the deposit of that purchase.
   A purchase task (rule 8) is not made for a purchase tied to a cancelled
   order.
3. **Payments** (owner). Amount > 0, date not in the future, a method, a kind
   (`weekly` | `deposit` | `final`), optional note, optional receipt photo
   (added with the payment or afterwards; replaceable; removable). A payment
   is a lump sum against the supplier, not an order. It writes one line:
   `payment`, `-amount`. A wrong payment is reversed with a reason (owner),
   never edited.
4. **Balance brought forward** (owner). One `opening` line per supplier
   (positive: HBA owes; negative: HBA has overpaid), dated; refused if the
   supplier already has an `opening` line that is not reversed. Any later
   correction is an `adjustment` line with a required note.
5. **Work on orders.** Settling an order (batch 1's `settle`) now also
   writes, in the same transaction, one `work` line on the factory's
   account: `+settled_payable_piastres`, dated the day it is settled, tied
   to the order. A settled payable of zero writes no line; a negative one
   writes a negative line.
   **Cancelling an order after cutting is done keeps what the factory has
   earned.** In the same transaction `cancel` writes one `work` line on the
   factory's account for the payable so far (batch 1's
   `settlement(...)["payable_piastres"]`; none at zero, a negative line when
   negative), dated the day of the cancel, tied to the order, noted
   "Cancelled after cutting", and freezes the figure on the order the way
   `settle` does (`settled_payable_piastres`, `settled_at`, `settled_by`)
   while `status` stays `cancelled`; the order page then shows the frozen
   figure to the owner, as "owed to the factory when the order was
   cancelled". Cancelling **before** cutting is done writes nothing. *Built
   as recommended on 15 November 2026, awaiting the owner's confirmation.*
   Once cutting is done the order's factory cannot change (`Locked`, 409:
   "The factory cannot change after cutting. Reopen cutting first."; the
   unchanged value is accepted), like who buys the fabric and printing.
   **Until an order is settled, its payable so far is not a ledger line.**
   It is worked out on each read from batch 1's `settlement` and shown on
   the factory's page as a line "so far, not settled", and it counts in what
   HBA owes now. Settling replaces it with the real line, so nothing is
   counted twice.
6. **What HBA owes a supplier now** = the sum of its account lines + the
   payable-so-far of its open orders (cutting done, not settled).
   **Held until pieces are fixed** = the sum of batch 1's `held_piastres`
   over the same open orders (already excluded from payable). A negative
   total reads "Overpaid".
7. **Cost from purchases.** A purchase tied to an order and a cost part
   never changes the order's typed costs by itself. The order's cost card
   shows, per part, "From purchases: EGP X per piece" (the live, unvoided
   purchases for that order and part, divided by pieces cut once cutting is
   done, else by pieces planned, rounded to a whole piastre) with a "Use
   this" button for the owner, which sets that part's actual cost through
   the existing edit. No money formula of batch 1 changes.
8. **Tasks.** A live purchase with `expected_on` before today and no
   `received_on` is a generated task: "Chase the <item> delivery", who
   `factory` (waiting on that supplier), due `expected_on`, `open`
   `purchase:<id>`; the Tasks button "Mark received" goes to
   `/production/next/suppliers/{supplier_id}?open=purchase:<id>`. A purchase
   expected today or later and not received is a task "Check <item> on
   arrival", who `qc`, due `expected_on`. Titles carry no money.
**Lock order.** Whenever a write involves a known order, the order's row
is locked `FOR UPDATE` first and the supplier's second: `settle` and
`cancel` (order, then factory) and, in the supplier module, adding a
purchase (which also re-checks the order is still open under that lock),
voiding one and reversing a line that has an order or a purchase with
one. A line with an `order_id` takes a key-share lock on the order
through its foreign key, so locking the supplier first could deadlock
with a `settle` or `cancel`. The rule is stated in the docstrings of
`services/suppliers.py` and `services/account.py`.
**No double entry by accident.** A payment, a purchase, an opening
balance or an adjustment identical to one the same person recorded for
the same supplier within the last 60 seconds is refused (`Locked`, 409:
"This looks like the same payment / purchase / correction recorded twice.
Wait a minute if it really is a second one."; for an opening, "balance
brought forward"). Payment: amount, date, method, kind. Purchase: item,
quantity, unit, unit price, order. Adjustment: amount, date, note.
Opening: amount, date. A line that was reversed, and a purchase that was
voided, no longer count. The check is made under the supplier's lock.
**A supplier cannot be made inactive** while it is the factory or print
house of an open order (422, in plain words, with no balance in it).
9. **Permissions.**
   - `production.view`: the supplier list and page **without money**: names,
     sections, contact, purchases as item / quantity / unit / dates only, no
     prices, totals, account, balance or payments (keys omitted, not null).
   - `production.edit` (the QC manager): set a purchase's expected date and
     mark it received.
   - `production.suppliers` (managers and the owner): add and edit a
     supplier, its sections, active or not; manage the section list.
   - `production.owner`: everything with money: purchases, payments,
     opening balance, adjustments, reversals, voids, receipts, and seeing
     any of it.
   A test must prove, recursively, that viewer, staff and manager responses
   carry no money on every endpoint here, including write responses, and
   that a receipt photo is served only to the owner.
10. **Audit.** Every write: `production.supplier_*`, `production.section_*`,
    `production.purchase_*`, `production.payment_*`; subject
    `production:supplier:{id}`; an `after.summary` sentence. Summaries carry
    no amounts (a non-owner reads the activity list).

## API (`/api/prod`, same conventions as batches 1 to 3)

- `GET /suppliers` — `{sections, suppliers}`; each supplier: id, code, name,
  sections, contact fields, active, `open_orders`, `open_purchases`
  (unreceived), and for the owner `owed_piastres`, `held_piastres`.
- `POST /suppliers`, `PATCH /suppliers/{id}` (`production.suppliers`).
- `GET /suppliers/{id}` — the supplier, its purchases, its orders (id, code,
  style, colour, stage, status), and for the owner `account` (lines newest
  first with a running "you owe" after each, the not-settled lines marked),
  `owed_piastres`, `held_piastres`, `paid_piastres` (payments this year).
- `POST /sections`, `PATCH /sections/{id}`, `DELETE /sections/{id}`
  (`production.suppliers`).
- `POST /suppliers/{id}/purchases` (owner); `PATCH /purchases/{id}`
  (expected_on, received_on, note: `production.edit`);
  `POST /purchases/{id}/void` (owner, reason, and `deposit_returned` when a
  deposit stands on the purchase).
- `POST /suppliers/{id}/payments` (owner);
  `POST /suppliers/{id}/opening` (owner);
  `POST /suppliers/{id}/adjustments` (owner);
  `POST /entries/{id}/reverse` (owner, reason; not for `work` lines).
- `POST /entries/{id}/receipt`, `GET /entries/{id}/receipt`,
  `DELETE /entries/{id}/receipt` (owner).
- `GET /orders/{id}` gains, for the owner, `cost.from_purchases`: per part,
  the per-piece figure and the purchases behind it.

## Screens (follow the mockup)

- **Suppliers** tab after Incoming. List: section chips with counts and
  "+ Add section"; rows with name, sections, open orders and purchases; for
  the owner what is owed ("You owe EGP …", "Overpaid EGP …", "Nothing
  owed"). "Add supplier" (`production.suppliers`), "Record a purchase"
  (owner). The mockup's ratings line is batch 6: leave it out.
- **Supplier page**: header with sections; for the owner the four figures
  (You owe now, Held until pieces are fixed, Paid this year; the mockup's
  "Usual lateness" is batch 6: show three figures) and "Record a payment";
  **Account** (date, what, amount, you owe after; not-settled lines marked;
  reversed lines struck through; each payment's receipt); **Purchases**
  (item, quantity and unit, order, expected and received dates, and for the
  owner price and total; "Mark received" for the QC manager; "Void" for the
  owner); **Orders** (links to the order); **Details** (contact, sections,
  notes, active; edit for `production.suppliers`).
- **Record a payment** and **Record a purchase** as inline panels, as the
  order page does: the purchase form computes the total and what is owed
  after the deposit as the person types; the payment form says what the
  balance will be after it. Pounds in, piastres out.
- `?open=purchase:<id>` on the supplier page opens that purchase's "Mark
  received" panel (from Tasks).
- The order page's **Cost per piece** card shows "From purchases" per part
  with "Use this" (owner). When the part is in what the factory is owed
  (manufacturing; printing when the factory prints; fabric when the factory
  bought it) "Use this" first says "This changes what the factory is owed
  for this order" and asks to confirm inline; other parts act at once.
- **Void** asks what became of a standing deposit (two plain answers, neither
  chosen for the owner, each with what the account will show). **Cancel
  order**, once cutting is done and for the owner, says what will go on the
  factory's account ("The factory keeps EGP X for the work already done; it
  goes on their account."). The edit form shows the factory read-only after
  cutting. A save button is disabled while a save is in flight.
- A person without `production.owner` sees no money and no money controls
  anywhere. Phone first where the QC manager works (purchases: mark
  received); 44px targets; no horizontal scroll at 390px; both themes.

## Verification

- Backend `tests/test_prod_suppliers.py`: the section mapping in the
  migration; supplier add / edit / sections; every purchase, payment,
  opening, adjustment, reversal and void rule; rounding; the append-only
  trigger; settle writing the `work` line once (and not at zero); owed and
  held with open orders, before and after settling, with no double count;
  from-purchases figures; the two generated tasks; receipts; the permission
  table; the recursive no-money check; audit summaries without amounts.
  Keep green: `test_prod_orders`, `test_prod_tasks`, `test_prod_incoming`,
  `test_migrations`, `test_reachability`, `test_permissions`,
  `test_several_roles`, `test_production_api`, `test_audit_by_department`.
- Frontend: tests for the list, the page as owner and as non-owner, both
  forms' arithmetic, void and reverse, mark received, `?open=`, and the cost
  card's "From purchases". `cd frontend && npm test`, `npm run build`.

## Response shapes (as built)
Generated from real responses of the built backend (one scenario on the main factory `fac`: a balance brought forward, a settled order, a purchase with a deposit, a payment with a receipt, a reversed adjustment, a voided purchase and an order not yet settled). Ids, dates and names are the scenario's; the shapes are exact. Everything is under `/api/prod`.
### Rules that hold for every response
- **Money is integer piastres**, in keys ending `_piastres`, and appears only for somebody holding `production.owner`. For anybody else the keys are **absent, not null**, on every route, a write's answer included. The money keys are: `owed_piastres`, `held_piastres`, `paid_piastres`, `paid_year`, `owed_total_piastres`, `has_opening`, `account` (the whole list), and on a purchase `unit_price_piastres`, `total_piastres`, `deposit_piastres`, `deposit_kept`, `void_reason`.
- A purchase's part is called **`part`** in the JSON (`fabric` | `printing` | `accessories` | `packaging` | `other`), not `cost_part`.
- A purchase's **`quantity` is a decimal string** (`"1075"`, `"12.5"`), never a float, so it survives exactly; send it as a number or a string.
- Dates are `YYYY-MM-DD`; moments are UTC ISO with `Z`.
- **Every write on a supplier answers `{"supplier": <the supplier's page as this person may see it>, ...}`** (plus `purchase_id` or `entry_id` where one was made), so a screen can replace its whole state with it. The section routes answer `{"sections": [...]}` (plus `section_id` / `deleted`).
- Refusals: a rule broken -> **422** with `{"detail": "<words a person can act on>"}`; something that has moved past changing (a purchase already voided, a line already reversed) -> **409**; an unknown supplier, section, purchase, line or receipt -> **404**; the wrong permission -> **403**. A refusal writes nothing.
- `production.view` reads (list, page); `production.suppliers` writes suppliers and sections; `production.edit` sets a purchase's expected date, note and arrival; everything else is `production.owner`.
### `GET /suppliers` as the owner
```json
{
  "sections": [
    {
      "id": 6,
      "name": "Manufacturers",
      "position": 1,
      "supplier_count": 1
    },
    {
      "id": 7,
      "name": "Fabric",
      "position": 2,
      "supplier_count": 1
    }
  ],
  "suppliers": [
    {
      "id": "fac",
      "code": "FAC",
      "name": "Main factory",
      "contact_person": null,
      "phone": null,
      "whatsapp": null,
      "city": "Cairo",
      "notes": null,
      "active": true,
      "sections": [
        {
          "id": 6,
          "name": "Manufacturers"
        }
      ],
      "open_orders": 1,
      "open_purchases": 2,
      "owed_piastres": 36343000,
      "held_piastres": 345000
    },
    {
      "id": "prt",
      "code": "PRT",
      "name": "Print house A",
      "contact_person": null,
      "phone": null,
      "whatsapp": null,
      "city": null,
      "notes": null,
      "active": true,
      "sections": [],
      "open_orders": 0,
      "open_purchases": 0,
      "owed_piastres": 0,
      "held_piastres": 0
    },
    {
      "id": "d07bc757-d032-4318-baa4-8de87621e501",
      "code": "SUP-004",
      "name": "Trims supplier",
      "contact_person": "Mona",
      "phone": "0100 000 0000",
      "whatsapp": "0100 000 0000",
      "city": "Giza",
      "notes": "Pays by InstaPay",
      "active": true,
      "sections": [
        {
          "id": 7,
          "name": "Fabric"
        }
      ],
      "open_orders": 0,
      "open_purchases": 0,
      "owed_piastres": 0,
      "held_piastres": 0
    },
    {
      "id": "old",
      "code": "OLD",
      "name": "Closed mill",
      "contact_person": null,
      "phone": null,
      "whatsapp": null,
      "city": null,
      "notes": null,
      "active": false,
      "sections": [],
      "open_orders": 0,
      "open_purchases": 0,
      "owed_piastres": 0,
      "held_piastres": 0
    }
  ],
  "unsectioned": 2,
  "owed_total_piastres": 36343000
}
```
`owed_piastres` negative means overpaid (the screen says "Overpaid EGP …"); zero reads "Nothing owed". `owed_total_piastres` is what is owed in total, leaving overpaid suppliers out. `unsectioned` counts suppliers in no section. `sections[].supplier_count` counts every supplier in it (active or not), as does the rule that a section is removed only when empty. Rows are active first, then by name.
### `GET /suppliers` as a viewer (staff and managers get the same)
```json
{
  "sections": [
    {
      "id": 6,
      "name": "Manufacturers",
      "position": 1,
      "supplier_count": 1
    },
    {
      "id": 7,
      "name": "Fabric",
      "position": 2,
      "supplier_count": 1
    }
  ],
  "suppliers": [
    {
      "id": "fac",
      "code": "FAC",
      "name": "Main factory",
      "contact_person": null,
      "phone": null,
      "whatsapp": null,
      "city": "Cairo",
      "notes": null,
      "active": true,
      "sections": [
        {
          "id": 6,
          "name": "Manufacturers"
        }
      ],
      "open_orders": 1,
      "open_purchases": 2
    },
    {
      "id": "prt",
      "code": "PRT",
      "name": "Print house A",
      "contact_person": null,
      "phone": null,
      "whatsapp": null,
      "city": null,
      "notes": null,
      "active": true,
      "sections": [],
      "open_orders": 0,
      "open_purchases": 0
    },
    {
      "id": "d07bc757-d032-4318-baa4-8de87621e501",
      "code": "SUP-004",
      "name": "Trims supplier",
      "contact_person": "Mona",
      "phone": "0100 000 0000",
      "whatsapp": "0100 000 0000",
      "city": "Giza",
      "notes": "Pays by InstaPay",
      "active": true,
      "sections": [
        {
          "id": 7,
          "name": "Fabric"
        }
      ],
      "open_orders": 0,
      "open_purchases": 0
    },
    {
      "id": "old",
      "code": "OLD",
      "name": "Closed mill",
      "contact_person": null,
      "phone": null,
      "whatsapp": null,
      "city": null,
      "notes": null,
      "active": false,
      "sections": [],
      "open_orders": 0,
      "open_purchases": 0
    }
  ],
  "unsectioned": 2
}
```
### `GET /suppliers/{id}` as the owner
```json
{
  "supplier": {
    "id": "fac",
    "code": "FAC",
    "name": "Main factory",
    "contact_person": null,
    "phone": null,
    "whatsapp": null,
    "city": "Cairo",
    "notes": null,
    "active": true,
    "sections": [
      {
        "id": 6,
        "name": "Manufacturers"
      }
    ],
    "open_orders": 1,
    "open_purchases": 2,
    "purchases": [
      {
        "id": 3,
        "supplier_id": "fac",
        "item": "Wrong thread",
        "quantity": "12.5",
        "unit": "kg",
        "part": "accessories",
        "order": null,
        "bought_on": "2026-11-15",
        "expected_on": null,
        "received_on": null,
        "note": null,
        "voided": true,
        "voided_at": "2026-11-14T22:22:57.791221Z",
        "unit_price_piastres": 4000,
        "total_piastres": 50000,
        "deposit_piastres": 0,
        "deposit_kept": false,
        "void_reason": "Wrong supplier"
      },
      {
        "id": 2,
        "supplier_id": "fac",
        "item": "Zips",
        "quantity": "1000",
        "unit": "piece",
        "part": "accessories",
        "order": {
          "id": 2,
          "code": "PO-2611-02",
          "style_name": "Oversized hoodie",
          "colour": "Black",
          "status": "open"
        },
        "bought_on": "2026-11-15",
        "expected_on": "2026-11-19",
        "received_on": null,
        "note": null,
        "voided": false,
        "voided_at": null,
        "unit_price_piastres": 300,
        "total_piastres": 300000,
        "deposit_piastres": 0,
        "deposit_kept": false,
        "void_reason": null
      },
      {
        "id": 1,
        "supplier_id": "fac",
        "item": "Heavy fleece, black",
        "quantity": "1075",
        "unit": "kg",
        "part": "fabric",
        "order": {
          "id": 2,
          "code": "PO-2611-02",
          "style_name": "Oversized hoodie",
          "colour": "Black",
          "status": "open"
        },
        "bought_on": "2026-11-09",
        "expected_on": "2026-11-12",
        "received_on": null,
        "note": "Pick up from the mill",
        "voided": false,
        "voided_at": null,
        "unit_price_piastres": 16000,
        "total_piastres": 17200000,
        "deposit_piastres": 4000000,
        "deposit_kept": false,
        "void_reason": null
      }
    ],
    "orders": [
      {
        "id": 2,
        "code": "PO-2611-02",
        "style_name": "Oversized hoodie",
        "colour": "Black",
        "status": "open",
        "role": "factory",
        "stage": {
          "key": "warehouse",
          "label": "Warehouse receipt",
          "position": 9
        }
      },
      {
        "id": 1,
        "code": "PO-2611-01",
        "style_name": "Oversized hoodie",
        "colour": "Black",
        "status": "closed",
        "role": "factory",
        "stage": null
      }
    ],
    "owed_piastres": 36343000,
    "held_piastres": 345000,
    "paid_piastres": 7000000,
    "paid_year": 2026,
    "has_opening": true,
    "account": [
      {
        "id": null,
        "kind": "work",
        "what": "Work on PO-2611-02 so far, not settled",
        "amount_piastres": 10649000,
        "balance_after_piastres": 36343000,
        "happened_on": null,
        "order": {
          "id": 2,
          "code": "PO-2611-02"
        },
        "purchase": null,
        "method": null,
        "payment_kind": null,
        "note": null,
        "reversal": false,
        "reverses_id": null,
        "reversed": false,
        "reversed_by_id": null,
        "not_settled": true,
        "receipt": null,
        "created_by": null,
        "created_at": null
      },
      {
        "id": 10,
        "kind": "purchase",
        "what": "Reversal · Purchase · Wrong thread",
        "amount_piastres": -50000,
        "balance_after_piastres": 25694000,
        "happened_on": "2026-11-15",
        "order": null,
        "purchase": {
          "id": 3,
          "item": "Wrong thread"
        },
        "method": null,
        "payment_kind": null,
        "note": "Wrong supplier",
        "reversal": true,
        "reverses_id": 9,
        "reversed": false,
        "reversed_by_id": null,
        "not_settled": false,
        "receipt": null,
        "created_by": "Owner",
        "created_at": "2026-11-14T22:22:57.771971Z"
      },
      {
        "id": 9,
        "kind": "purchase",
        "what": "Purchase · Wrong thread",
        "amount_piastres": 50000,
        "balance_after_piastres": 25744000,
        "happened_on": "2026-11-15",
        "order": null,
        "purchase": {
          "id": 3,
          "item": "Wrong thread"
        },
        "method": null,
        "payment_kind": null,
        "note": null,
        "reversal": false,
        "reverses_id": null,
        "reversed": true,
        "reversed_by_id": 10,
        "not_settled": false,
        "receipt": null,
        "created_by": "Owner",
        "created_at": "2026-11-14T22:22:57.671980Z"
      },
      {
        "id": 8,
        "kind": "adjustment",
        "what": "Reversal · Adjustment",
        "amount_piastres": -250000,
        "balance_after_piastres": 25694000,
        "happened_on": "2026-11-15",
        "order": null,
        "purchase": null,
        "method": null,
        "payment_kind": null,
        "note": "Counted twice",
        "reversal": true,
        "reverses_id": 7,
        "reversed": false,
        "reversed_by_id": null,
        "not_settled": false,
        "receipt": null,
        "created_by": "Owner",
        "created_at": "2026-11-14T22:22:57.561044Z"
      },
      {
        "id": 5,
        "kind": "purchase",
        "what": "Purchase · Zips",
        "amount_piastres": 300000,
        "balance_after_piastres": 25944000,
        "happened_on": "2026-11-15",
        "order": {
          "id": 2,
          "code": "PO-2611-02"
        },
        "purchase": {
          "id": 2,
          "item": "Zips"
        },
        "method": null,
        "payment_kind": null,
        "note": null,
        "reversal": false,
        "reverses_id": null,
        "reversed": false,
        "reversed_by_id": null,
        "not_settled": false,
        "receipt": null,
        "created_by": "Owner",
        "created_at": "2026-11-14T22:22:57.127753Z"
      },
      {
        "id": 2,
        "kind": "work",
        "what": "Work on PO-2611-01",
        "amount_piastres": 10994000,
        "balance_after_piastres": 25644000,
        "happened_on": "2026-11-15",
        "order": {
          "id": 1,
          "code": "PO-2611-01"
        },
        "purchase": null,
        "method": null,
        "payment_kind": null,
        "note": null,
        "reversal": false,
        "reverses_id": null,
        "reversed": false,
        "reversed_by_id": null,
        "not_settled": false,
        "receipt": null,
        "created_by": "Owner",
        "created_at": "2026-11-14T22:22:55.897176Z"
      },
      {
        "id": 6,
        "kind": "payment",
        "what": "Weekly payment · InstaPay",
        "amount_piastres": -3000000,
        "balance_after_piastres": 14650000,
        "happened_on": "2026-11-14",
        "order": null,
        "purchase": null,
        "method": "instapay",
        "payment_kind": "weekly",
        "note": "Week 46",
        "reversal": false,
        "reverses_id": null,
        "reversed": false,
        "reversed_by_id": null,
        "not_settled": false,
        "receipt": {
          "url": "/api/prod/entries/6/receipt",
          "mime_type": "image/png",
          "size_bytes": 48
        },
        "created_by": "Owner",
        "created_at": "2026-11-14T22:22:57.229985Z"
      },
      {
        "id": 7,
        "kind": "adjustment",
        "what": "Adjustment",
        "amount_piastres": 250000,
        "balance_after_piastres": 17650000,
        "happened_on": "2026-11-13",
        "order": null,
        "purchase": null,
        "method": null,
        "payment_kind": null,
        "note": "Missed invoice",
        "reversal": false,
        "reverses_id": null,
        "reversed": true,
        "reversed_by_id": 8,
        "not_settled": false,
        "receipt": null,
        "created_by": "Owner",
        "created_at": "2026-11-14T22:22:57.455997Z"
      },
      {
        "id": 4,
        "kind": "payment",
        "what": "Deposit · Bank transfer · Heavy fleece, black",
        "amount_piastres": -4000000,
        "balance_after_piastres": 17400000,
        "happened_on": "2026-11-09",
        "order": {
          "id": 2,
          "code": "PO-2611-02"
        },
        "purchase": {
          "id": 1,
          "item": "Heavy fleece, black"
        },
        "method": "bank_transfer",
        "payment_kind": "deposit",
        "note": null,
        "reversal": false,
        "reverses_id": null,
        "reversed": false,
        "reversed_by_id": null,
        "not_settled": false,
        "receipt": null,
        "created_by": "Owner",
        "created_at": "2026-11-14T22:22:57.019078Z"
      },
      {
        "id": 3,
        "kind": "purchase",
        "what": "Purchase · Heavy fleece, black",
        "amount_piastres": 17200000,
        "balance_after_piastres": 21400000,
        "happened_on": "2026-11-09",
        "order": {
          "id": 2,
          "code": "PO-2611-02"
        },
        "purchase": {
          "id": 1,
          "item": "Heavy fleece, black"
        },
        "method": null,
        "payment_kind": null,
        "note": null,
        "reversal": false,
        "reverses_id": null,
        "reversed": false,
        "reversed_by_id": null,
        "not_settled": false,
        "receipt": null,
        "created_by": "Owner",
        "created_at": "2026-11-14T22:22:57.019078Z"
      },
      {
        "id": 1,
        "kind": "opening",
        "what": "Balance brought forward",
        "amount_piastres": 4200000,
        "balance_after_piastres": 4200000,
        "happened_on": "2026-10-06",
        "order": null,
        "purchase": null,
        "method": null,
        "payment_kind": null,
        "note": "From the notebook",
        "reversal": false,
        "reverses_id": null,
        "reversed": false,
        "reversed_by_id": null,
        "not_settled": false,
        "receipt": null,
        "created_by": "Owner",
        "created_at": "2026-11-14T22:22:54.812512Z"
      }
    ]
  }
}
```
Account notes: lines are **newest first**, by date then id; `balance_after_piastres` is what HBA owes after that line. A line for an order not yet settled has `not_settled: true`, `id: null`, `happened_on: null` and comes first; it is worked out on each read and is not a ledger line. A line that was reversed has `reversed: true` and `reversed_by_id` (strike it through); its reversing line has `reversal: true` and `reverses_id`, and its `note` is the reason. A `work` line cannot be reversed (the API says 422), nor can a `purchase` line (void the purchase), nor a reversal. `paid_piastres` is this calendar year's payments (deposits included) that still stand; `paid_year` is that year. `has_opening` says whether a balance brought forward still stands (hide the button when true). `receipt.url` is served only to the owner (an `<img src>` works). A voided purchase has `voided: true`: strike it through. `orders` lists orders the supplier is the factory (`role: "factory"`) or print house (`"print"`) of, open first; `stage` is null unless the order is open.
### `GET /suppliers/{id}` as a viewer (staff and managers get the same)
```json
{
  "supplier": {
    "id": "fac",
    "code": "FAC",
    "name": "Main factory",
    "contact_person": null,
    "phone": null,
    "whatsapp": null,
    "city": "Cairo",
    "notes": null,
    "active": true,
    "sections": [
      {
        "id": 6,
        "name": "Manufacturers"
      }
    ],
    "open_orders": 1,
    "open_purchases": 2,
    "purchases": [
      {
        "id": 3,
        "supplier_id": "fac",
        "item": "Wrong thread",
        "quantity": "12.5",
        "unit": "kg",
        "part": "accessories",
        "order": null,
        "bought_on": "2026-11-15",
        "expected_on": null,
        "received_on": null,
        "note": null,
        "voided": true,
        "voided_at": "2026-11-14T22:22:57.791221Z"
      },
      {
        "id": 2,
        "supplier_id": "fac",
        "item": "Zips",
        "quantity": "1000",
        "unit": "piece",
        "part": "accessories",
        "order": {
          "id": 2,
          "code": "PO-2611-02",
          "style_name": "Oversized hoodie",
          "colour": "Black",
          "status": "open"
        },
        "bought_on": "2026-11-15",
        "expected_on": "2026-11-19",
        "received_on": null,
        "note": null,
        "voided": false,
        "voided_at": null
      },
      {
        "id": 1,
        "supplier_id": "fac",
        "item": "Heavy fleece, black",
        "quantity": "1075",
        "unit": "kg",
        "part": "fabric",
        "order": {
          "id": 2,
          "code": "PO-2611-02",
          "style_name": "Oversized hoodie",
          "colour": "Black",
          "status": "open"
        },
        "bought_on": "2026-11-09",
        "expected_on": "2026-11-12",
        "received_on": null,
        "note": "Pick up from the mill",
        "voided": false,
        "voided_at": null
      }
    ],
    "orders": [
      {
        "id": 2,
        "code": "PO-2611-02",
        "style_name": "Oversized hoodie",
        "colour": "Black",
        "status": "open",
        "role": "factory",
        "stage": {
          "key": "warehouse",
          "label": "Warehouse receipt",
          "position": 9
        }
      },
      {
        "id": 1,
        "code": "PO-2611-01",
        "style_name": "Oversized hoodie",
        "colour": "Black",
        "status": "closed",
        "role": "factory",
        "stage": null
      }
    ]
  }
}
```
### `cost.from_purchases` on `GET /orders/{id}` (owner only; the key is absent for everybody else)
```json
{
  "cost": {
    "from_purchases": {
      "pieces": 972,
      "basis": "cut",
      "parts": [
        {
          "part": "fabric",
          "label": "Fabric",
          "purchases": [
            {
              "id": 1,
              "item": "Heavy fleece, black",
              "supplier": {
                "id": "fac",
                "name": "Main factory"
              },
              "total_piastres": 17200000
            }
          ],
          "total_piastres": 17200000,
          "per_piece_piastres": 17695
        },
        {
          "part": "printing",
          "label": "Printing",
          "purchases": [],
          "total_piastres": 0,
          "per_piece_piastres": null
        },
        {
          "part": "accessories",
          "label": "Accessories",
          "purchases": [
            {
              "id": 2,
              "item": "Zips",
              "supplier": {
                "id": "fac",
                "name": "Main factory"
              },
              "total_piastres": 300000
            }
          ],
          "total_piastres": 300000,
          "per_piece_piastres": 309
        },
        {
          "part": "packaging",
          "label": "Special packaging",
          "purchases": [],
          "total_piastres": 0,
          "per_piece_piastres": null
        }
      ],
      "other": {
        "purchases": [],
        "total_piastres": 0
      }
    },
    "...": "the rest of `cost` is batch 1's, unchanged"
  }
}
```
`pieces` is the pieces cut once cutting is done (`basis: "cut"`), else the pieces planned (`"planned"`). `per_piece_piastres` is the part's live (unvoided) purchases over `pieces`, rounded half up to a whole piastre, or null when there are none. The four `parts` are always present, in this order; `other` collects purchases whose part is `other`. "Use this" is `PATCH /orders/{id}` with `{"actual_<part>_piastres": per_piece_piastres}` (batch 1's edit); `from_purchases` itself never changes the order. The order's part names are `fabric`, `printing`, `accessories` and `packaging` (the `packaging` part is batch 1's "Special packaging").
### The two generated tasks (in `GET /tasks`, for everybody)
```json
[
  {
    "kind": "generated",
    "key": "purchase:1:chase",
    "title": "Chase the Heavy fleece, black delivery",
    "who": "factory",
    "due": "2026-11-12",
    "order": {
      "id": 2,
      "code": "PO-2611-02",
      "style_name": "Oversized hoodie",
      "colour": "Black"
    },
    "stage": null,
    "waiting_on": "Main factory",
    "since": "2026-11-09",
    "open": "purchase:1",
    "supplier": {
      "id": "fac",
      "name": "Main factory"
    },
    "group": "overdue",
    "overdue_days": 3
  },
  {
    "kind": "generated",
    "key": "purchase:2:arrival",
    "title": "Check Zips on arrival",
    "who": "qc",
    "due": "2026-11-19",
    "order": {
      "id": 2,
      "code": "PO-2611-02",
      "style_name": "Oversized hoodie",
      "colour": "Black"
    },
    "stage": null,
    "waiting_on": null,
    "since": "2026-11-15",
    "open": "purchase:2",
    "supplier": {
      "id": "fac",
      "name": "Main factory"
    },
    "group": "week",
    "overdue_days": 0
  }
]
```
Keys are `purchase:{id}:chase` (late: expected before today, not received; `who: "factory"`, `waiting_on` the supplier's name) and `purchase:{id}:arrival` (expected today or later; `who: "qc"`). `open` is `purchase:{id}`; the link is `/production/next/suppliers/{supplier.id}?open=purchase:{id}`. `supplier` is an extra key on these two tasks only. No title carries money. A purchase with no expected date makes no task.
### A cancelled order, after cutting (the factory's page and the order's)

Cancelling an order whose cutting is done (not before) writes one `work` line on the factory's account, in the same transaction, and freezes the payable so far on the order. Built as recommended on 15 November 2026, awaiting the owner's confirmation. For a payable so far of EGP 106,490.00 the owner reads, on `GET /suppliers/{factory}`, a line like this (newest first; there is no `not_settled` line for the order any more, and it counts once in `owed_piastres`):
```json
{
  "id": 14,
  "kind": "work",
  "what": "Work on PO-2611-02",
  "amount_piastres": 10649000,
  "balance_after_piastres": 7649000,
  "happened_on": "2026-11-15",
  "order": { "id": 2, "code": "PO-2611-02" },
  "purchase": null,
  "method": null,
  "payment_kind": null,
  "note": "Cancelled after cutting",
  "reversal": false,
  "reverses_id": null,
  "reversed": false,
  "reversed_by_id": null,
  "not_settled": false,
  "receipt": null
}
```
On `GET /orders/{id}` the `status` is `"cancelled"` and the owner's `settlement` block is the frozen one (`payable_piastres` as it was at the cancel, `settled: true`, `settled_at` set). Anybody else gets the order with no `cost` and no `settlement`, as for every order. At a payable of zero no line is written (the block is still frozen); a negative payable writes a negative line. A cancel before cutting is done writes nothing, and the order has `settlement: null`.

A voided purchase whose deposit the supplier kept (`deposit_returned: false`) keeps its `deposit_piastres`, has `deposit_kept: true`, and its deposit line stays on the account, not reversed.

### Request bodies and what each route answers
#### `POST /api/prod/sections` -> 201
Who and rules: `production.suppliers`. Answers `{sections, section_id}`.
```json
{
  "name": "Manufacturers"
}
```
#### `PATCH /api/prod/sections/{section_id}` -> 200
Who and rules: `production.suppliers`. Answers `{sections}`.
```json
{
  "name": "Fabric"
}
```
#### `DELETE /api/prod/sections/{section_id}` -> 200
Who and rules: `production.suppliers`; refused (422) while a supplier is in it. Answers `{sections, deleted}`.
No body.
#### `POST /api/prod/suppliers` -> 201
Who and rules: `production.suppliers`; `name` required, the rest optional; code `SUP-NNN` is made for it. Answers `{supplier}` (the page).
```json
{
  "name": "Trims supplier",
  "contact_person": "Mona",
  "phone": "0100 000 0000",
  "whatsapp": "0100 000 0000",
  "city": "Cairo",
  "notes": "Pays by InstaPay",
  "section_ids": [
    7
  ]
}
```
#### `PATCH /api/prod/suppliers/{supplier_id}` -> 200
Who and rules: `production.suppliers`; any of these, what is left out stays; `section_ids` replaces the set; `active: false` makes it inactive (a supplier is never deleted). Answers `{supplier}`.
```json
{
  "city": "Giza",
  "active": true,
  "section_ids": [
    7
  ]
}
```
#### `POST /api/prod/suppliers/{supplier_id}/purchases` -> 201
Who and rules: `production.owner`; `quantity` > 0, three decimals at most; `unit` `kg`|`m`|`piece`; `part` as above; `order_id` and `expected_on` optional; `bought_on` not in the future and not more than 366 days back (default today); `expected_on` not before `bought_on`; the same purchase by the same person within 60 seconds answers 409; a deposit is `deposit_piastres` (0 < deposit <= the server's total) with `deposit_method` (`bank_transfer`|`cash`|`instapay`|`wallet`|`cheque`); the total is never sent. Answers `{supplier, purchase_id}`.
```json
{
  "item": "Heavy fleece, black",
  "quantity": 1075,
  "unit": "kg",
  "unit_price_piastres": 16000,
  "part": "fabric",
  "order_id": 2,
  "bought_on": "2026-11-09",
  "expected_on": "2026-11-12",
  "note": "Pick up from the mill",
  "deposit_piastres": 4000000,
  "deposit_method": "bank_transfer"
}
```
#### `PATCH /api/prod/purchases/{purchase_id}` -> 200
Who and rules: `production.edit`; only these three, any other field answers 422; `null` clears; `received_on` not in the future; neither `expected_on` nor `received_on` before the purchase's `bought_on` (422); a voided purchase answers 409. Answers `{supplier}` (no money for a non-owner).
```json
{
  "expected_on": "2026-11-12",
  "received_on": null,
  "note": "Pick up from the mill"
}
```
#### `POST /api/prod/purchases/{purchase_id}/void` -> 200
Who and rules: `production.owner`; `reason` required; `deposit_returned` (boolean) is **required (422) when a deposit stands on the purchase** and ignored otherwise: `true` reverses the purchase and the deposit, `false` reverses the purchase only and leaves the deposit on the account as credit with the supplier. Built as recommended on 15 November 2026, awaiting the owner's confirmation. Answers `{supplier}`; the voided purchase then has `deposit_kept: true` (owner only) when its deposit was kept.
```json
{
  "reason": "Wrong supplier",
  "deposit_returned": true
}
```
#### `POST /api/prod/suppliers/{supplier_id}/payments` -> 201
Who and rules: `production.owner`; `amount_piastres` > 0; `paid_on` not in the future and not more than 366 days back (default today); `method` as above; `kind` `weekly`|`deposit`|`final`; the same payment by the same person within 60 seconds answers 409. Answers `{supplier, entry_id}`.
```json
{
  "amount_piastres": 3000000,
  "paid_on": "2026-11-14",
  "method": "instapay",
  "kind": "weekly",
  "note": "Week 46"
}
```
#### `POST /api/prod/suppliers/{supplier_id}/opening` -> 201
Who and rules: `production.owner`; `amount_piastres` signed and not 0 (positive: HBA owes; negative: overpaid); refused (422) while one still stands; `happened_on` not in the future and not more than 366 days back; an identical one within 60 seconds answers 409. Answers `{supplier, entry_id}`.
```json
{
  "amount_piastres": 4200000,
  "happened_on": "2026-10-06",
  "note": "From the notebook"
}
```
#### `POST /api/prod/suppliers/{supplier_id}/adjustments` -> 201
Who and rules: `production.owner`; signed, not 0; `note` required; `happened_on` not in the future and not more than 366 days back; an identical one within 60 seconds answers 409. Answers `{supplier, entry_id}`.
```json
{
  "amount_piastres": 250000,
  "happened_on": "2026-11-13",
  "note": "Missed invoice"
}
```
#### `POST /api/prod/entries/{entry_id}/reverse` -> 200
Who and rules: `production.owner`; `reason` required; not for `work`, `purchase` lines or a reversal (422); a second reversal is 409. Answers `{supplier, entry_id}` (the reversing line's id).
```json
{
  "reason": "Counted twice"
}
```
#### `POST /api/prod/entries/{entry_id}/receipt` -> 201
Who and rules: `production.owner`; multipart with `file` (JPG/PNG/WebP/GIF or PDF, 20 MB); on a payment only (422 for one that has been reversed); replaces the one there is. Answers `{supplier}`.
Body: multipart: file
#### `GET /api/prod/entries/{entry_id}/receipt` and `DELETE /api/prod/entries/{entry_id}/receipt`
`production.owner` only (403 for everybody else, the viewer, the QC manager and the manager included). `GET` returns the photo or PDF itself (`Content-Disposition: inline`, `nosniff`, no-store); 404 when there is none. `DELETE` has no body and answers `{supplier}`.
#### Route table
| Route | Permission |
|---|---|
| `GET /suppliers`, `GET /suppliers/{id}` | `production.view` (money for the owner only) |
| `POST /suppliers`, `PATCH /suppliers/{id}`, `POST /sections`, `PATCH /sections/{id}`, `DELETE /sections/{id}` | `production.suppliers` |
| `PATCH /purchases/{id}` | `production.edit` |
| `POST /suppliers/{id}/purchases`, `POST /purchases/{id}/void`, `POST /suppliers/{id}/payments`, `POST /suppliers/{id}/opening`, `POST /suppliers/{id}/adjustments`, `POST /entries/{id}/reverse`, `POST|GET|DELETE /entries/{id}/receipt` | `production.owner` |
