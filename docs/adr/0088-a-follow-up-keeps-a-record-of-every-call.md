# 0088. A follow-up keeps a record of every call

**Status:** Accepted, being built
**Date:** 2026-11-21

Amends ADR 0083, decisions 4 (*Unhappy chats are followed up by a person*)
and 6 (*Every answer is a row*).

## Context

Under ADR 0083 the only thing customer service could record on an unhappy
answer was *Resolved*, and pressing it has a side effect: the next day she is
asked *Was your issue solved?*. Some customers do not answer the phone. A
support person who could not reach her had two bad choices: press *Resolved*,
and she is asked about a fix nobody gave her; or press nothing, and the
platform shows no trace of the calls.

The owner, 21 November 2026: support should write down what they did on every
follow-up, in a box that opens when they press *Resolved*; a customer who does
not answer should show as such; and what the platform records should match
what really happened.

## Decision

A follow-up is **open** while the answer is *Not happy* and the survey waits
for a person (step `support`). While it is open a person can do one of three
things, and each adds a line to its history:

| Action | Note | What happens |
|---|---|---|
| **Resolved** | required, 1–1,000 characters | As before: *Was your issue solved?* goes the next day (or the follow-up closes, after the second reopen). |
| **No answer** | optional, up to 1,000 | It stays open and nothing is sent. On the 2nd no-answer of a round the platform messages her on WhatsApp. From the 3rd it can be closed as *Couldn't reach*. |
| **Add note** | required, 1–1,000 | It stays open and nothing is sent ("spoke to her, waiting on finance"). |

1. **The history is a record.** One row per action in `feedback_follow_up`:
   the survey, the round, what it was, the note, who and when (nobody, for
   what the platform did itself). Nothing edits or deletes a row; a mistake is
   corrected by a new note. Every action is also audited.
2. **Rounds.** A round starts when she answers *Not happy* (round 0), when
   she says *No, not solved*, and when she writes back after *Couldn't
   reach*. The survey keeps its own counter (`follow_up_round`) and when the
   round started (`round_started_at`); `reopened_count` keeps its one meaning
   (she said *No*) and its limit on *Resolved*. The no-answer count and the
   WhatsApp message are per round, so a second round can send the message
   once more.
3. **The waiting clock** runs from the start of the round. Calls and notes do
   not restart it: the promise is to reach her, not to try.
4. **The WhatsApp message** goes once per round, queued when the 2nd
   no-answer is saved. Whether her 24 hours are open is checked when it is
   sent:
   - open: a chat message, *"We tried to call you about your order {order}.
     Reply here or tell us a good time to call."*, whose words the owner can
     edit in Feedback setup like the other messages;
   - closed: the approved template `feedback_tried_to_call` (English, one
     body variable, the order name), which the owner submits to Meta.

   It names the order and offers nothing, so Meta counts it as *utility*.
   Everything in ADR 0059's sending rules and `INBOX_FEEDBACK_ENABLED`
   applies. If it cannot be sent, including while the template is not yet
   approved, the history says *Couldn't send the WhatsApp message: … Write to
   her yourself.* It is not retried on its own.

   It is claimed for the round (`tried_claimed_round`, `tried_claimed_at`)
   in a committed transaction of its own before WhatsApp is asked, as the
   solved question is, so a crash after WhatsApp took it never sends it
   twice; no row lock is held while WhatsApp is asked. WhatsApp not answering
   gives the claim back and the job tries again; on its last try the history
   says it could not be sent. A claim with nothing in the chat ten minutes
   later gets the line *Interrupted while sending … it may have gone out.
   Check the chat in WhatsApp before writing to her.*
5. **Couldn't reach** closes the follow-up (step `done`, with who and when).
   She leaves *To follow up*, Today and the sidebar count. She is not asked
   whether her issue was solved and gets no code.
6. **She writes back.** A message she types (a button tap does not count)
   within 14 days of *Couldn't reach* opens the follow-up again, on the most
   recent such survey for her phone: back to step `support`, the close
   cleared from the survey (the history keeps it), a *She wrote back* line,
   and a new round. Nothing is sent to her; the chat is already unread.
7. **When *Was your issue solved?* cannot be sent**, the follow-up returns to
   a person in the same round, and the history says why. The no-answer count
   carries on.
8. **Follow-ups resolved before this** get one *Resolved* line from the
   migration (no note, at the time and by the person recorded), so no
   history is blank. Open ones start with none.

Who can act: everyone who can press *Resolved* today (Inbox holders). Test
surveys follow the same rules and are still never counted.

## Consequences

- A support person can no longer press *Resolved* without saying what was
  agreed. That is the point, and it costs a few seconds per follow-up.
- One more template for the owner to get approved by Meta. Until it is, a
  customer whose 24 hours have closed is not messaged after the 2nd call, and
  the history tells the team to write to her themselves.
- The history grows without bound (a row per call or note). It is small: a
  handful of rows per unhappy answer.
- Reopening on her own message means one more step in the path of every
  typed message (one indexed lookup by phone).

## Alternatives considered

- **Counters and a "last note" column on the survey.** Smaller, but each new
  note erases the last: exactly the gap between what happened and what is
  recorded that the owner wants closed.
- **Reuse the chat's internal notes.** They are not tied to the order or the
  round, so the sheet and the download cannot count calls.
- **Reuse `reopened_count` as the round.** It would make *Couldn't reach*
  and her writing back count towards the limit on *Resolved*, which is about
  her saying *No*.
