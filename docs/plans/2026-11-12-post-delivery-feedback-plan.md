# Post-delivery feedback on WhatsApp: plan

Rule: ADR 0083. Branch: `claude/post-delivery-feedback-workflow-29df80`.
Approved by the owner 12 November 2026. Merge and deploy each need his
separate go-ahead.

## Batches

| # | Batch | Status |
|---|---|---|
| A | Engine: table, trigger, first question, taps, follow-up questions, resolve, solved question. Silent unless switched on. | Built on this branch; tests pass; not merged |
| B | Codes: the one Shopify discount, a code per customer, 30-day clean-up, used-or-not. Settings (review link, promised hours). | Not started |
| C | Screens: Inbox → Feedback sheet with filters and download; *Needs follow-up* and *Feedback: neutral* chips; *Resolved* button; Today counts; settings card. | Not started |
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

## Owner's steps (batch D)

1. Meta: submit two templates (wording supplied): `order_feedback` and
   `feedback_resolved`, both as *Utility*.
2. Shopify: add *manage discounts* to the second app and reconnect it.
3. Give the review link.
4. Test on his own phone, then say go.

## Decisions made, not to reopen

- In WhatsApp, not Google Forms. Two days after delivery. 24-hour promise.
- 20%, one code each inside one discount, 30 days, everyone who finishes;
  unhappy customers after their issue is solved.
- No email collected. No reminder for an unanswered first question.
- The code is sent right after the reason, with the invitation to comment,
  instead of after a separate comment question: one message fewer, and nobody
  misses her code by not replying.
