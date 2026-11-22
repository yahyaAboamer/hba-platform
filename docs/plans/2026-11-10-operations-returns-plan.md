# Operations → Returns: the refund monitor — plan, 10 November 2026

**Status: started 10 November 2026 on the owner's word.** The decisions below were approved
by the owner on 10 November 2026, with his corrections folded in. Nothing is
built yet. Branch `claude/returns-tracking-dashboard-cdd817`.

## What it is

A new section of Operations, **Returns**, that replaces the Google Sheet the
owner used with Bosta. Each row is **one customer who is owed a refund**:
either a return or an exchange for a cheaper item. The platform watches each
row's Khazenly order and marks it received by itself. A person pays the
customer outside the platform and records it here as paid.

**It records; it never pays.** No money moves, nothing is written to
Shopify or Khazenly, and a refund here never changes model pay (pay stays
Shopify's answer, ADR 0023). The amount is whatever the person will send:
fees and deductions are out of scope.

The old sheet is not imported. The tab starts empty.

## What we learned about Khazenly (tested 10 November with 11 real orders)

- `track.khazenly.com` reads a public JSON endpoint with no login:
  `GET https://tracking-api.khazenly.com/api/v1/tracking/?referenceNumber=KH-HBA-…`
  → `data.order` (`Name` = the KH number, `PO_Number__c` = the Shopify
  number with a suffix, for example `#31876-RE`) and `data.timeline`: each
  step's `Order_Status__c`, `Order_Status_Date__c` (UTC) and an optional
  courier `Note__c`, newest first.
- **No customer details** are in the answer: no name, phone or amount.
- It only finds KH numbers. A Shopify number or an unknown KH number comes
  back as HTTP **500** with the body `"Request failed with status code 404"`.
- Return steps seen: New Return → Ready for Pickup → Return Picked Up →
  In-transit to Fulfilment Center → Return Reached Fulfilment Center →
  Return Receiving In Progress → **Return Completed**.
- Khazenly's own page shows **"Contact Success Manager"** as "Order In
  Progress". The JSON gives the real name, so we can flag it.
- Delivery orders (not returns) end in "Order Delivered".
- **It is unofficial** (it is the endpoint behind their public page, with no
  promise behind it). The tab must say plainly when it stops answering,
  rather than show old statuses as current.

## Decisions (approved)

1. **One row = one refund owed.** Type is **Return** or **Exchange**. Both
   carry an amount, which is required and greater than zero. An exchange
   with nothing to refund is simply not added.
2. **Added by KH number.** The platform reads Khazenly immediately, fills
   the Shopify order number and the tracking link, and refuses a KH number
   Khazenly does not know or one already in the tab. The person enters
   type, amount, refund method and refund ID.
3. **Customer name and phone come from Shopify**, using the Shopify number
   Khazenly returns, read with the platform's own app credentials. They can
   be edited. If Shopify will not give them (customer-data access), the
   fields are typed by hand. *Checked read-only before building, see task 1.*
4. **Received = "Return Completed"** on Khazenly. "Reached the warehouse"
   and "Being counted" show as earlier steps but do not unlock *Mark as
   paid*.
5. **Checked every 30 minutes** while a row is not yet received, and once
   on adding it. A completed or paid row is not read again. Each row shows
   when it was last checked. If Khazenly fails for every row, the tab shows
   one plain banner.
6. **Mark as paid** records the paid date (today by default, never in the
   future), who recorded it, and confirms the amount, method and refund ID.
   A paid row is locked. **Undo paid** asks for a reason and writes it to
   the activity log.
7. **Organised by the next act**: *Ready to refund* (received, not paid)
   first, then *On the way back*, *Needs attention*, then *Paid*.
8. **Needs attention**: no new Khazenly step for 3 or more days, a "Contact
   Success Manager" step, or received but unpaid for more than 2 days.
9. **Totals**: owed now (received and unpaid), and refunded this month.
10. **Guards**: no KH number twice; the refund ID must fit its method (an
    Egyptian mobile number, an `…@instapay` handle, or an InstaPay `ipn.eg`
    link, reusing the Payments handling from PR #154).
11. **Paste several KH numbers at once** to add many rows, each then
    completed with its amount and details.
12. **Who** (the owner, 10 November: viewers see every Operations tab and
    change nothing; staff and managers see everything and change
    everything):

    | Role | Sees | Changes |
    |---|---|---|
    | `operations_viewer` (new) | every Operations tab, Khazenly's history included | nothing |
    | `operations_staff` (new) | every Operations tab | Returns, and builds the Khazenly file |
    | `operations_manager` (exists) | every Operations tab | Returns, and builds the Khazenly file |
    | `admin` | everything | everything |
    | `customer_service` | the Khazenly section alone, as today | the Khazenly file |

    The two new roles copy Production's levels (ADR 0076/0077). The
    single-holder rule on the operations manager is unchanged; the
    Bosta and E-stebdal keys stay the admin's.

**Refund methods** offered: InstaPay, Vodafone Cash, Bank transfer, Other.

**Personal data**: this is the first Operations table that keeps a
customer's name, phone and refund handle. It is kept because recording a
refund needs it. Only Operations roles and the admin see it, and none of it
goes into the activity log text or the server logs.

## The work, in order

One batch, one pull request. Merge and deploy only on the owner's word.

1. **Check Shopify first (read-only).** With the platform's own app
   credentials, read one real order by number and confirm the customer's
   name and phone come back. This decides decision 3's automatic part.
   *Exchange check:* if the owner gives one exchange KH number, read it the
   same way to confirm exchanges end in "Return Completed" too.
2. **ADR 0079** (*Operations records refunds; it never pays*) with the
   decisions above, then a short `docs/RULES.md` entry: refunds are
   recorded only and do not touch pay.
3. **Roles and permission.** New `returns.edit` permission;
   `operations_viewer` = `order_ops.view`; `operations_staff` =
   `order_ops.view` + `returns.edit`; `operations_manager` gains
   `returns.edit`. Settings → Team can grant them (`teamAccess.ts`).
   Migration extends the role check constraints, as Production's did.
4. **Table `ops_refund`** (migration): KH number (unique), type, Shopify
   number, customer name and phone, amount (`Numeric(12,2)`), method,
   refund ID, the last Khazenly timeline (JSON) with the current step and
   its time, received at, checked at, last check error, paid on, paid by,
   created/updated by and at. Check constraints: amount > 0, paid fields
   all set or all empty.
5. **Khazenly tracking client** (`services/khazenly_tracking.py`): one GET
   with a 10-second timeout, an identifying user agent with no personal
   data, the 500/404 body read as "unknown number", only the fields above
   kept. Tests against recorded answers (from the 11 orders, with nothing
   personal in them).
6. **The 30-minute read** in the worker's operations lane, for rows not yet
   received, one request at a time. Freshness is recorded like the other
   sources, so the tab and the frame can say how old it is.
7. **API** under `/api/operations/returns`: list with the four groups and
   totals; add (one or a pasted list); edit; mark paid; undo paid with a
   reason; delete a row that is not paid. Every write is audited, with
   plain wording in `audit_words.py`.
8. **The tab** (`OperationsReturns.tsx`), in Operations' existing look
   (there is no approved export for it). A mockup is shown to the owner
   first. Then it goes through the screen-refinement method: phone width,
   wording, empty, loading and error states, keyboard access.
9. **Tests**: backend (permissions for every role, guards, status mapping,
   attention rules, paid lock and undo, unknown KH number, Khazenly down)
   through `docs/repair/batch-1/run-suite.sh`; frontend `npm test` and
   `npm run build`.
10. **Review** (code, security and database review), fix, then check on
    staging after the owner allows the deploy, with the owner signing in.

## As built (10 November 2026)

- **ADR 0079**, and a `docs/RULES.md` entry: refunds are a record, never a payment.
- **Roles**: `operations_viewer`, `operations_staff`; `returns.edit`; the
  manager gains it. Settings → Team offers all three Operations levels.
  Khazenly's reads take `order_ops.view` or `khazenly.use`
  (`require_any_permission`); building the file stays `khazenly.use`, and
  the tab hides its upload from viewers.
- **Migration `a1c7e3f50028`** (after `f8d4b1c30027`): `ops_refund` and the
  widened role checks. Rehearsed up → down → up on the disposable database.
  Its downgrade refuses while anybody holds or is invited to a new level.
  **Joins the release gate's migration/rollback rehearsal list.**
- **Khazenly reader** `services/khazenly_tracking.py`; **service**
  `services/returns.py`; **job** `order_ops_track_returns`, every 30
  minutes in the operations lane, stopping after 3 minutes or 5 failures in
  a row so it never holds Shopify, Bosta and E-stebdal back.
- **Routes** under `/api/order-ops/returns`: list, add, edit, paid, unpaid,
  check, delete.
- **Screen** `OperationsReturns.tsx`, the sixth Operations tab.
- **Review** (code reviewer): no critical findings; one high (the read's
  time budget) and two medium (a check could un-receive a row; the pay form
  could send details older than the ones just saved) fixed, with tests.
- **Seen working** on a local copy with a throwaway database, at 390 and
  1440: add (against the real Khazenly, 10 November), mark paid, undo with
  a reason, the activity log's words. Phone fixes made from it: the sums
  take a row each; a long refund ID no longer squeezes the Khazenly number.

**Open:**
- **Shopify customer read** not yet confirmed on staging: Railway's SSH
  answered "temporarily unavailable" three times on 10 November. The inbox
  already reads first name and phone in production; whether *last* name is
  granted is unchecked. If not, the shorter query is used and the name is
  the first name only, or typed.
- **Exchanges**: none was seen on Khazenly. Received is *Return Completed*
  for both; confirm with one real exchange number.

## Added 11 November 2026 (ADR 0082, the owner)

- **Paid before it is back.** Any refund not yet received can be recorded
  as paid after ticking "I paid it before Khazenly said the return was
  back" (*Paid it already? Record it* on the row). It moves to *Paid*,
  tagged "Paid before it was back" with its Khazenly step, and is still read
  every 30 minutes (and by *Check Khazenly now*) until *Return Completed*,
  for up to 60 days after the day paid. Migration `b2d8f4a60029`.
- **Payment photo, optional.** Chosen in the pay form, or added, replaced or
  removed later on a paid row. JPG, PNG or WebP up to 10 MB, in the file
  bucket under `operations/refunds/`, served only to Operations; undoing
  paid removes it.
- **The four groups fold.** *Ready to refund* and *Needs attention* start
  open, *On the way back* and *Paid* folded; each person's choice is kept
  in their browser. A search opens every group it found something in.

## Added 22 November 2026 (ADR 0090, the owner)

- **Marked received in E-stebdal.** A refund that is paid **and** back
  (*Return Completed*) has its E-stebdal request marked received, so it
  moves to *Processing* and the team can close it there, which is what
  takes the sale out of E-stebdal's and Shopify's reports. The one
  *Approved* request on that Shopify order is used. Two approved requests
  wait for a person to choose, and nothing is guessed. A request still in
  review is tried again. One already *Processing* or *Closed* counts as
  done. *Paid* never waits for E-stebdal.
- **Switch** `ESTEBDAL_MARK_RECEIVED`:
  - `off`: the default, and staging stays on it.
  - `manual`: only a person's *Mark received in E-stebdal* sends.
  - `auto`: also the 15-minute job `order_ops_estebdal_received`, which
    also sweeps the older paid rows.
- **Email:** customers are emailed for refunds paid after migration
  `d5f7b9c20043`. Rows already paid then are sent without the email.
- **Undo paid** leaves E-stebdal received, because it can't be taken back.
- **Going live** (each step on the owner's word):
  1. deploy;
  2. set production to `manual`;
  3. mark #32546-R1 (Khazenly 09254008) by hand and check it in E-stebdal;
  4. set `auto`;
  5. revoke the old key in E-stebdal and remove it from Railway's
     `ESTEBDAL_API_KEY`.
- **Release gate:** migration `d5f7b9c20043` joins the rollback-rehearsal list.
  It was rehearsed up → down → up on the disposable database on 22 November.

## Not in scope

Paying anyone; writing to Shopify or Khazenly (E-stebdal's *received* is the one write, ADR 0090); fees or deductions; changing
model pay; importing the old Google Sheet; Bosta returns.
