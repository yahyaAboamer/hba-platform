# WhatsApp inbox and order confirmation: phased plan

**Decision record:** `docs/adr/0059-order-confirmation-and-the-customer-inbox-move-into-the-platform.md`
**Written:** 11 October 2026
**Starts:** only after the audit repair's release gates are finished. Nothing here is built yet.
**Replaces:** the Railway project `order-confirmation-message` (n8n + Postgres, production only).

## Shape of the work

Nine phases. Each ends with something the owner can check, and no phase changes what customers receive until phase 7.

| # | Phase | Size | Customers affected |
|---|---|---|---|
| 0 | Checks and approvals | Small, no code | No |
| 1 | Foundations | Medium | No |
| 2 | Confirmation engine, running silently | Medium | No |
| 3 | Inbox backend | Large | No |
| 4 | Inbox screens | Large | No |
| 5 | Import the old chats | Small | No |
| 6 | End to end on staging | Small | No |
| 7 | Switch over | Small, risky | **Yes** |
| 8 | Retire n8n | Small | No |

Phases 2 and 3 can overlap. Phase 4 needs phase 3. Phase 7 needs everything before it and the owner's separate go-ahead to deploy.

## Phase 0 — Checks and approvals

No code. Each item changes the design if the answer is not what we expect.

| Check | Why it matters |
|---|---|
| October's charges in WhatsApp Manager | Settles whether free-form replies are billed, and how much the automatic replies cost |
| Which Shopify app n8n uses, and what access it holds | Decides whether the second connection (ADR 0059, point 11) reuses it or needs a new app |
| Whether the platform's own Shopify webhooks carry the customer's phone | Shopify hides customer fields from apps without approved access. If hidden, intake reads the phone through the second connection |
| Who owns the Meta business account, the app and the number | Needed to change the callback address in phase 7 |
| The approved templates, and their exact wording | Outside the 24-hour window only these can be sent |
| How long Meta keeps media | Sets how soon media must be copied |
| Why 220 queued orders ended as failed | The rebuild should not copy the cause |
| How the n8n chat page checks who may use it | If it is weak, phase 7 becomes more urgent |
| An object bucket on Railway, and its cost | Media storage |

Also in this phase:

- **Mockups of the Inbox and of the Operations WhatsApp tab**, approved by the owner before any screen is built, the way Operations was. Desktop and phone.
- **The owner's confirmation of the automatic replies** proposed in ADR 0059, point 8: none after Confirm, Edit kept, Cancel kept and reworded. The new Cancel wording is agreed here.

**Done when:** every row has an answer written into this plan, and both mockups are approved.

## Phase 1 — Foundations

- Tables for conversations, messages, media, confirmation sends and Meta's raw callbacks. Migration with a tested rollback.
- The `customer_service` role and the `inbox.use` permission, which the operations manager also holds. Tests that affiliate managers, content managers and models are refused, that customer service is refused everything else, and that the operations manager gains Inbox and nothing more.
- Settings → a place for the Meta keys and the second Shopify connection, encrypted and checked against the provider before saving, as the Shopify secret is.
- A Meta client: send template, text and media; fetch media; mark read. Tested against a fake, never the real API.
- `docs/RULES.md` updated for the two narrowed rules: customer data lives only in the inbox tables, and the platform writes order tags only.
- The structural test that keeps customer data out of `order_index` and `attributed_order` stays and passes.

**Done when:** the suite passes, the migration goes up and down cleanly, and an admin can save and verify the keys on staging.

## Phase 2 — Confirmation engine, running silently

- On each new order the platform decides what n8n decides: cash on delivery or pending payment, the Egyptian number, the three template values.
- It records what it **would** send and sends nothing.
- A job in its own worker lane, with the retry rule (five attempts, then failed).
- The reconciliation sweep also feeds it, so an order whose webhook was missed is still caught.
- A daily comparison against n8n's own record of sends.

**Done when:** over seven days in production, every order n8n messaged is one the platform would have messaged, and the reverse, or each difference is explained in writing.

## Phase 3 — Inbox backend

