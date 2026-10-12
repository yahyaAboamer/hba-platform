# WhatsApp inbox and order confirmation: phased plan

**Decision record:** `docs/adr/0059-order-confirmation-and-the-customer-inbox-move-into-the-platform.md`
**Written:** 11 October 2026
**Started:** 11 October 2026, on the owner's order, ahead of the audit repair's release gates.
**Branch:** `feature/whatsapp-inbox`, cut from `repair/batch-2`. It stays off the repair branch so the repair remains releasable, and nothing is merged or deployed without the owner's separate go-ahead.
**Where it stands (12 October):** mockup `docs/design/whatsapp-inbox-2026-10-11.html` approved by the owner on 11 October. Phases 1 and 2 are on production, with the engine running silently. Phases 3 and 4 are built on the branch and deployed nowhere; each has an "as built" section below saying what it still owes.
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
  - Production: `INBOX_CONFIRMATIONS_ENABLED=true` (set 11 October, phase 2). `INBOX_SEND_TO_CUSTOMERS=true` at the switch-over in phase 7 and not before.
  - Staging reports `APP_ENV=production`, so nothing about sending may be decided from `APP_ENV`.
  - **`SETTINGS_ENCRYPTION_KEY` was set on both on 12 October**, on the owner's order, a different key on each, generated on the spot and never displayed. It lives only in Railway's variables; the owner keeps a copy. **Never change or delete it**: every key saved from Settings would have to be typed in again.
  - **Media buckets, created 12 October**: `inbox-media-staging` and `inbox-media-production`, region `ams`. Each app service reads its own through `INBOX_MEDIA_BUCKET`, `INBOX_MEDIA_ENDPOINT`, `INBOX_MEDIA_ACCESS_KEY_ID`, `INBOX_MEDIA_SECRET_ACCESS_KEY` and `INBOX_MEDIA_REGION`, set as references to the bucket, so no credential was ever typed or shown. They take effect at each service's next deploy. Railway's buckets are addressed with the bucket name as a subdomain of the endpoint.

## Phase 2 — Confirmation engine, running silently

- On each new order the platform decides what n8n decides: cash on delivery or pending payment, the Egyptian number, the three template values. A paid order is recorded as finished with no message, not as failed.
- It records what it **would** send and sends nothing.
- A job in its own worker lane, with the retry rule (five attempts, then failed).
- The reconciliation sweep also feeds it, so an order whose webhook was missed is still caught.
- A daily comparison against n8n's own record of sends.

**Done when:** over seven days in production, every order n8n messaged is one the platform would have messaged, and the reverse, or each difference is explained in writing.

### Phase 2 as built (11 October 2026)

