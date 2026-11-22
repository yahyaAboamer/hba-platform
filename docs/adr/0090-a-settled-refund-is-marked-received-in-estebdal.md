# 0090. A settled refund is marked received in E-stebdal

**Status:** Accepted
**Date:** 2026-11-22

## Context

E-stebdal holds every return and exchange request. A request's sale is not
deducted from E-stebdal's or Shopify's reports until the request is closed,
and E-stebdal only lets a request be closed once it has been marked
*received*. Until now nobody marked them, so the reports kept counting sales
that had been refunded. The owner (22 November 2026) wants Operations →
Returns to mark the request received on its own, so his team only has to
filter E-stebdal by *Processing* and close those requests, one by one or in
bulk.

ADR 0079 said the Returns tab writes nothing outside the platform. This
changes that rule for this one write.

E-stebdal's public API (read 22 November 2026, `openapi-public.json`):
`POST /api/v1/public/returns/{id}/received`, with an *all-access* key. The
request must currently be **Approved**. The request moves to **Processing**
and `receivedAt` is set. The body's one option is `notifyCustomer`, true when
it is left out, which emails the customer. The call does not restock. For a
Cash request still owed money, E-stebdal also records the cash refund as
settled. Nothing can undo the call. A request is found with the list's
filter: its number is the order number followed by `-R1`, `-R2` and so on.

## Decision

1. **When.** A refund row is sent once it is both **paid** and **received**
   (Khazenly says *Return Completed*). A row paid before the parcel is back
   waits for Khazenly. Both kinds are sent: returns and exchanges.
2. **Which request.** The request is found from the row's Shopify order
   number, and only the requests whose order number matches exactly are
   used.
   - When exactly one is *Approved*, it is marked received.
   - When more than one is *Approved*, nothing is guessed: the row asks a
     person to choose one.
   - When none is *Approved*: if one is still waiting (*Needs Review* or
     *Pending Payment*), the row says so and is tried again later. If one is
     already *Processing* or *Closed*, the row counts as done. If all are
     *Rejected* or *Cancelled*, or there is no request at all, the row says
     so.
3. **Paid never waits for E-stebdal.** *Mark paid* is saved the same way
   whether or not E-stebdal answers. Sending happens afterwards. A failure
   is kept on the row with a plain note, the row is tried again on the next
   run, and *Try again* sends it at once. The exception is an outright
   refusal of an *Approved* request: it is marked *refused* and waits for a
   person's *Try again*, so it is never sent every 15 minutes.
   **Each row of the background run is its own transaction**, locked, sent
   and committed alone. A send can email a customer and cannot be taken
   back, so its record must not roll back with a later row's failure. This
   is the one job that commits outside the session the worker gives it, and
   the reason is this one.
4. **The customer email stays on** for refunds paid after this goes live.
   Rows already paid when it went live (the sweep of old rows the owner
   asked for) are sent without the email, so nobody gets a "we received
   your return" weeks late.
5. **Undoing *paid* does not touch E-stebdal**, because E-stebdal cannot
   take *received* back. The undo box says so.
6. **One key** reads and writes: an all-access key saved in Settings →
   Integrations. After the first real send works, the old key is revoked
   in E-stebdal and taken out of Railway's `ESTEBDAL_API_KEY`.
7. **Only the production service writes.** The switch is
   `ESTEBDAL_MARK_RECEIVED`: `off` (the default; nothing is sent), `manual`
   (only a person's *Mark received in E-stebdal* or *Try again* sends), or
   `auto` (the background run also sends every row that is due). Staging
   keeps `off`: there is only one real E-stebdal, and a staging test would
   change real customers' requests and email them. It goes live as
   `manual`, one real request is sent by hand and checked in E-stebdal,
   and then it becomes `auto`.
8. **Who.** Anyone who can mark a refund paid (`returns.edit`) can send or
   choose by hand. Each send is in the activity log with the refund's
   Khazenly number and the E-stebdal request number, never the customer.

## Consequences

- The tab now changes something outside the platform that cannot be undone.
  Exactly one call per request, only for paid and received rows, and only
  where the switch allows it.
- E-stebdal emails the customer for new refunds.
- A wrong order number on a row would mark the wrong request. The exact
  order-number match and the refusal to guess between two *Approved*
  requests are the guards. A refund row is linked to an order, not to a
  request, so the guard cannot tell requests apart in two cases:
  - an order with a refunded R2 and a still-*Approved* R1 marks R1;
  - an old *Closed* R1 next to a *Rejected* R2 reads as already received.
  Both need two requests on one order, which the owner sees rarely, and the
  row names the request it used.
- E-stebdal's own words (a refusal, a warning) are shown on the row, as it
  gave them, up to 200 characters. They never go into the activity log or
  the server log.
- E-stebdal documents no answer for "not Approved" other than `400`, and no
  way to test a key's write access without writing. A refused key first
  shows on a real send, as a note on the row.

## Alternatives considered

- **Sending inside *Mark paid*.** It would make paying wait on E-stebdal and
  fail when it is down. Rows paid early would still need a later send.
- **Marking received as soon as Khazenly says *Return Completed*, paid or
  not.** The owner chose to wait for both.
- **Letting staging write.** Rejected: it would change real requests.
