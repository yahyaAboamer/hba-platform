# WhatsApp inbox and order confirmation: phased plan

**Decision record:** `docs/adr/0059-order-confirmation-and-the-customer-inbox-move-into-the-platform.md`
**Written:** 11 October 2026
**Started:** 11 October 2026, on the owner's order, ahead of the audit repair's release gates.
**Branch:** `feature/whatsapp-inbox`, cut from `repair/batch-2`. It stays off the repair branch so the repair remains releasable, and nothing is merged or deployed without the owner's separate go-ahead.
**Where it stands:** mockup `docs/design/whatsapp-inbox-2026-10-11.html` approved by the owner on 11 October. Phase 1 is built on the branch; see "Phase 1 as built" below for what is left of it.
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

Answered on 11 October 2026, each by a read-only check:

| Check | Answer | What it changes |
|---|---|---|
| Which Shopify app n8n uses | A different app from the platform's, on the same store | The second connection (ADR 0059, point 11) is that app; no new app is needed |
| What the platform's own app may read | Read access only, and it already includes the customer's name and phone | Intake reads the phone through the existing connection. The second connection only writes tags |
| Why 220 queued orders ended as failed | All 220 are paid orders, which are never meant to get a message. n8n drops them unmarked, retries five times and calls them failed. All 2,823 sent ones are cash on delivery | No customer was missed. The rebuild records a paid order as finished, so the failed count means something |
| How the n8n chat page checks who may use it | One fixed key in the page's address, shared by everyone | Anyone who has seen the link can read every chat. A reason not to delay the switch |
| Where n8n keeps its Shopify secret | In plain text inside the workflows | The secret is replaced when n8n is retired |
| How long Meta keeps media | 7 days for an incoming file; a download link lasts 5 minutes | Media is copied the moment it arrives. Almost none of the old media can be imported |
| An object bucket on Railway | $0.015 per GB a month, downloads free | Media storage costs cents |

Still to be answered, by the owner:

| Check | Why it matters |
|---|---|
| October's charges in WhatsApp Manager | Settles whether free-form replies are billed |
| Who owns the Meta business account, the app and the number | Needed to change the callback address in phase 7 |
| The approved templates, and their exact wording | Outside the 24-hour window only these can be sent |

Also in this phase:

- **Mockup of the Inbox and of the Operations WhatsApp tab**: `docs/design/whatsapp-inbox-2026-10-11.html`. The owner approves it before any screen is built, the way Operations was. Desktop and phone.
- **Automatic replies**: settled by the owner on 11 October (ADR 0059, point 8).

**Done when:** the three remaining rows have answers written here, and the mockup is approved.

## Phase 1 — Foundations

- Tables for conversations, messages, media, confirmation sends and Meta's raw callbacks. Migration with a tested rollback.
- The `customer_service` role and the `inbox.use` permission, which the operations manager also holds. Tests that affiliate managers, content managers and models are refused, that customer service is refused everything else, and that the operations manager gains Inbox and nothing more.
- Settings → a place for the Meta keys and the second Shopify connection, encrypted and checked against the provider before saving, as the Shopify secret is.
- A Meta client: send template, text and media; fetch media; mark read. Tested against a fake, never the real API.
- `docs/RULES.md` updated for the two narrowed rules: customer data lives only in the inbox tables, and the platform writes order tags only.
- The structural test that keeps customer data out of `order_index` and `attributed_order` stays and passes.

**Done when:** the suite passes, the migration goes up and down cleanly, and an admin can save and verify the keys on staging.

### Phase 1 as built (11 October 2026)

- **Migrations** `b1d4f7a20013` (the role) and `c2e5a8b30014` (seven tables), after `f6b2d8a41c57`. Rehearsed up, down and up again on the disposable database. The second one's downgrade drops every chat.
- **Role and permission**: `customer_service` holds `inbox.use`; the operations manager holds it too. Server-side tests cover who reaches the inbox and that it opens nothing else.
- **Tables** (`app/models/inbox.py`): conversations, messages, media, one confirmation per order, Meta's callbacks, and the two connections.
- **WhatsApp client** (`app/services/inbox/meta.py`): send text, template, media and reaction; mark read; upload and download a file; read the number and its approved messages; check a callback's signature. A file is fetched only from Meta's own hosts.
- **Connections** (`app/services/inbox/connection.py`, `/api/inbox/connection`, Settings → Shopify): the WhatsApp keys and the second Shopify app, saved encrypted and only after their provider answers. The app that reads money is refused as the second app, and so is an app that may not change orders.
- **Who may be messaged** (`app/services/inbox/sending.py`): sending is off until an admin turns it on; a server not told it may message customers (`INBOX_SEND_TO_CUSTOMERS`) messages only `INBOX_TEST_NUMBERS`; only an Egyptian mobile is accepted.
- **`docs/RULES.md`** carries the two narrowed rules and the inbox's own.

Left of phase 1:

- **Saving the keys on staging.** The branch went to `main` on 11 October on the owner's order. Staging has no `SETTINGS_ENCRYPTION_KEY`, so the cards refuse to save there until it is set.
- **The app secret is proved by the first signed callback**, not at save: Meta offers nothing to try it against. Phase 3 shows whether it has been proved.
- **A customer-service account has no screens yet.** Until phase 4 it signs in to the affiliate shell and is refused everything by the server. Do not invite one before then.
- **Railway variables**:
  - Staging: `SETTINGS_ENCRYPTION_KEY` (to save keys at all) and `INBOX_TEST_NUMBERS` (the test phones). Never `INBOX_SEND_TO_CUSTOMERS`.
  - Production: `INBOX_SEND_TO_CUSTOMERS=true`, at the switch-over in phase 7 and not before.
  - Staging reports `APP_ENV=production`, so nothing about sending may be decided from `APP_ENV`.

## Phase 2 — Confirmation engine, running silently

- On each new order the platform decides what n8n decides: cash on delivery or pending payment, the Egyptian number, the three template values. A paid order is recorded as finished with no message, not as failed.
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
- Replace the secret of the Shopify app n8n used, since the old one sat in plain text there.
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
- Work starts now, not after the release gates (he first said after, then ordered the start the same day).
- Operations gains a fourth tab, WhatsApp, showing the failures.
- The operations manager sees the Inbox as well as Operations.
- Automatic replies: none after Confirm, Edit kept, Cancel reworded to "We received your cancellation request ❌".

## Still open

- The owner's approval of the mockup.
- The three phase 0 rows only the owner can answer.
