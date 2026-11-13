# 0083. A delivered order is asked how it went, on WhatsApp

**Status:** Accepted, being built
**Date:** 2026-11-12

## Context

The owner (12 November 2026) wants every customer asked, after delivery, how
the order went: happy customers thanked and rewarded, unhappy ones handed to
customer service, and every answer kept in one sheet. He first proposed Google
Forms; he approved doing it inside WhatsApp and the Inbox instead, because a
tap in the chat is answered far more often than a form, and because an answer
given in the chat is already tied to its order.

Facts this is built on, checked on the day:

- Shopify's delivered date and return state are already on `order_index`
  (ADR 0023, 0051). Customer phone, name and products are not (ADR 0059).
- Meta bills each delivered template. Since 1 October 2026 it also bills
  free-form messages after 1,000 a month per number. A feedback question
  counts as *utility* only when it names the order and carries no offer; with
  an offer it is *marketing*, about fifteen times the price.
- One Shopify discount can hold many codes, and its usage limit counts per
  code. Creating codes needs `write_discounts`.

## Decision

1. **Who is asked, and when.** An order is asked once, two days after
   Shopify's delivered date. It is not asked when:
   - it has no delivered date, is cancelled, refunded or voided, or shows any
     return in Shopify, in the returns awaiting review, or in refunds owed;
   - it was delivered before the feature was switched on, or more than seven
     days ago;
   - its phone is not an Egyptian mobile;
   - the same phone was asked in the last 60 days.
   An order not asked for one of these reasons is recorded with the reason
   and never looked at again.

   An order **waits**, instead of being dropped, when the customer has
   written something in the last three days that nobody on the team has
   answered, or when she has an unhappy answer not yet resolved: both clear
   on their own. A tap on a button does not count as writing, and a message
   older than three days no longer blocks. A waiting order is looked at again
   every six hours and is asked as soon as it is clear. If seven days pass
   after delivery and it is still waiting, it is dropped.
2. **The first question** is an approved template naming the order, with
   three buttons: *Loved it*, *It was okay*, *Not happy*. It never mentions a
   reward.
3. **What follows a tap**, sent as ordinary chat messages while her 24 hours
   are open:
   - *Loved it*: one question, what she liked most. Then her code, the review
     link, and an invitation to write anything we could do better.
   - *It was okay*: one question, what would have made it better. Then her
     code and the same invitation.
   - *Not happy*: one question, what went wrong. Then a promise that a person
     will write to her within the promised time (24 hours). No code yet.
   The first thing she writes after that, within 24 hours, is kept as her
   comment. Nobody is asked more than three questions.
4. **Unhappy chats are followed up by a person.** The chat is listed under
   *Needs follow-up* with the reason and the order until someone presses
   *Resolved*. A day later she is asked *Was your issue solved?*:
   - *Yes*: she is asked how likely she is to order again, then sent her code.
   - *No*: the chat returns to *Needs follow-up*, marked as reopened, and is
     raised to the manager on Today. It is asked only once more after the
     second *Resolved*.
   This question goes as a chat message if her 24 hours are open and as a
   second approved template if not.
5. **The reward is one code each, in one Shopify discount.** The platform
   keeps a single discount, *Feedback 20%*: 20% off, one use per code, once
   per customer. Each customer who finishes gets her own code inside it.
   A code unused after 30 days is deleted from Shopify. A code is recorded as
   used when an order carrying it is indexed. Codes are written through the
   second Shopify app, which must now also be allowed to manage discounts.
6. **Every answer is a row.** Inbox gains a *Feedback* section: one row per
   asked order with the date, customer, order, products, courier, each
   answer, who resolved it, and the code and whether it was used. It filters
   by date, answer, reason, product and courier, and downloads as a
   spreadsheet. Everyone who holds the Inbox sees it.
7. **Nobody is asked by accident.** Everything in ADR 0059's sending rules
   applies. In addition the feature is off unless `INBOX_FEEDBACK_ENABLED` is
   set; until sending is allowed it records what it would have sent and sends
   nothing. An admin can send the first question to a number of his choosing as
   a test, at once and with the feature still off for everyone else; the
   test runs the real flow (and issues a real code) but is never counted in
   the sheet, Today or the sidebar, and never stands in the way of a real
   question for that phone.

This amends ADR 0059 (what the platform sends, and what it writes to Shopify)
and narrows ADR 0015 a second time.

## Consequences

- Customer name, phone and product titles for asked orders are stored, in an
  inbox table only. They are read from Shopify when the order falls due.
- An order Shopify marks delivered without a date is never asked.
- A customer who answers everything costs one template and up to four chat
  messages; one who ignores it costs one template.
- A reply that is not a tap (she types "good" instead) is kept as a chat
  message for a person to read; it is not guessed into an answer.
- The owner has two templates to get approved by Meta and one permission to
  add to the second Shopify app before it can be switched on.

## Alternatives

- **Google Forms.** Rejected with the owner: fewer answers, and answers not
  tied to orders.
- **One shared code (`FB20`).** The owner's fallback if codes cluttered
  Shopify. Not needed: one discount holds every code.
- **A code only for happy customers.** Rejected: it rewards those most likely
  to return anyway and gives nothing to a customer whose problem was fixed.
- **Triggering from the courier's own delivered status.** Rejected: delivery
  stays Shopify's answer (ADR 0023).
