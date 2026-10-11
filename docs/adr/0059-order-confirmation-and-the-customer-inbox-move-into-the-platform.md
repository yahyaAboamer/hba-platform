# 0059. Order confirmation and the customer inbox move into the platform, which now holds customer chats and writes order tags

**Status:** Accepted — owner, 11 October 2026. **Not built.** Work starts only after the audit repair's release gates are finished. The plan is `docs/plans/2026-10-11-whatsapp-inbox-and-order-confirmation.md`.
**Date:** 2026-10-11
**Follows:** 0057 (Operations is a separate, read-only dashboard), 0015 (Shopify is read with client credentials and no write access), 0045 (keys are kept encrypted in Settings), 0009 (Postgres is the job queue)
**Narrows:** 0015's "this platform only reads from Shopify" and the "no customer data" rule in `docs/RULES.md`. Both now have one stated exception each, below.
**Amends:** 0057, when built: Operations gains a fourth tab, and the operations manager also holds the inbox.

## Context

HBA confirms cash-on-delivery orders over WhatsApp. Since July 2026 this has run outside the platform, in a Railway project called `order-confirmation-message`: an n8n instance and its own Postgres, in production only. The owner built it as a first version that does the job.

What it does, read from its workflows on 11 October 2026:

- Shopify sends each new order to n8n, which queues it.
- Every minute a worker takes the next order. If it is cash on delivery or payment is pending, it sends the approved WhatsApp template `order_confirmation` with the order name, first name and total, and tags the order `WA Sent 📤`.
- The message has three buttons. A tap tags the order `Confirmed ✅`, `Edit ✏️` or `Cancelled ❌` and sends a short automatic reply.
- If WhatsApp reports the message undelivered, `WA Sent 📤` is swapped for `No WhatsApp 📵`.
- A chat page served by n8n lets staff read and answer customers. Meta gives an API number no chat screen of its own, which is why the page exists.

What is wrong with it:

- **No accounts.** The chat page has no per-person sign-in and no record of who sent what.
- **It shows at most 200 chats and 500 messages a chat.** These are fixed caps, because the page loads everything at once.
- **Media breaks.** Images and voice notes are fetched from Meta each time they are viewed, and Meta deletes them after about a month.
- **Failures are easy to miss.** 220 of 3,042 queued orders ended as failed. Seven runs failed between 9 and 11 October. They show only inside n8n.
- **It is edited live in production**, with no tests, no staging copy and no history of changes.
- **It costs a second system.** n8n holds about 0.48 GB of memory whatever the traffic, which is most of that project's bill. The stored chats are not the cost: 13,603 messages take 2.8 MB.

Volumes, for scale: 2,995 conversations in total. In September 2026, 1,100 confirmations were sent and about 1,250 other messages went out. Of those, 1,020 were automatic replies to a button tap (880 to Confirm, 74 to Cancel, 66 to Edit) and about 225 were typed by staff.

Providers report that from 1 October 2026 Meta bills free-form replies per message at each country's utility rate, with 1,000 free per number per month. Meta's own pricing page still described them as free when read on 11 October. The owner's invoice is the answer; this decision does not depend on it.

The owner's requirements, set on 11 October 2026: everything in one place; a real chat that shows every conversation and works like WhatsApp for what staff need; a role so a customer-service employee can sign in and use it.

## Decision

1. **The automation is rebuilt as code inside the platform, and n8n is retired** once the platform has taken over.
2. **Inbox is its own dashboard**, beside the affiliate dashboard and Operations. It is not a tab inside Operations, which stays read-only (0057).
3. **A new role, customer service**, holds one permission, `inbox.use`.
   - They land on Inbox and see nothing of models, codes, targets, payroll, payments or Operations.
   - **The operations manager holds `inbox.use` too** (owner, 11 October 2026). He still lands on Operations and switches to Inbox; he still sees nothing of models, codes, targets, payroll or payments, and still invites nobody.
   - Affiliate managers, content managers and models see nothing of Inbox.
   - The admin holds everything and switches between the three dashboards.
   - Several people may hold the customer-service role at once. Only an admin gives it.
4. **Staff keep chatting on the API number.** The owner considered moving conversations to a second, ordinary WhatsApp number and rejected it, accepting Meta's per-message cost.
5. **The inbox is a full chat for what staff need**:
   - every conversation, loaded as you scroll, with search by phone, name and order number;
   - text, images, voice notes, video and files, both ways;
   - replying to a specific message, reactions, and sent, delivered and read ticks;
   - unread counts, and the order's details beside the chat.

   It has no calls, statuses, groups or WhatsApp settings.
6. **The 24-hour rule is shown, not hidden.** When a customer has been silent for 24 hours the chat says so and offers only approved templates.
7. **Every outgoing message records who sent it**: the staff member, or the system for automatic ones.
8. **The confirmation rules do not change.** One confirmation per order, only for cash on delivery or pending payment, to the customer's Egyptian number, with the same template and the same five tags. A failed send is retried up to five times and then shown as failed.
   - **Automatic replies after a button tap** (proposed to the owner on 11 October 2026; awaiting his confirmation):

     | Tap | Reply | Why |
     |---|---|---|
     | Confirm | None | WhatsApp already shows the customer their own tap, and it is 880 of the 1,020 automatic replies a month |
     | Edit | Kept as it is | Without it the customer does not know to type what they want changed |
     | Cancel | Kept, reworded to say the request was received | The order is only tagged, not cancelled, so "your order has been cancelled" is not yet true |
