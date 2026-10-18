# 0063. An answer tagged in Shopify counts, and the cards count open orders

**Status:** Accepted
**Date:** 2026-10-18

## Context

Inbox → Confirmations showed 67 orders on its five action cards on 18
October 2026. A read-only check of production that day found only 7 that
still needed anybody. The other 60 were already shipped (35) or cancelled
(25) in Shopify. The cards counted only what the customer did in WhatsApp,
over every order from the last 7 days. Nothing that happened in Shopify
afterwards took an order off a card. *Asked to cancel* said "still open in
Shopify" without ever checking: 14 of its 15 orders were already cancelled.

The owner then found order #31441 marked *Waiting for an answer*, with
*WA Sent 📤* under "Tags in Shopify", while Shopify itself carried
*Confirmed ✅*. The platform had written *WA Sent* and never anything
else. The customer never tapped. Somebody changed the tag in Shopify, which
does not record who changes a tag. The platform never reads tags back, so
the panel was showing the tag it last wrote, not the order's tag.

Across all 238 orders of that week, 37 carried a different confirmation tag
in Shopify from the one the platform believed: 23 *WA Sent* and 9 *Edit*
that Shopify called *Confirmed*, 2 untagged ones also *Confirmed*, 2
*Cancelled*, and one carrying two tags. This is how the team worked under
n8n, and still does: they call the customer or make the change, then set
the tag in Shopify.

## Decision

1. **An answer tagged in Shopify is the order's answer.** When an order's
   confirmation tags change in Shopify, the platform reads them. If
   exactly one of *Confirmed ✅*, *Edit ✏️* or *Cancelled ❌* is on the
   order and it differs from the answer on record, it becomes the answer,
   recorded as given in Shopify (`answered_in = 'shopify'`). A tap in
   WhatsApp is recorded as `whatsapp` and a mark in the Inbox as `inbox`.
   A later answer, from any of the three, replaces an earlier one.
2. **Nothing is guessed, and nothing newer is undone.** Two answer tags at
   once are left as they are; the platform cannot tell which is meant. A
   tag that was removed takes no answer away: what the customer said
   remains what she said. A tag is taken only when the order's answer tags
   **changed since the platform last read them**: an unchanged tag is one
   it already knows, and taking it again would undo a newer tap or mark.
   A tap or mark made while Shopify was being asked wins over what that
   read returns. An answer taken from a tag is dated by the order's last
   change in Shopify, not by when the platform read it.
3. **Reading a tag writes nothing.** The platform does not answer a tag it
   read by writing tags back. It still writes only as ADR 0059 and 0062
   say: after it sends, after a tap, after a mark in the Inbox, after
   payment.
4. **The panel shows the tags Shopify really has**, as of the last read,
   and only the platform's own seven tags. Before the first read it shows
   the tag the platform wrote, labelled as such.
5. **How tags are read.** In its own job, through the connection that reads
   money, which stays read-only (ADR 0015). It runs when Shopify reports
   that an order changed, for orders with a confirmation decided in the
   last 14 days. A failed read never stops an order being indexed.
   Orders from the last 7 days are each read once after this ships, so the
   cards are right from the start.
6. **The action cards count orders still open in Shopify.** *Waiting for
   an answer*, *Wants a change*, *Asked to cancel*, *Not sent*,
   *No WhatsApp* and *Waiting for payment* leave out any order that has been
   cancelled or shipped in Shopify. Shipped means Shopify holds a
   fulfilment that counts (ADR 0051), for any part of the order: the same
   test that sets an order's delivery state. *Waiting for payment* is the
   exception and leaves out only cancelled orders. An international order
   shipped while it still owes money is one somebody must see (ADR 0062).
7. **What left a card is still shown**, as one line under it: how many of
   its orders were already shipped or cancelled. *Confirmed* and *Paid by
   link* are outcomes, not work, and keep counting every order.

## Consequences

- The numbers on the action cards drop as the team works. Each one is now
  an order somebody can still act on.
- A customer who asked for a change and was shipped without it is no
  longer on *Wants a change*. The platform cannot tell a change that was
  made from one that was missed; shipping is taken as handled.
- The platform now reads Shopify once more for each change to a recent
  order. The read is small, and is limited to orders with a confirmation
  decided in the last 14 days.
- A tag set in Shopify by mistake becomes the answer. It is put right
  where it was made, in Shopify or in the Inbox.
- *Tapped Confirm* is no longer true of every confirmed order, so the
  cards and the panel say where an answer came from.

## Alternatives considered

- **Count only orders less than a day old.** That hides old orders that
  really are stuck, and still counts the ones already shipped.
- **A "Done" button on every order.** It adds work for the team, who
  already record the outcome in Shopify.
- **Write the platform's tag over whatever Shopify has.** That would undo
  the team's own work. They set those tags on purpose.
- **Read tags on the order sync's shared query.** That query feeds
  commission. As with the confirmation's own read (ADR 0059), a refused
  field there must never be able to stop orders indexing, so the inbox
  reads tags in a query of its own.
