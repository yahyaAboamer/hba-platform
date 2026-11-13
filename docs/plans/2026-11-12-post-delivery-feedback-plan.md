# Post-delivery feedback on WhatsApp: plan

Rule: ADR 0083. Branch: `claude/post-delivery-feedback-workflow-29df80`.
Approved by the owner 12 November 2026. Merge and deploy each need his
separate go-ahead.

## Batches

| # | Batch | Status |
|---|---|---|
| A | Engine: table, trigger, first question, taps, follow-up questions, resolve, solved question. Silent unless switched on. | Built on this branch; tests pass; not merged |
| B | Codes: the one Shopify discount, a code per customer, 30-day clean-up, used-or-not, and the closing words that carry them. (Review link and promised hours are columns already; their settings card is batch C.) | Built on this branch; tests pass; not merged |
| C | Screens: Inbox → Feedback sheet with filters and download; *Needs follow-up* and *Feedback: neutral* chips; *Resolved* button; Today counts; settings card. | C1 (the API and read side) built on this branch; tests pass. C2 (the screens) not started |
| D | Switch-on: templates approved, discount permission added, test on the owner's phone, then on. | Waiting on the owner |

## Batch A: design

**Table `feedback_survey`** (inbox module; one row per asked or skipped order,
`shopify_order_id` unique):

- order: `order_name`, `delivered_at`, `courier`, `products` (JSONB list of
  titles), `conversation_id`, `phone`, `customer_name`
- sending: `state` (`pending`, `waiting`, `would_send`, `sending`, `sent`,
  `no_whatsapp`, `failed`, `skipped`), `skip_reason`, `attempts`, `next_attempt_at`,
  `last_error`, `wa_message_id` (unique), `sent_at`
- answers: `rating` (`loved`, `okay`, `unhappy`), `rated_at`, `reason`,
  `reason_at`, `comment`, `comment_at`, `reorder` (`very_likely`, `maybe`,
  `unlikely`)
- follow-up: `resolved_at`, `resolved_by`, `solved_asked_at`, `solved`
  (bool), `solved_at`, `reopened_count`
- code (filled in batch B): `code`, `code_sent_at`, `code_expires_at`,
  `code_used_at`, `code_order_name`
- `step`: what the chat is waiting for (`rating`, `reason`, `comment`,
  `support`, `solved`, `reorder`, `done`)

**Trigger.** Scheduled job `INBOX_FEEDBACK_SWEEP`, every 30 minutes, in the
inbox lane. Reads `order_index` for delivered orders due (decision 1), reads
phone, first name and line titles from Shopify with the protected read the
confirmation uses, applies the skips, inserts the row, queues
`INBOX_FEEDBACK_SEND`. Sender copies the confirmation's claim-before-send.

**Messages.** `MetaClient` gains interactive sends (reply buttons, up to 3;
list, up to 10). Inbound gains `list_reply`. Payloads: `fb_<answer>_<order
id>` for the template, `fbr_<reason>_<survey id>`, `fbs_<yes|no>_<survey id>`,
`fbo_<answer>_<survey id>`. A tap is accepted only from the survey's own
phone and only for the step it is on; anything else is stored as an ordinary
message.

Reasons: loved → quality, fit, design, delivery, other. okay → size_fit,
quality, delivery, packaging, price, other. unhappy → size_fit, quality,
wrong_item, delivery, other.

**Follow-up state** is derived from the survey, not stored on the chat:
*Needs follow-up* = rating unhappy, `resolved_at` null.

**Flag.** `INBOX_FEEDBACK_ENABLED` (off by default). `feedback_started_at` is
kept in a one-row `feedback_settings` table so nothing delivered before
switch-on is asked.