- **Meta callback receiver.** Signature checked, stored first, applied once. Built and tested from recorded callbacks, not connected to Meta yet.
- **Button taps** become tags through the second Shopify connection: add the new tag, clear the old ones.
- **Automatic replies** as ADR 0059, point 8: none after Confirm, the Edit prompt, and the reworded Cancel notice.
- **The failures read for Operations**: failed sends, numbers with no WhatsApp, orders never messaged, callbacks that could not be applied, and when Meta was last heard from. Order numbers and reasons only, with no name, phone or message text.
- **Delivery failures** swap `WA Sent 📤` for `No WhatsApp 📵`.
- **Conversations and messages**: a page at a time, newest first, with search by phone, name and order number, and unread counts.
- **Sending**: text, image, voice note, video, file, reply to a message, reaction. Voice recorded in a browser is converted so WhatsApp shows it as a voice note.
- **Ticks**: sent, delivered, read, failed with Meta's reason.
- **The 24-hour window** worked out per conversation and returned with it.
- **Media** copied to the bucket on arrival; served only to a signed-in holder of `inbox.use`.
- **Who sent it** on every outgoing message, and in the audit log.
- **Resend missed confirmations**, as the n8n workflow does, limited to orders with no recorded send.
- **Sending is switched off** by a setting, and outside production allowed only to listed test numbers.

**Done when:** the suite covers each of these, including a repeated callback, a forged callback, an expired window and a refused role, and a security review of the receiver and the media endpoint finds nothing open.

## Phase 4 — Inbox screens

Built from the approved mockup.

- The Inbox shell, and the switch between dashboards for the admin and the operations manager.
- **Operations → WhatsApp**, the fourth tab: read-only cards and lists of the failures, each row linking into the Inbox, each card showing when it was read.
- Conversation list with unread counts, search, and loading as you scroll.
- The chat: bubbles, ticks, dates, media viewers, voice playback, reply and reaction.
- The composer: text, attach, record voice, and the template picker when the window is closed.
- The order beside the chat: order number, total, confirmation status, tags, with manual override of the tag.
- Resend screen and a health strip: last callback received, failed sends, Meta's number rating.
- New messages appear within a few seconds without reloading the list.
- Works on a phone at 390 wide, by keyboard, and with a screen reader.

**Done when:** the screens match the mockup in captured comparisons, `npm test` and `npm run build` pass, and the flows are exercised in a real browser on staging.

## Phase 5 — Import the old chats

- Read n8n's Postgres read-only: 13,603 messages, 2,995 conversations and the record of sends (11 October figures).
- The import can be run again without duplicating anything.
- Media still held by Meta is copied; the rest is marked no longer available.
- The record of sends is imported first, so nothing n8n already confirmed is ever sent again.
- Rehearsed on a throwaway database before it touches staging or production.

**Done when:** conversation and message counts match the source, and a spot check of twenty conversations reads the same in both.

## Phase 6 — End to end on staging

- A Meta test number connected to staging.
- A test order goes through the whole flow: confirmation, each of the three buttons, a typed reply, an image and a voice note each way, an undelivered number, a closed window.
- A customer-service test account does all of it and can reach nothing else.
- The operations manager's account reaches Operations and Inbox and nothing else, and a forced failure appears on the WhatsApp tab.

**Done when:** every step is seen working on staging and written up with evidence.

## Phase 7 — Switch over

Needs the owner's explicit go-ahead to deploy and to change Meta's settings.

1. Pick a quiet hour. Tell whoever answers customers.
2. Run the import once more for anything since phase 5.
3. Turn off the n8n workflows that send and tag. Leave n8n running.
4. Point Meta's callback at the platform.
5. Switch the platform's sending on.
6. Place one real test order and follow it through.
7. Watch the health strip and the failed list for the rest of the day.

**Going back:** point Meta's callback at n8n again, switch the platform's sending off, turn the n8n workflows back on. This stays possible for two weeks.

**Done when:** a full day of real orders has gone through with no double message and no missed one, checked against Shopify's order list.

## Phase 8 — Retire n8n

After two clean weeks, and only on the owner's word:

- Export the workflows and take a final database dump, stored with the other archives.
- Remove the Shopify webhook that points at n8n.
- Delete the Railway project.
- Record the divergence and the parity state, update the handoff, and note the saved cost.

**Done when:** the project is gone, the archive is verified readable, and orders are still confirmed.

## Decisions already made — not to reopen

From the owner, 11 October 2026:

- Code inside the platform, not n8n.
- Same Shopify store.
- Inbox is its own dashboard with a customer-service role.
- Staff keep chatting on the API number; the per-message cost is accepted.
- The old chats are imported.
- Work starts after the release gates.
- Operations gains a fourth tab, WhatsApp, showing the failures.
- The operations manager sees the Inbox as well as Operations.

## Still open

- The owner's confirmation of the automatic replies, and the new Cancel wording (phase 0).