9. **The platform now stores customer data, in the inbox's own tables only**: phone, name, message text and media.
   - `order_index` and `attributed_order` still hold none, and the test that keeps that true stays.
   - Operations still shows none (0057, point 7).
   - Conversations are kept without a time limit.
10. **The platform now writes to Shopify, and only order tags.** It adds and removes the five confirmation tags and nothing else. It never cancels or edits an order: a customer's Cancel or Edit is a tag for staff to act on.
11. **Tag writes use a second Shopify connection, not the money connection.** The existing connection stays read-only exactly as 0015 requires. The inbox uses its own credentials, limited to what it needs.
12. **Media is copied to our own storage when it arrives**, in an object bucket, and is served only to a signed-in person holding `inbox.use`.
13. **Meta's callbacks are checked and never trusted blindly.** Each one is verified by its signature, stored before anything acts on it, and applied once however many times Meta repeats it.
14. **Sending runs in its own lane of the background worker**, so a Meta outage never delays order sync or anything that decides pay.
15. **Staging never messages a customer.** Outside production the platform sends only to numbers on a short list of test phones.
16. **Keys are kept encrypted in Settings**, as the Shopify secret is (0045): Meta's token, phone number id, app secret and callback check word, and the second Shopify connection.
17. **The old chats are imported.** Media that Meta has already deleted cannot be recovered and shows as no longer available.
18. **Operations gains a fourth tab, WhatsApp, that shows the failures** (owner, 11 October 2026). It sits beside Shopify, Bosta and E-stebdal and follows Operations' rules (0057):
    - it only reads, and nothing on it sends or retries; each row links to the Inbox, where the fix is made;
    - it lists order numbers and the reason, and no name, phone or message text;
    - it shows confirmations that failed to send, numbers with no WhatsApp, orders never messaged, callbacks that could not be applied, and when Meta was last heard from;
    - a source that cannot be read shows as a failure, never as 0.

## Consequences

- **Every reply costs money once Meta's new pricing applies.** At September's volume that is about 1,100 templates and about 1,250 other messages a month. Dropping the Confirm reply takes the other messages down to about 365 a month.
- **The operations manager now sees customer phones and conversations**, which 0057 kept from him. That holds inside Inbox only; the Operations tabs still show none.
- **A customer who taps Confirm hears nothing back.** If customers start asking whether it worked, the reply can be restored at its per-message cost.
- **The platform now holds customer phones and conversations.** A leak or a stolen backup exposes more than before. Every backup, every restored copy and the reconciliation copy used for the release gates must be handled as customer data from then on.
- **The platform can now change something in Shopify.** The exposure is limited to order tags by a separate connection, but a bug could mis-tag an order, and Operations reads those tags.
- **Operations and the inbox share a spelling.** A renamed tag breaks both the confirmation flow and an Operations card.
- **A new outside dependency in the request path.** Meta's API limits, template approvals and number quality rating are now the platform's problem to show and explain.
- **Meta sends callbacks to one address per app.** The switch from n8n is a single moment, not a gradual one, and a mistake means customers get two messages or none.
- **A chat needs to feel live.** The service runs one process on one replica; the inbox must refresh every few seconds without loading the whole list, or it will be the heaviest screen on the platform.
- **More storage to look after**: an object bucket, with its own cost and backup.
- **New screens without an approved export.** Like Operations, Inbox is built from an owner-approved mockup and recorded as a divergence.
- **Losing n8n loses quick edits.** Changing the message flow becomes a code change and a deploy.

## Alternatives considered

- **Keep n8n and leave things as they are.** Rejected: none of the faults above goes away, and it stays a second system with its own bill.
- **Keep n8n and show its chat page inside the platform.** Rejected: two databases and two ways in, and the page's limits remain.
- **Two numbers: the API number only for automation, chats on an ordinary WhatsApp number.** Cheaper per message. Rejected by the owner on 11 October 2026: the chats would live on a phone, outside the platform, with no record of who said what and no link to orders. A template button also cannot link straight to WhatsApp, so the hand-off would be a number in the text.
- **Meta's coexistence mode**, one number in both the WhatsApp Business app and the API. Not chosen: availability for Egyptian numbers was not confirmed, replies would still be typed on a phone, and it was not what the owner asked for.
- **A paid shared-inbox product.** Rejected: a monthly fee per seat, and conversations would again sit outside the platform.
- **The whole inbox as a tab inside Operations.** Rejected: Operations only reads and shows no customer details (0057). Only the read-only failures tab lives there.
- **Failures shown only inside Inbox.** Rejected by the owner: the operations manager should see them where he already looks.
- **Give the existing Shopify connection write access.** Rejected: the connection that reads money would gain the power to change orders, which is the exposure 0015 refused.
- **Store media in the database, as payment proof is.** Rejected: proof images are small and compressed; voice notes, video and files are not, and would grow every backup.
