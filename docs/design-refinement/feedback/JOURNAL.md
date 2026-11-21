# Feedback refinement journal

**Started:** 2026-11-21 · **Branch:** `claude/feedbacks-ui-support-workflow-dc4b2f` from `main` at `8904e2d`
**Scope:** Inbox → Feedback (`/inbox/feedback`), the Feedback block beside a chat, the follow-up pop-ups, the Feedback setup message list, the download.
**Not in scope:** Today's items and the sidebar count. They read the same "open follow-up" rule and only lose *Couldn't reach* follow-ups.
**Design and rules:** `docs/superpowers/specs/2026-11-21-feedback-follow-up-design.md`, ADR 0087.

---

## 1. What the owner asked (21 Nov 2026)

1. The Feedback screen is not tidy. Apply design thinking to what is shown, where, and how.
2. Support should record what they did with each customer who needs a follow-up, in a comment box that opens on *Resolved*.
3. Some customers don't answer the phone. Show that, and match what really happened with what is recorded.

## 2. Skills used

| Skill | Why | What it contributed |
|---|---|---|
| superpowers:brainstorming | A new workflow, not only a restyle | Found that *Resolved* sends "Was your issue solved?" the next day, so it can't double as "I tried". This led to the separate *No answer* action. |
| Visual companion (mockup) | The look was the owner's to decide | Approved mockup: summary, *To follow up* list, sheet, pop-ups, chat panel. |
| screen-refinement | The house standard for screens | One journal, a phone and theme sweep, nothing written to staging. |

## 3. Findings on the old screen

| ID | What | Decision |
|---|---|---|
| F1 | Two jobs on one sheet: support working a queue, the owner reading trends | The people waiting for a call come first, in their own list that ignores filters. The sheet below is for reading. |
| F2 | 9 summary tiles, several of them derived (Answered, Solved, Codes sent) | 4 cards: answered of asked, one bar for how they felt, to follow up (with past-promise count), codes used of sent. |
| F3 | 10 columns: Products, Courier and Reason each had their own | 7 columns. Products and courier sit under the order, the reason under the answer. |
| F4 | 8 filters always visible | Answer as one-tap buttons (adds *No answer yet*), dates, follow-up and one search box that also matches products. Courier and reason go behind *More filters*. |
| F5 | *Resolved* was the only record, and it sends a question to the customer | *Resolved* needs a note. *No answer* and *Add note* send nothing. Every action is kept in an append-only history. |
| F6 | Nothing for a customer who never picks up | The 2nd unanswered call sends a WhatsApp message by itself (chat message if her 24 h are open, else template `feedback_tried_to_call`). From the 3rd call, support can close it as *Couldn't reach*. |
| F7 | On a phone the 4 cards stacked into a tall column above the list of people to call | 2 a row: Answered and To follow up side by side, the bar and codes across. |

## 4. Verification

- **Backend:** the full suite runs on a private disposable database (`hba_feedback_test`), because another session shares `hba_platform_test`. Every feedback, chat, worker and migration file passes.
- **Frontend:** `npm test` (1,987 tests) and `npm run build` both pass.
- **Browser:** checked locally (`seed_inbox.py` + `seed_feedback.py` on `hba_browser_feedback`, no WhatsApp keys) at 1280 and 390 px, dark theme.
  - Saving *No answer* from the list added it to the history straight away.
  - *Resolve* from a chat with the required note worked.
  - No sideways scroll at 390 px.
- **Review:** a whole-branch review found three issues, all fixed:
  - the message could be sent twice after a crash, now prevented with a committed claim and a recovery sweep;
  - running out of retries left no trace, now recorded as `message_failed`;
  - pop-ups promised messages the server would not send, now worded from the server's own state.
- **Not verified:** staging. Also not checked: the real Meta template, which is not yet submitted, and the light theme in the real app (only in the builder's preview).

## 5. Lessons

1. A shared test database collided with another session's run; the full-suite script empties the database it is given. Use a private disposable database whenever another session might be testing.
2. "Resolved" was carrying two meanings: "I reached her" and "ask her tomorrow". Splitting the actions was the real fix. The tidier screen follows from that.

## 6. Open items

- Owner: submit `feedback_tried_to_call` to Meta (utility, English, one variable: the order name).
- Staging check after merge and deploy, when authorised.
