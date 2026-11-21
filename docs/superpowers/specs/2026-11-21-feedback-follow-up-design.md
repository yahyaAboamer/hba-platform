# Feedback: a tidier screen and a real follow-up record

**Date:** 2026-11-21
**Branch:** `claude/feedbacks-ui-support-workflow-dc4b2f`
**Builds on:** ADR 0083 (a delivered order is asked how it went on WhatsApp).
**Approved mockup:** shown to the owner on 21 Nov in the browser companion
(`feedback-layout.html`). Its three parts are described below. No approved
export from the designer covers this screen.

## Why

The owner, 21 Nov 2026:

1. The Feedback screen is not tidy. Apply design thinking to what is shown,
   where, and how.
2. Customer service should record what they did on every chat that needs a
   follow-up after they contacted the customer: a comment box that opens when
   they press *Resolved*.
3. Some customers do not answer the phone. The platform should show that and
   match what really happened with what is recorded.

Today *Resolved* is the only thing support can record. It has a side effect:
the next day the customer is asked *Was your issue solved?* So a support
person who could not reach her has two bad choices. They can press
*Resolved*, and she gets asked about a fix nobody gave her. Or they can press
nothing, and the platform shows no trace of the calls.

## Goals

- Every follow-up has a history: each call with no answer, each note, the
  resolution and what was agreed, who did it and when.
- *Resolved* needs a note.
- A call with no answer is one button. It keeps her in the follow-up list
  and sends her nothing.
- After the **2nd** unanswered call the platform messages her on WhatsApp by
  itself. If her 24 hours are open it sends a chat message. If not, it sends
  a new approved template.
- From the **3rd** unanswered call, support can close the follow-up as
  *Couldn't reach*. She is never asked *Was your issue solved?* If she writes
  later, the follow-up opens again.
- The Feedback screen puts the people waiting for a call first and makes the
  whole sheet lighter.

## Non-goals

- No dialling or call recording. The platform does not know a call happened
  until a person says so.
- No change to who is asked, when, what the first question says, or reward
  codes.
- No change to Today's two follow-up items or the sidebar count, beyond what
  *Couldn't reach* removes from them.

## Anti-goals (a failure even if it works)

- Pressing a button sends the customer something the support person did not
  expect. Every pop-up says what she will receive and when, before saving.
- The history can be edited or deleted afterwards. It is a record. Nobody
  edits or deletes an entry, and a mistake is corrected by a new note.
- A support person cannot finish the job from a phone.

## The rules (become ADR 0087, amending ADR 0083 decisions 4 and 6)

