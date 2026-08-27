# 0030 — A reopened month emails once, on re-approval, and says why

**Status:** accepted
**Date:** 2026-08-27
**Amends:** spec §16 (Notifications, audit, and policy)
**Related:** [0029](0029-a-late-order-is-paid-at-its-own-months-rate.md)

## The question

> "We need to send [her] a mail like paying a normal month saying that his
> payment for this month is updated to what I will write."

Right, in substance. Reopening a month and re-approving it at a different
figure moves money she was not expecting, and §11.1's whole premise is that a
model should never have to ask what a number means. An unexplained transfer is
exactly the question this platform exists to prevent.

## Decision: no separate email for reopening itself

The proposal was raised as two moments — tell her when it's reopened, tell her
again when it's re-approved. Considered and rejected for one reason, given by
the business directly: **reopen and re-approve happen back to back.** A
heads-up email that lands minutes before the real one teaches her to skip the
first and, eventually, skim the second.

**One email, on re-approval.** §16's existing "Month approved" row already
covers this — a re-approval is an approval, just not the first one. No new
event type is needed. What is missing is that the email has to *know* it is a
second version and say so.

## Decision: the channel is email, because that is the only one she has

§16's table gives models exactly one channel: email. There is no in-platform
inbox for her — that belongs to the maintainer alone, and even her own
dashboard does not exist before Phase 9. So until notifications are built
(Phase 10) and her portal exists (Phase 9), a re-approval is invisible to her
exactly like every other event in that table. This ADR does not move that
timeline; it settles what the email says once it is built.

## Decision: the email states the reason, not just the new figure

*"Your August is now E£2,650"* answers what changed. It does not answer the
question she will actually have: *did you make a mistake, or did I?* Silence
on that point is what turns a correction into a support message.

The reopen action already collects a written reason (§11.5, enforced
server-side). The re-approval email for a **second or later version** must
include it, rewritten for her rather than copied from the audit log verbatim -
*"an order arrived after the month closed"*, not
`orders_released: 1`.

## Decision: a downward correction is told before any money moves, not after

The proposal assumed the figure only goes up. It does not — ADR 0029 and a
corrected rate or target can both make a re-approved month **lower** than what
was already paid. When that happens there is no transfer to attach the news
to, and by construction she will notice nothing in her bank account. Telling
her only reaches her the day her next payment is short, which is the exact
failure this ADR exists to prevent.

So a downward re-approval emails **immediately**, at approval, and says which
of the two resolutions applies (§11.5 leaves that choice to the maintainer,
never to the platform):

- **Credited**: *"E£300 will come off next month's payment."*
- **Written off**: *"Nothing further is needed from you."*

## What this settles for Phase 10

When notifications are built, the "Month approved" email template needs a
branch for `version > 1`, carrying:

1. The new figure and the difference from the previous version.
2. The written reason, in plain language.
3. For a downward correction: which resolution was chosen and what happens
   next.

No new row in §16's table. No email on reopen itself.
