# 0089. Billing lists every purchase, and fabric is kept in storage by the kilo

**Status:** Accepted
**Date:** 2026-11-22

## Context

On 21 November 2026 the owner asked for two more Production sections:

- **Billing:** "all the billings and receipts that HBA bought, fabric,
  accessories, etc."
- **Fabric storage:** "all the fabric I own or bought as in my storage. When I
  make a production order, it tells me to select the fabric from the storage
  and how many kgs am I using and minus it automatically."

He accepted the recommendations put to him the same day: Billing shows the
purchases already recorded on each supplier's account rather than keeping a
second record of money; every bill has a supplier; buying fabric by the kilo
fills storage; one order may use more than one fabric; an order may not take
more fabric than storage holds; and the order's fabric cost is filled from
what it took, for him to keep.

What existed: a purchase (`prod_purchase`) is recorded against a supplier and
writes its line on that supplier's account (ADR 0084); the account is what
"what you owe" is read from. Payment receipts are photos on a payment line
(`prod_supplier_receipt`). An order's actual cost is typed per piece, part by
part, by `production.owner`.

## Decision

**Billing.**

- `/production/billing`, for `production.owner` only (it is money, like
  Payments, ADR 0086): every purchase from every supplier, voided ones shown
  struck through, newest first, filtered by date range, supplier and cost part,
  with the total of those not voided, and per part.
- A bill **is** a purchase. Adding one records a purchase on its supplier's
  account exactly as the supplier page does; nothing is counted twice.
- A bill carries **photos or PDFs of its receipt** in a table of its own
  (`prod_purchase_photo`). A payment's receipts stay where they are.

**Fabric storage.**

- `/production/fabric`, for everybody who reads Production; the price per kg
  is `production.owner`'s only.
- A **fabric** (`prod_fabric`) is a named roll type: name, fabric type,
  colour, colour code, usual supplier. Its stock is never stored as a number;
  it is the **sum of its movements** (`prod_fabric_move`, kilos to three
  decimals, signed): `purchase` (in), `use` by an order (out), `return` to
  storage (in, undoing a use), `count` (a correction, either way, with a
  reason), `void` (out, undoing a purchase).
- A purchase **in kg of the fabric part** may put its kilos into a fabric,
  existing or new, as it is recorded. Voiding it takes them out again, and is
  refused while that would leave the fabric below zero.
- An order whose fabric HBA buys may **take fabric from storage**: one or more
  fabrics, each with its kilos, on the New order form or later on the order
  while it is open. Taking more than the fabric holds is refused. Taking one
  off returns its kilos. **Cancelling an order returns everything it took.**
  An order whose fabric the factory buys takes nothing.
- The **price per kg** of a fabric is the average of its live purchases
  (their totals over their kilos). The order shows the owner what its fabric
  from storage cost (kilos × that price, for the order and per piece over the
  pieces planned, or cut once cutting is done) and offers it as the actual
  fabric cost. **It is written only when the owner presses it**; the actual
  cost stays a figure he sets.

## Consequences

- Storage is right only as far as what is recorded is complete: fabric used
  outside an order, waste and leftovers need a `count` to put storage right.
- The average price moves as new fabric is bought; an order's fabric cost is
  worked out when it is read, not frozen, until the owner presses it into the
  actual cost.
- The QC manager sees kilos, never a price.
- A purchase not in kg (metres, pieces) never fills storage.

## Alternatives considered

- **A separate Billing ledger.** Rejected: two records of the same money
  disagree, and "what you owe" would have to choose one.
- **Receipts on the purchase's account line** (the payment receipts' table).
  Rejected: it would change what a payment receipt is and every rule written
  around it.
- **Writing the fabric cost into the order automatically.** Rejected: an
  order's cost is the owner's figure (ADR 0084); it is offered, not written.
- **First-in-first-out pricing per roll.** Rejected for now: HBA does not
  track rolls separately; the average is honest about that.