- **The engine** (`app/services/inbox/confirmations.py`): one decision per order, recorded in `order_confirmation` as `would_send`, `not_needed`, `no_phone` or `bad_phone`, with the reason. It has no way to reach WhatsApp, and a test keeps it so.
- **Its own Shopify query**, read with the platform's existing read-only connection. Run against the real store from staging on 11 October: every field answers.
- **When an order is considered**: as soon as it is indexed (the webhook's path), and by a sweep after each reconciliation for an order whose webhook was missed.
- **Its own worker lane**, `inbox`, beside `main` and `operations`.
- **The comparison** (`app/services/inbox/shadow.py`): run by hand with n8n's order ids, it prints what agrees and each difference by order number, with no name or phone.

Where it differs from n8n, on purpose:

| | n8n | The platform |
|---|---|---|
| A paid order | Dropped unmarked, retried, called failed | `not_needed`, finished |
| The phone | The first one on the order, whatever it is | The first that reads as an Egyptian mobile |
| A number that is not an Egyptian mobile | Messaged anyway | `bad_phone`, shown for a call |
| An order already cancelled or a test order | Messaged | `not_needed` |
| An order met more than 48 hours late | Never met late | Not considered at all |

Each of these will show as a difference in the comparison, and is its explanation.

- **A switch**, `INBOX_CONFIRMATIONS_ENABLED`, off unless set. Off, nothing is queued, nothing is read from Shopify and nothing is kept. The owner's decision on 11 October: on in production, off on staging, because staging reads the real store and a decision keeps a customer's phone and first name. Turn it on there only for a test.

Left of phase 2:

- **The seven-day comparison.** Deployed to production on 11 October, 18:28 UTC, on the owner's order, switched on. The comparison runs from the first full day after that, 12 October.

First run, 11 October 18:52 UTC, over the 59 orders of the 48 hours before the deploy (which the first sweep picked up):

| | Orders |
|---|---|
| n8n messaged | 51 |
| The platform would message | 45 |
| Both | 45 |
| Only the platform | 0 |
| Only n8n | 6 |
| Paid, no message from either | 7 |

All 6 that only n8n messaged are orders cancelled **after** n8n had messaged them. The platform met them up to two days late in this first sweep and found them already cancelled. It is the "already cancelled" row of the table above, and should not recur for an order decided within seconds of arriving. No job failed, and every would-send row carries a phone, a first name and a total.
- **A late order at the switch** (phase 7): whether an order found hours late is messaged automatically or left for Send again is the owner's to decide then. For now nothing sends.

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

### Phase 3 so far (11 October 2026)

Built on the branch, not deployed. Nothing on staging or production runs it. Whole suite 107/107 at `c3cb773`.

**Part a, receiving** (`d811c68`):

- `/api/webhooks/meta`: a callback is checked against the saved app secret, stored whole by the SHA-256 of its bytes, queued and answered. Unsigned, forged or arriving before WhatsApp is connected, it is refused and nothing is kept. Meta's one-time check of the address answers only to the saved check word.
- `app/services/inbox/events.py` applies it in the inbox lane: a message opens or joins a conversation; a file is recorded as waiting to be copied; a tap is kept as the order's answer, the latest winning, including a tap on a message n8n sent; a tick moves one of our messages forward and never back.

**Part b, sending and tagging** (`c3cb773`):

- `app/services/inbox/outbound.py`, the one place a message is sent from. The confirmation is the approved message exactly as n8n sends it (read from n8n's workflow). It is tried five times, a number with no WhatsApp is not retried, and an order is claimed before WhatsApp is asked so it is sent at most once. An order a crash left half-sent is shown as failed, never sent again.
- The two automatic replies: Edit as before, Cancel reworded, none after Confirm. One per tap, and only while the tap is fresh (15 minutes).
- `app/services/inbox/tags.py`, the only thing the platform writes to Shopify: one of the five tags per order, through the second app. Checked against n8n: answering clears *WA Sent*, as n8n does.
- **An order recorded as `would_send` is never sent later.** Turning sending on affects orders decided from then on.
- Migration `d3f6b9c40015` adds the `sending` state.
- **A tap is believed only from the order's own phone** (security review, 11 October). The order number inside a tap is whatever the sender's phone sent, and a modified WhatsApp can name any order. A tap naming somebody else's order, or one with no record, stays in the chat and changes no order, tag or reply.

**Part c, what the screens read and staff do** (`4cdee64`, whole suite 109/109):

- `app/services/inbox/chats.py` and the routes in `app/api/inbox.py`, all behind `inbox.use`: the list a page at a time with four views and a search by name, phone or order number; a chat paged backwards with who sent each message; a reply and a reaction under the staff member's name; marking read; Send again; recording her answer by hand; the Confirmations cards.
- `app/services/inbox/health.py` and `GET /api/order-ops/whatsapp`, behind `order_ops.view`: Operations' five cards, with an order number and a reason and no customer detail.
- Send again is refused for any order that has, or may have, its message. It and a hand-recorded answer are audited, under a new activity-log kind, Inbox.
- **Each message's record of who sent it is the message itself** (`sent_by`), not a line in the activity log: a busy day would bury everything else there.

**Part d, files** (`08ce682`, whole suite 111/111):

- `app/services/inbox/storage.py`: the bucket, through a small client of its own, not a library - three calls, on a small server. Its signing is checked against the worked example in AWS's documentation.
- `app/services/inbox/media.py`: a customer's file is queued to be copied when its message arrives; kept under `inbox/<conversation>/<message>/<file>`; served through the server to a signed-in holder of `inbox.use`, and only a photo, audio, a video or a PDF is shown in place - anything else is a plain download the browser may not run.
- Staff send a photo, a voice note, a video or a document, under the same rule on who may be messaged. The approved messages are read from Meta for the closed-window picker.
- A file larger than 25 MB is not copied: the server holds a file in memory while it copies it.

Phase 3 is built. What it still owes before it is done:

- **An independent security review** of the receiver and the media endpoint. Both were written against the risks named here and tested for them, and the automated review found one fault in part a, since fixed; nobody other than the author has reviewed them.
- **Nothing has met the real thing.** Meta, Shopify's tag writes and the Railway bucket are all stand-ins in the tests. That is phase 6.
- **A voice note recorded in a browser.** Done in phase 4: the browser now hands the server an Ogg file.
- **Sending an approved message other than the order confirmation.** Done in phase 4 for a message with nothing to fill in. One with blanks of its own, other than the confirmation, still waits for the owner to say which messages exist (phase 0's open row).

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

### Phase 4 as built (12 October 2026)

Commits `9fc3944`, `292a4a5`, `5ea7d0d`, and `4f939f5` for the owner's choices. **On staging and production since 12 October** (`4f939f5`, the owner's order), with migration `d3f6b9c40015`. Customers still receive only what n8n sends: nothing on either server may message them.

- **Who lands where.** Customer service signs in to the Inbox and nothing else. The operations manager gains it beside Operations. The admin holds all three dashboards. The switch under the brand shows only what a person holds, so customer service sees none. Operations and the Inbox share one shell (`SideShell`).
- **Operations → WhatsApp**, the fourth tab: the five cards, each with its orders, an order number and a reason and no customer detail. Each order opens in the Inbox on the card it stands under.
- **Inbox → Confirmations**: the six cards, Send again, and the number to call for an order with no WhatsApp.
- **Inbox → Chats**: every conversation a page at a time, search, the four views, read again every 5 seconds. The open chat: who sent each reply, ticks, dates, her taps, replies, reactions, photos, voice notes, videos and files, read again every 4 seconds. The order beside it, where her answer is recorded by hand.
- **The composer**: text, a file with a caption, a voice note recorded in the browser, and the approved messages. Once her 24 hours have passed the box is replaced by the reason and the approved messages.
- **Settings**: the WhatsApp card says when WhatsApp was last heard from and how Meta rates the number.
- **On a phone**: the list, then the chat with its own way back, then the order behind the Order button.

What the server gained for it:

- Each order's link into the Shopify admin, how long an order has waited and the tag it carries (Operations), and the number to call (Confirmations).
- **Whether WhatsApp has gone quiet.** Not "nothing for a while": at night nothing arrives for hours and nothing is wrong. It is quiet when the platform sent something more than 10 minutes ago and has heard nothing since, not even that it was sent. Shown on Operations → WhatsApp and at the top of Chats (`GET /api/inbox/health`).
- **Sending an approved message from a chat** (`POST /api/inbox/conversations/{id}/template`). Meta's list is read again for the send, so only a message approved now, with nothing left to fill in, can go out. It is held to the rule on who may be messaged and carries the sender's name. The order confirmation is filled in from an order, so it is listed with the reason and is not sent from a chat.
- `GET /api/inbox/connection/health`, admin only, for the Settings card.

**A voice note.** WhatsApp shows one only for Opus sound in an Ogg file, and Chrome records the same sound in a WebM file. The browser lifts each packet of sound out of the WebM and writes it into an Ogg, with nothing re-encoded (`frontend/src/lib/oggOpus.ts`). It is recorded in one channel, mixed down where the microphone hands over two. Firefox records Ogg already. **Safari records another kind of sound; from Safari it arrives as an audio file that plays, not as a voice note.**

Where it differs from the mockup, on purpose:

| The mockup | As built | Why |
|---|---|---|
| The order panel lists the payment method and the items | Number, placed and total only | The platform keeps neither for a customer's order (ADR 0059, point 9). They are one click away in Shopify. **The owner chose this on 12 October** |
| Two tags on the order, *WA Sent* and *Edit* | One | Answering clears *WA Sent*, as n8n does (phase 3) |
| A search button inside the chat | Built on 12 October, on the owner's word; the bar it opens is not drawn | It searches the server, not the screen (below) |
| White on the accent green on filled buttons | The same look, the green slightly darker in the dark theme only (`--accent-fill`, `#1C874A`) | White on `#23A95C` is 3.04:1; on `#1C874A` it is 4.55:1. The owner chose this on 12 October |
| A *New* label on Operations' WhatsApp tab | Not there | It marked the tab for the approval; left on, it would be untrue within a week |
| A second approved message, *We tried to reach you* | Whatever Meta has approved is listed | That message does not exist yet. The day Meta approves one with nothing to fill in, it can be sent with no change to the platform |
| One list drawn on Confirmations, *Not sent* | All six cards open | Each with the column it is about: when it was sent, when she answered, the number to call. An order that has a chat opens it |
| A fixed "not heard from for 40 minutes" | The rule above | A clock alone would raise the alarm every night |
| No way drawn to reply to one message or to react | Shown on a message when the pointer or the keyboard is on it; on a phone, when it is tapped | ADR 0059, point 5, has both |
| On a phone the account sits in the brand row | Under the tabs | As Operations does today; the shell is shared |
| Full names on Confirmations | First names | The first name is what the platform keeps for an order |

Seen working in a real browser on 12 October, on a local copy with a throwaway database holding the mockup's own cast (`docs/repair/batch-2/visual/seed_inbox.py`): signing in as customer service, as the operations manager and as the admin; the three dashboards' switch; Chats, an open chat and the order panel at 1280 and at 390; marking read; Confirmations; Operations → WhatsApp; a reply refused with the server's reason; and a voice note recorded in Chrome from a generated tone, which the app turned into an Ogg file that the browser decoded at the length recorded, in one channel.

**The owner's choices of 12 October** (commit `4f939f5`):

- **The filled green in the dark theme**: the look is kept and the fill darkened slightly in dark only. A new token, `--accent-fill` in `styles/accent.css` (`#14653A` light, `#1C874A` dark), is the background of every Inbox fill that carries white: the buttons, the send and play buttons, the unread count. Nothing outside the Inbox changed.
- **The payment method and the items**: left one click away in Shopify, as built. Nothing more is kept about a customer's order.
- **Search inside one chat**: the search button in the chat's head opens a bar under it. What is typed (two letters or more) is asked of the server, `GET /api/inbox/conversations/{id}/search?q=`, which returns up to 100 matches newest first, on the message's words or its file's name; a reaction is not searched, and `%` and `_` are letters. The newest match is brought into view, picked out with its words marked. A match above what is loaded is reached by reading earlier pages until it is there. Enter or the up arrow goes to the earlier match, Shift+Enter or the down arrow to the later, Escape closes and returns to the button. "2 of 5" is announced as it changes.
- **The branch on staging and production**: ordered by the owner the same day.

What phase 4 still owes before it is done:

- **Captured comparisons against the mockup.** The screens were looked at beside it by eye. The harness's own capture-and-compare has not been run on them.
- **The flows on staging.** The code is there; trying them needs the WhatsApp keys and test numbers on staging and a customer-service test account. The cloud session that deployed could not sign in to staging (no browser password origin there), so nobody has clicked through it on staging yet.
- **A real screen reader.** The screens are built for one (names on every control, the new-message announcement, focus that follows the keyboard) and none has been tried on them. Known and not yet done: Reply and React are two stops for the Tab key on every message.
- **A kept photo, voice note or video on screen.** That needs the media bucket, so it is phase 6. Until then only "being fetched" and "no longer available" have been seen in a browser; a kept file is covered by tests.

## Phase 5 — Import the old chats

- Read n8n's Postgres read-only: 13,603 messages, 2,995 conversations and the record of sends (11 October figures).
- The import can be run again without duplicating anything.
- Media still held by Meta is copied; the rest is marked no longer available.
- The record of sends is imported first, so nothing n8n already confirmed is ever sent again.
- **Each imported send carries the order's phone.** A tap is believed only for an order whose recorded phone is the phone it came from, so an order imported without one could never be answered.
- Rehearsed on a throwaway database before it touches staging or production.

**Done when:** conversation and message counts match the source, and a spot check of twenty conversations reads the same in both.

### Phase 5 so far (12 October 2026)

Started, and waiting on one thing: **the shape of n8n's tables.** Neither the plan nor the code records the names of n8n's chat, message and send tables or their columns, and a cloud session cannot reach n8n's database. `docs/plans/inbox-phase5-n8n-schema.sql` is a read-only query that returns table names, row counts, columns, keys and indexes, and no row's values. Its output, pasted into the session, is what the importer is written against.

What the importer will be, from what is already built:

- A module, `app/services/inbox/importer.py`, run by hand on the server like `shadow.py`, reading n8n's database through a read-only connection given on the command line, never stored.
- The sends first, into `order_confirmation`, each with the order's phone, so nothing n8n confirmed is sent again and a tap on an old message is believed.
- Then conversations by phone, then messages, each keyed `n8n:<id>` in `inbox_message.source_ref`, which is unique, so a second run adds only what is new. Imported replies carry the origin `imported`.
- Media: copied while Meta still holds it, else marked `gone`.
- Rehearsed on a throwaway database with a copy of the source before staging or production. The counts are compared with the source, then twenty conversations by eye.

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

- The three phase 0 rows only the owner can answer.
- **The wording of new approved messages**, such as *We tried to reach you*, which he submits to Meta. One with nothing to fill in works from a chat the day it is approved.
- To try the Inbox on staging: the WhatsApp keys and the second Shopify app typed into Settings there, `INBOX_TEST_NUMBERS` on the staging service, and a customer-service test account.
