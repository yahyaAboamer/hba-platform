# 0062. An unpaid international order is sent a payment link on WhatsApp

**Status:** Accepted
**Date:** 2026-10-18

## Context

The store has two Shopify markets: Egypt, and International for everywhere
else, with its own prices. Orders from both markets go through the same
checkout, and that checkout offers cash on delivery to everybody. The owner
does not ship an international order before it is paid, and does not want
bank transfers, which carry heavy fees. Payment should go through the
store's own card payment (Paymob), which pays out in Egypt.

Some international customers pay at checkout and some choose cash on
delivery. On 18 October 2026, orders #31510 (Saudi Arabia) and #31375 (Iraq)
were both unpaid cash-on-delivery orders. Neither customer heard from the
platform at all, because the confirmation (ADR 0059) is sent only to an
Egyptian mobile number.

Hiding cash on delivery at checkout for international buyers was looked into
first (see *Alternatives considered*). It cannot be done on the store's plan
without Shopify Plus or an installed app.

What can be done: Shopify keeps a payment page for every order that still
owes money. It is the same page the admin's *Send invoice* email links to,
and the Admin API returns it as
`Order.paymentCollectionDetails.additionalPaymentCollectionUrl` with the
`read_orders` scope the platform already holds. A read-only check of the live
store on 18 October 2026 found the link on every unpaid order, including
both international ones, always in the form
`https://hbawear.store/72695906535/order_payment/<order id>?secret=<code>`.
Those orders were placed in EGP, so the page charges EGP and the customer's
bank converts.

## Decision

1. **An international order is one shipped outside Egypt**: its shipping
   address has a country other than Egypt. An order with no shipping address
   is treated as it was before.
2. **An international order that still owes money gets a payment request
   instead of the confirmation.** "Owes money" means Shopify's amount
   outstanding is above zero, and the order is neither cancelled nor a test.
   An international order that owes nothing gets no message, as a paid
   order never did. The request is a row in the same table as the
   confirmation (`order_confirmation`, `kind = 'payment'`), so it inherits
   the confirmation's guarantees: one per order, claimed before sending,
   never sent twice, and recorded as `would_send` on a server that may not
   message customers.
3. **The message is the approved template `international_payment`**
   (English, Utility). It carries the customer's first name, the order
   number and the amount still owed in the order's own currency
   (`EGP 5,850.00`), plus one *Pay now* button. The button's fixed part,
   `INBOX_PAYMENT_LINK_BASE`, must equal the URL approved in the template.
   What follows the fixed part is sent per order.
4. **The link is read from Shopify each time a message is sent and is never
   stored.** It carries a secret that lets anyone holding it pay the order.
   A link that does not begin with the approved fixed part is not sent; the
   order is shown as failed with the reason. A broken link would fail
   without anybody knowing; a failed order shows on screen.
5. **A foreign number is read with the shipping country's calling code.** A
   number written with `+` or `00` is taken as written. One written the
   local way is given the country's code, with a leading `0` dropped. A
   result that is not 8 to 15 digits, or a local number from a country the
   platform has no code for, is refused rather than guessed at. So is a
   number that could be read both ways: `010…` on an order abroad (an
   Egyptian mobile, or a local number), and a number of ten digits or fewer
   that begins with the country's own code (`3931234567` to Italy). This is the
   one exception to ADR 0059's *only an Egyptian mobile is messaged*, and it
   applies only to payment requests.
6. **Shopify's own invoice email is also sent, once.** It is sent through
   the second Shopify app (`orderInvoiceSend`, `write_orders`), only on a
   server that may message customers, and only while the order still owes
   money. It also goes when the customer has no usable WhatsApp, which is
   when it matters most. The request is never retried: if Shopify does not
   answer, it may still have sent the email, so the order says so and a
   person checks the order's timeline. This is the second thing the platform writes to
   Shopify, beside the tags (ADR 0059, point 10). The money connection stays
   read-only (ADR 0015).
7. **The order carries one of three new-or-existing tags**:
   `Awaiting payment 💳` once the message has gone, `Paid 💳` once it is
   paid, and `No WhatsApp 📵` when the number cannot be reached. The tags
   are written through the same second app, and an order still carries
   only one of the platform's tags at a time. A request that was never
   sent is never tagged, so a server that may not message customers never
   writes to the store.
8. **One reminder, 24 hours after the first message**, if the order still
   owes money and is not cancelled. The same template is used, so Meta
   reviews one message. There is never a second reminder.
9. **After 72 hours unpaid, the order is shown as needing a person.**
   Nothing is ever cancelled automatically.
10. **Paid is noticed from the order's own sync.** When Shopify reports the
    order paid (or refunded), the request is closed: no reminder, and the
    tag becomes `Paid 💳`.
11. **Off unless the server is told** (`INBOX_PAYMENT_REQUESTS_ENABLED`),
    on top of the confirmation's own switch. While it is off, an
    international order is decided exactly as before. It is turned on
    after Meta approves the template and a link sent through it has been
    opened and tested. Both were done on 18 October 2026 (see the last
    alternative below).
12. **Inbox → Confirmations gains two cards**, *Waiting for payment* and
    *Paid by link*. This departs from the approved mockup
    (`docs/design/whatsapp-inbox-2026-10-11.html`, frame 3, six cards). The
    owner asked for the feature on 18 October 2026, after the mockup.
    Payment requests stay out of *Waiting for an answer*, here and on
    Operations' WhatsApp tab: there is nothing for the customer to tap.

## Consequences

- Meta charges each Utility message at the rate of the customer's
  country, which is higher outside Egypt. A reminder doubles it for an
  order that stays unpaid.
- If the store's primary domain changes, the link's fixed part changes with
  it. Every request then fails as *link does not match* until the template
  is edited, re-approved and `INBOX_PAYMENT_LINK_BASE` is updated. It fails
  loudly, never by sending a dead link.
- Before 18 October, WhatsApp could only ever reach an Egyptian number. Now a
  foreign number read the wrong way would reach a stranger. Only a number
  that comes out as a well-formed international number is used, but the
  platform cannot know whether that is really the customer.
- The invoice email depends on the order having an email address. Without
  one, Shopify refuses and the order says so; the WhatsApp message is
  unaffected.
- The amount quoted is the order's currency, EGP today, not the currency
  the customer saw on the storefront.

## Alternatives considered

- **Hide cash on delivery at checkout for international buyers.** Shopify
  has no setting for a payment method per market on this plan. A payment
  customization function does this, but a *custom* app that contains a
  function runs only on Shopify Plus. A public App Store app may contain
  one on any plan, but that means going through App Store review or paying
  for somebody else's app, and the owner wants neither.
- **Copy the invoice link out of Shopify's email by hand.** That is what
  this replaces.
- **Shopify Flow.** Flow has no action that sends an order's invoice, and
  the platform can ask Shopify for the email itself.
- **International bank transfer.** Rejected by the owner for its fees.
- **A short link of our own that forwards to Shopify.** It would avoid any
  doubt about WhatsApp handling the `?` and `=` in the link, but it puts an
  unfamiliar domain in front of the customer and adds a public page. It is
  not needed. On 18 October 2026, after Meta approved the template, one
  message was sent from the live number to the owner's phone with the real
  link of his own unpaid order #31522. *Pay now* opened Shopify's payment
  page for #31522 showing EGP 12.00, so WhatsApp passes the `?` and `=`
  through unchanged.
