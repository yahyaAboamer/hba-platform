# 0080. A refund can be paid before the return is back, and can carry a photo

**Status:** Accepted
**Date:** 2026-11-11

## Context

ADR 0079 let a refund be marked paid only once Khazenly said *Return
Completed*. The owner (11 November 2026): some customers are refunded early,
as special cases, among them refunds still shown as *Needs attention*. Those
payments must be recordable, and the row must keep its Khazenly status after
it moves to *Paid*. The owner also asked for an optional photo as proof of
the payment.

## Decision

1. **Paid before the return is back.** A refund not yet received can be
   marked paid. The person confirms it is early (the request says so); the
   activity log records it as early. Everything else in 0079 decision 5
   stands: the date is never in the future, the amount, method and refund ID
   are required, a paid row is locked and undoing *paid* needs a reason.
   When the return is already received, the date still cannot be before it.
2. **It keeps its status.** A row paid early stays in *Paid* and is still
   read from Khazenly every 30 minutes until *Return Completed*, for up to
   60 days after the day it was paid; *Check Khazenly now* still works on
   it. The row shows its latest Khazenly step and "Paid before it was back".
   It never returns to *Needs attention*: it is paid.
3. **A photo of the payment, optional.** One photo per paid refund (JPG, PNG
   or WebP, up to 10 MB), checked by its first bytes, kept in the platform's
   file bucket under `operations/refunds/`. It can be added when marking
   paid, or added, replaced or removed afterwards: the only change a paid
   row accepts. It is served only to people who see Operations, and adding
   or removing it goes in the activity log. Undoing *paid* removes it.

This amends ADR 0079, decisions 3, 4 and 5.

## Consequences

- *Owed now* still counts only received, unpaid refunds; an early payment is
  counted in *Refunded this month* on its day.
- A photo can show a customer's account details; it is read only by people
  who already see the refund itself.
- The database no longer requires a paid row to have been received.
