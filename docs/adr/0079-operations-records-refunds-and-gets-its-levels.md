# 0079. Operations records refunds owed; it never pays. Operations gets viewer and staff levels

**Status:** Accepted
**Date:** 2026-11-10

## Context

Refunds to customers were tracked in a Google Sheet. One row per customer owed
money: the courier's order number, Return or Exchange, the customer's name and
phone, the amount, the refund method (InstaPay, Vodafone Cash) and the refund
ID. A Google Apps Script read Bosta's public tracking for each row and ticked
*received* once the parcel was back. A person then sent the money elsewhere and
ticked *paid*.

HBA has moved from Bosta to Khazenly, a fulfilment centre. On 10 November 2026,
11 real Khazenly orders were tested against `track.khazenly.com`. The page reads
a public JSON endpoint that needs no login,
`https://tracking-api.khazenly.com/api/v1/tracking/?referenceNumber=KH-…`,
which answers with the order's Shopify number and suffix (`PO_Number__c`, such
as `#31876-RE`) and its timeline: each step's name, time and an optional courier
note. It carries no customer details. An unknown number comes back as HTTP 500
with the body `"Request failed with status code 404"`. A return ends in
*Return Completed*. Khazenly's own page shows the step *Contact Success
Manager* as "Order In Progress".

Operations had a single level, its manager. The owner wants viewers who see
every Operations tab and change nothing, and staff and managers who see and
change everything there.

## Decision

1. **Operations → Returns records refunds owed. It never pays.** No money
   moves, nothing is written to Shopify or Khazenly, and nothing here changes
   model pay (pay stays Shopify's answer, ADR 0023). Each row is one customer
   owed a refund, for a **Return** or an **Exchange** (a cheaper item than the
   one sent back). The amount is whatever the person will send, greater than
   zero. Fees and deductions are out of scope.
2. **Added by Khazenly number.** The platform reads Khazenly at once, refuses a
   number Khazenly does not know or one already listed, and keeps the Shopify
   number and the timeline. The customer's name and phone are read from that
   Shopify order and can be corrected; when Shopify gives none, a person types
   them.
3. **Received means *Return Completed*.** Only then can a row be marked paid.
   Earlier steps show, but do not unlock payment.
4. **Read every 30 minutes** while not received, and once when added. A
   received or paid row is not read again. Each row says when it was last
   read, and a failed read says so rather than showing an old step as current.
   The endpoint is unofficial: if Khazenly changes it, the tab shows the
   failure and the rows stay as they were.
5. **Paid** records the date (never in the future), who recorded it, and the
   amount, method and refund ID as sent. A paid row is locked. Undoing *paid*
   needs a reason, kept in the activity log. Only an unpaid row can be
   deleted.
6. **Needs attention**: no new Khazenly step for 3 days or more, a *Contact
   Success Manager* step, or received and unpaid for more than 2 days.
7. **Operations gets two levels**, as Production has (ADR 0076):
   `operations_viewer` (`order_ops.view`) sees every Operations tab, including
   Khazenly's run history, and changes nothing. `operations_staff` and
   `operations_manager` see every tab and change what Operations can change:
   they hold `order_ops.view`, `khazenly.use` and the new `returns.edit`. The
   single-holder rule on the manager stays. Customer service keeps the
   Khazenly section alone, and does not see Returns. The keys stay the
   admin's (`settings.manage`).
8. **Personal data**: `ops_refund` is the first Operations table that keeps a
   customer's name, phone and refund handle, because recording a refund needs
   them. Only Operations roles and the admin read them. The activity log names
   a refund by its Khazenly number and amount, never the customer. This
   narrows ADR 0059, point 9 ("Operations holds no phone or name") by one
   named table; `tests/test_inbox_models.py` still fails for any other.
9. **Find and sort** (the owner, 10 November 2026): one search, under *Add a
   refund* and above the four groups, finds a refund by the customer's name
   or phone (however the phone is written), the Shopify order or the
   Khazenly number. Every column sorts, both ways; a phone sorts from a menu,
   since its rows stack. Search covers every unpaid refund and the latest
   100 paid, as the tab holds them.

## Consequences

- The tab depends on an endpoint Khazenly never promised. It can break without
  notice. The failure is visible, and a person can still record payments.
- A customer's details now live in Operations. They are read only by people
  who already see Operations, and are not copied anywhere else.
- `khazenly_router`'s reads now accept `order_ops.view` as well as
  `khazenly.use`, so a viewer sees Khazenly's history but cannot build a file.

## Alternatives considered

- **Khazenly's merchant portal** (`experience.khazenly.com`) needs a login;
  storing a password to scrape it was rejected.
- **Importing the old sheet**: the owner chose to start fresh.
- **Writing the refund to Shopify**: out of scope; the money is sent outside
  Shopify and pay must not move with it.