**As built (batch A).** The sweep and first question are
`app/modules/inbox/services/feedback.py`; taps, follow-ups, comment, resolve
and the solved question are `feedback_replies.py`. A fourth job,
`INBOX_FEEDBACK_REPLY` (one per tap, under the tap's own id), carries the
follow-up messages; `INBOX_FEEDBACK_SWEEP`, `_SEND` and `_ASK_SOLVED` are as
above. The closing words are built by `closing_text`, and her code by the one
seam `issue_code` (returns nothing until batch B). "Returns awaiting review or
a refund owed" is read through `operations.public`. A skipped row keeps no
phone, name or products. "An unhappy answer not yet resolved" means an unhappy
survey on step `support`.

An order whose customer has written something nobody on the team has answered
(in the last 72 hours, ignoring button taps and reactions; "answered" means
the latest message a member of staff sent her is newer), or who has an unhappy
answer not yet resolved, is recorded `waiting` with no customer detail and
looked at again every 6 hours by the sweep. Past 7 days from delivery it
becomes `skipped` (`waited_too_long`). A `pending` question whose send job
ended without sending is queued again by the sweep after 30 minutes. "Asked in
the last 60 days" counts questions sent or on their way, not ones only
recorded or never delivered. The solved question is claimed before it is
sent; if it cannot be sent (or may not have been) the survey returns to step
`support` with the reason in `last_error`, so a person sees her.

**As built (batch B).** All in `app/modules/inbox/services/feedback_codes.py`;
`feedback_replies.issue_code` is now a thin call into it. The migration
(`c3e9a5b70030`, still undeployed, edited in place) gained
`feedback_settings.discount_gid`, `feedback_survey.code_gid`,
`code_removed_at`, a unique `code` and a partial index on the codes still out.

- *One discount.* `ensure_discount` checks the stored id still exists in
  Shopify (`discountNode`), otherwise makes *Feedback 20%* with
  `discountCodeBasicCreate`: 20%, whole order, `context: {all: ALL}` (the
  current form of the deprecated `customerSelection`), `usageLimit: 1`,
  `appliesOncePerCustomer`, starts now, no end, one unguessable first code
  that is never given to anyone (Shopify requires one). A Postgres advisory
  lock makes two racing jobs take turns; the id is committed in a session of
  its own the moment Shopify has made the discount.
- *A code each.* `FB-` and six of `ABCDEFGHJKMNPQRSTUVWXYZ23456789`, added with
  `discountRedeemCodeBulkAdd`; the answer (or one status read) gives the
  redeem code's id, kept as `code_gid`; a code Shopify has not finished adding
  keeps `code_gid` null and is found by its text at clean-up time. Committed in
  a session of its own, so a retried job reuses it. 30 days from issue.
  `code_sent_at` is stamped only when the closing message is sent.
- *Never blocks the thank-you.* Not connected, permission missing, Shopify
  saying no: closing goes out without a code, `last_error` says why. A
  Shopify error that may pass is raised so the reply job retries (nothing has
  been sent yet); the job's own failed-try count (read from its row) says
  when to stop - the third try thanks her without a code.
- *Used.* `mark_used`, called by the sweep: one `UPDATE ... FROM` over
  `order_index.discount_codes`, case-insensitive, orders placed at or after
  `code_sent_at`, earliest order wins.
- *Thirty days.* `INBOX_FEEDBACK_EXPIRE_CODES`, daily, inbox lane, flag-gated.
  Runs `mark_used` first, reads each code's id and use count in one `nodes`
  query, removes in batches of 100 with `discountCodeRedeemCodeBulkDelete`.
  A code Shopify no longer has counts as removed; one Shopify says was used
  is left for the orders to catch up. A used code is never removed.
- *`codes_ready(db) -> (bool, reason)`* reads the second app's granted scopes
  from the token exchange (one call to Shopify; nothing is stored) and
  needs `write_discounts`. Saving the second app is unchanged: it still needs
  only `write_orders`.

**As built (batch C1).** The HTTP side, all behind `inbox.use` in
`app/modules/inbox/api.py`; the reads are in `feedback.py`, the file in
`feedback_sheet.py` (openpyxl, one row per asked order, dates as dates in Cairo
time, customers' words stored as text so a leading `=` is never a formula).

- `GET /api/inbox/feedback`: a page of asked orders, newest question first
  (`limit` 1-200, `offset`), filters `since`/`until` (the Cairo day she was
  asked, `until` included), `rating`, `reason`, `product`, `courier`, `state`
  (`needs_follow_up`, `resolved`, `reopened`), `q` (order, customer, phone).
  Returns `rows`, `next_offset`, a `summary` for the same filters and the
  `options` for the filter menus. Skipped and waiting rows are never listed.
  A question never sent is placed by when it was recorded.
- `GET /api/inbox/feedback/download`: the same filters, every row, as an
  `.xlsx` named `feedback-<Cairo date>.xlsx`; audited as
  `inbox.feedback_downloaded` (row count and filters, never the search text).
- `POST /api/inbox/feedback/{id}/resolve`: `feedback_replies.resolve`; 404 no
  such feedback, 422 not an unhappy answer waiting for follow-up (which covers
  already resolved).
- `GET /api/inbox/feedback/settings` (`enabled`, `started_at`, `review_url`,
  `reply_hours`, `codes_ready: {ready, reason}`; the only read that asks
  Shopify) and `PUT` (admin only, `settings.manage`): `review_url` empty or
  `https://`, at most 500 characters; `reply_hours` 1-72; audited as
  `inbox.feedback_settings_saved`.
- A chat's detail carries `feedback` (her latest asked survey, or null). The
  conversation list gains two views, `follow_up` and `neutral` (her latest
  answered survey is *okay* and was given in the last 14 days), a `feedback`
  marker on each row (`reopened`, `follow_up`, `neutral` or null) and
  `counts.follow_up`.
- Today: `inbox.feedback_follow_up` (chats with an unhappy answer waiting for a
  person; late once the oldest has waited longer than the promised hours) and
  the stronger `inbox.feedback_reopened` (always late). The sidebar count key
  is `chats_follow_up`, the same number as the list's chip.

## Test send

An admin can try the whole flow on his own phone before the questions are
switched on for customers: Settings → Integrations → Feedback questions →
*Send a test to this number* (`POST /api/inbox/feedback/test`, `settings.manage`;
audited as `inbox.feedback_test_sent`, which keeps only the last four digits).

- It sends the real first question (`order_feedback`) at once, for one
  Egyptian mobile, to a survey row marked `is_test`. Its order id is a 20-digit
  number, which no Shopify order id can be, so it cannot collide with a real
  order and the buttons read it like any other.
- **It works with `INBOX_FEEDBACK_ENABLED` off.** The sweep stays off, and so
  does everything else for a customer. The jobs that carry on the flow (the
  send, the reply to each tap, the solved question and the 30-day clean-up)
  let a test survey through the switch and nothing else. WhatsApp must be
  connected and sending allowed for that number, as for any message.
- The flow is the real one, with real WhatsApp and real Shopify. A test that
  reaches the closing message gets a real code in the real discount, to try at
  checkout; the clean-up removes it after 30 days. After *Resolved* on a test
  the solved question comes after one minute instead of a day. A test is not
  tried again in the background if WhatsApp does not take it: the caller is
  told why. Sending another test closes the earlier unfinished one.
- **Tests are kept out of the numbers.** Never in the sheet, its summary, its
  filter menus or the download; never in Today, the sidebar or the
  *Needs follow-up* chip. They are in the chats: the chat's Feedback block
  carries a *Test* tag and *Resolved* works, and the *Needs follow-up* view
  and badge list them, so the owner can practise finding and resolving one.
  A test never counts as "asked in the last 60 days", never holds back a real
  question for the same phone (an unresolved unhappy answer), and is never held
  back by one.

## Owner's steps (batch D)

1. Meta: submit two templates (wording supplied): `order_feedback` and
   `feedback_resolved`, both as *Utility*.
2. Shopify: add *Write discounts* (`write_discounts`) to the second app,
   release the new app version and approve it on the store, then reconnect it
   (a token never gains a scope after it was issued). Before going on, make
   two codes in the discount and use one twice on a test order: the usage
   limit must count per code (Shopify's REST docs say so; the GraphQL docs
   only say "times the discount can be redeemed").
3. Give the review link.
4. Test on his own phone with *Send a test* (see above), then say go.

**Where these stand (told by the owner while the screens were being checked).** Both templates are approved
by Meta as *Utility*, under exactly these names. `write_discounts` is added to
the second app; whether the platform's token now holds it shows on the
Settings card (*Reward codes*) once this is deployed, and the use-one-code-
twice check is still to do. The review link is Judge.me's
(`https://judge.me/product_reviews/a34be3ff-0a3d-4e51-8343-16f813bcac58/new?source=shareable-link`):
it asks for a product review and offers a store review too. It is entered in
Settings → Integrations → Feedback questions after deploy, not in code.

## Decisions made, not to reopen

- In WhatsApp, not Google Forms. Two days after delivery. 24-hour promise.
- 20%, one code each inside one discount, 30 days, everyone who finishes;
  unhappy customers after their issue is solved.
- No email collected. No reminder for an unanswered first question.
- The code is sent right after the reason, with the invitation to comment,
  instead of after a separate comment question: one message fewer, and nobody
  misses her code by not replying.