A follow-up is **open** while the answer is *Not happy* and the survey's step
is `support` (today's *Needs follow-up*). While it is open, a person can do
any of three things. Each one adds an entry to its history.

| Action | Note | What happens |
|---|---|---|
| **Resolved** | required, 1–1,000 characters | Same as today: step moves on and *Was your issue solved?* goes the next day (or the follow-up closes, after the second reopen). |
| **No answer** | optional, up to 1,000 | The follow-up stays open. On the 2nd no-answer in this round, the platform's WhatsApp message is queued. From the 3rd, the pop-up offers *Close as Couldn't reach*. |
| **Add note** | required, 1–1,000 | The follow-up stays open and nothing is sent. This is for "spoke to her, waiting on finance". |

- **Rounds.** A follow-up that comes back after she says *No, not solved*
  starts a new round. No-answer counts and the "message already sent" mark
  are per round, so a second round can send the message once more. The
  history shows both rounds.
- **The WhatsApp message** goes once per round. It names the order and offers
  nothing, so Meta counts it as *utility*. Default wording:
  *"We tried to call you about your order {order}. Reply here or tell us a
  good time to call."*
  - If her 24 hours are open, it is sent as a chat message, and its wording
    is the owner's to edit in Feedback setup, like the other messages.
  - If they are closed, it is sent as the approved template
    `feedback_tried_to_call` (English, one body variable: the order name).
    The owner submits this to Meta.
  - Everything in ADR 0059's sending rules and `INBOX_FEEDBACK_ENABLED`
    applies. While sending is off, the platform records what it would have
    sent and sends nothing.
  - If sending fails, including while the template is not approved yet, the
    history says *Couldn't send the WhatsApp message: … Write to her
    yourself.* It is not retried automatically.
- **Couldn't reach** closes the follow-up. She leaves *To follow up*, Today
  and the sidebar count. She is not asked whether her issue was solved and
  gets no code.
  - If she writes in her chat within **14 days** of the close, the follow-up
    opens again (a new round), and the history shows *She wrote back*.
  - Tapping a button doesn't count; only a message she types does, the same
    as ADR 0083's rule for waiting.
- **Who can do it:** everyone who can press *Resolved* today (Inbox holders).
- **Audit:** every action writes an audit entry, as `resolve` does today.
- **Test surveys** follow the same rules and are still never counted.

## What the screen shows (approved mockup)

### 1. The Feedback screen (`/inbox/feedback`)

**A. Summary: 4 cards instead of 9.**
- *Answered*: answered of asked, the percentage, and "N couldn't be reached"
  (not-reached sends).
- *How they felt*: one bar split into Loved it / It was okay / Not happy,
  with counts.
- *To follow up*: the open count, in the "owed" tone, plus "N past the
  24-hour promise". Pressing it scrolls to the list.
- *Reward codes used*: used of sent, plus "Problems solved: X of Y asked".

The cards follow the date filter, as today.

**B. To follow up.** This list only appears when at least one follow-up is
open. It always shows **every** open follow-up and ignores the sheet's
filters, because nobody waiting may fall outside a filter. Whoever has
waited longest comes first. Each card shows:
- name, phone and order;
- the waiting clock against the promised hours (`reply_hours`), turning red
  once past;
- the answer, reason and her words;
- the history (latest 3, with "show all");
- *Resolved…*, *No answer*, *Add note* and *Open chat*. The mockup showed
  *Add note* only beside the chat; the list has it as well.

**C. All answers.** 7 columns: *Asked · Customer (name / phone) · Order
(products · courier) · Answer (reason) · What she said · Follow-up · Reward
code*.
- The Follow-up cell shows a status chip: *To follow up*, *Resolved*,
  *Couldn't reach* or *Reopened*. Under it goes one line: the latest history
  entry, or "N calls, no answer".
- Filters on the surface: the date range, Answer as a segmented control (All
  / Loved it / It was okay / Not happy / No answer yet), the Follow-up menu
  (adds *Couldn't reach*), and one search box for order, name, phone or
  product. *More filters* holds courier and reason.
- All filters stay in the address, as today.

On a phone, B's cards stack, and C stays the existing card list with the
same content.

### 2. The pop-ups

- **Resolve #order.** Who and why, the required note ("What did you agree
  with her?"), and a line saying what she will get tomorrow. Buttons: *Save
  and resolve* and *Cancel*.
- **No answer: #order.** "This is call N". Optional note.
  - From the 2nd call, it says the WhatsApp message will go and quotes it.
    On the 2nd call itself it says the message goes after this call; on later
    calls it says it already went.
  - From the 3rd call, a checkbox *Close as Couldn't reach*, unticked by
    default, explains what closing means.
- **Add note: #order.** A required note.

Every pop-up keeps what was typed if saving fails, and shows the server's
reason.

### 3. Beside the chat (`ChatFeedbackBlock`)

The block shows the history and the same three buttons and pop-ups. The
waiting clock is added. Everything it shows today stays.

### Download

The spreadsheet gains three columns: *Calls with no answer*, *Last follow-up
note*, and *Closed as couldn't reach* (date and who).

## Approaches considered (owner delegated the how; my pick)

1. **A history table, one row per action (chosen):** `feedback_follow_up`
   holds survey, round, kind, note, who and when. It keeps every call and
   note, can't be edited, and the sheet, chat, download and audit all read
   from one place.
2. **Counters and a "last note" column on the survey.** Smaller, but each new
   note erases the last. That is the gap between real life and the record
   the owner wants closed.
3. **Reuse the chat's internal notes.** These aren't tied to the order or
   the round, so the sheet and download can't count calls.

## Build outline (for the plan)

- **Model and migration.** A new table `feedback_follow_up`:
  - `id`, `survey_id` (FK, cascade), `round` (= the survey's
    `reopened_count` at the time), `kind` (`no_answer`, `note`, `resolved`,
    `unreached`, `message_sent`, `message_failed`, `wrote_back`, `returned`),
    `note` (text, nullable), `actor_id` (nullable, null for the platform),
    `at`.
  - Indexed on `(survey_id, at)`. Append-only.
  - The survey gains `unreached_at` and `unreached_by`.
  - *Couldn't reach* sets step `done`. The sheet's state *Couldn't reach* is
    `unreached_at IS NOT NULL AND step = 'done'`.
- **Services** (`feedback_replies` or a new `feedback_follow_up` module):
  - `resolve(note)`, `no_answer(note, close)` and `add_note(note)`. Each
    locks the survey row, checks that the follow-up is open, writes the
    entry and the audit entry, and on the 2nd no-answer queues the job.
  - A new job kind `INBOX_FEEDBACK_TRIED_TO_CALL`. It follows the
    `ask_solved` pattern (window check, chat message or template, claim and
    release, recovery after an interruption), deduplicated per survey and
    round. The claim is `tried_claimed_round` / `tried_claimed_at` on the
    survey; the recovery writes a `message_failed` line saying it may have
    gone out. The last retry writes `message_failed` instead of raising.
  - In the inbound-message path, reopen a recently unreached survey.
- **API.**
  - `POST /feedback/{id}/resolve` now takes `{note}`.
  - New: `POST /feedback/{id}/no-answer` `{note?, close?}` and
    `POST /feedback/{id}/note` `{note}`.
  - New: `GET /feedback/follow-up`, the open list with each history.
  - `describe()` gains `history`, `no_answer_count`, `message_sent`,
    `unreached_at` and `waiting_since`.
  - `summary()` gains `overdue`, `solved_asked` and `unreached`.
  - The sheet filter gains `state=unreached` and `rating=none`.
  - The wording key `tried_to_call` is added to `feedback_messages`.
- **Frontend.**
  - `InboxFeedback.tsx`, split into the summary, the follow-up list and the
    sheet.
  - A shared `FollowUpDialog` and history component, used by the list and
    by `ChatFeedbackBlock`.
  - Feedback setup lists the new message.
- **Docs.** ADR 0087, `docs/RULES.md` (Inbox feedback section), and the
  journal at `docs/design-refinement/feedback/JOURNAL.md`.

## Settled after the builder check (my calls)

- **Rounds have their own counter.** The survey gains `follow_up_round` (starts at 0) and
  `round_started_at`. `reopened_count` keeps its one meaning ("she said *No, not solved*")
  and its limit on *Resolved*. A round starts when she answers *Not happy* (round 0, from
  `rated_at`), when she says *No* (the existing reopen), or when she writes back after
  *Couldn't reach*. History rows, the no-answer count and the message dedupe key
  (`survey:round`) are all per `follow_up_round`.
- **Reopening after *Couldn't reach*:** step goes back to `support`, `unreached_at`/`_by` are
  cleared (the history keeps the close), a `wrote_back` entry is added, a new round starts.
  The chip shows *To follow up*. `reopened_count` is not touched. The sheet's *Reopened*
  state keeps today's meaning (`reopened_count > 0`).
- **Which message reopens:** any message she types (not a button tap) within 14 days of the
  close, on the most recent unreached survey for that phone. Nothing is sent to her; it shows
  in the history, and the chat is already unread.
- **The waiting clock** runs from `round_started_at`. Calls and notes do not restart it: the
  promise is to reach her, not to try.
- **Surveys already resolved before this ships** get one `resolved` history entry (no note,
  at `resolved_at`, by `resolved_by`) from the migration, so no history is blank. Open ones
  start with none. `/resolve` is called only by this frontend, so requiring a note breaks
  nothing else.
- **When *Was your issue solved?* cannot be sent** (`back_to_support`), the survey returns to
  the same round and a platform entry `returned` says why. The no-answer count carries on.
- **The tried-to-call message** is queued to run at once when the 2nd no-answer is saved.
  Whether her 24 hours are open is checked at send time, not at queue time.
- **Phone:** the whole flow works at 390 px, including the follow-up list, every pop-up and
  the chat block.

## Left to the builder

- Exact component split and CSS; reuse the Inbox / Operations pieces and
  tokens.
- Wording of empty states and errors, in the platform's plain style.
- Whether the follow-up list reloads after an action by re-reading it or by
  patching it locally. The server's answer wins.

## Owner's tasks

- Submit the template `feedback_tried_to_call` to Meta (utility, English,
  one variable: the order name) with the wording above or his own.

## My calls (the owner may change any)

- The WhatsApp message goes after the 2nd unanswered call. *Couldn't reach*
  is offered from the 3rd.
- A note is required for *Resolved* and *Add note*, and optional for *No
  answer*.
- A *Couldn't reach* follow-up reopens if she writes within 14 days.
- The follow-up list ignores the sheet's filters.
- Failed WhatsApp sends are not retried; support is told to write by hand.
