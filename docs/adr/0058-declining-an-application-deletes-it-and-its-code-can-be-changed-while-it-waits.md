# 0058. Declining an application deletes it, and its code can be changed while it waits

**Status:** Accepted
**Date:** 2026-10-03
**Amends:** 0052 (decline and reconsider), 0053 (her code does not change)

## Context

On 3 October 2026, the first day real models applied on production, Ziad
Ahmed applied with the code `ZYZZ`, which was mistyped. The owner could not
see how to correct it on the review screen, so he declined the application
(reason: *the code was written wrong*) meaning to invite Ziad again. Three things
went wrong:

- **Inviting him again was refused**: *ziadscholarships@gmail.com is already a
  model on HBA.* ADR 0052 kept a declined applicant's account and profile, and
  an invitation refuses an address that has either.
- **He stayed on the roster**: he was listed under *Inactive* on Models and had a row
  on the Targets grid, though he was never accepted.
- **The code could not be seen to be editable.** The correction box held the
  code only as greyed placeholder text, and once Shopify confirmed a code the
  box was gone, so a mistyped code that happened to exist could not be
  corrected at all.

The owner's ruling (3 October): an application that is declined is
**deleted**, not kept as an inactive model. Someone who applied and was
turned down never was a model. And a submitted application's code must be
**editable** before it is approved.

## Decision

### Declining deletes the application

Declining a pending application **erases it**, through the same routine and
the same scoped guards as *Erase* (ADR 0052). The routine removes her
sign-in account, profile, code, pay terms, targets, payment details, the
invitations sent to her address, queued notices and the audit entries about
her. One audit entry survives, `affiliate.declined_and_erased`, recording
that application #id was declined, by whom, when and the reason given. It
carries none of her details.

Afterwards nothing of her is left. She is on no list and no grid. Her code is
free for anyone, and **the same address can be invited again** at once.

A reason is still required. Declining is open to the same people as
before (`affiliates.manage`), not only an admin: an applicant who was never
accepted has no history the business needs to keep.

**The one exception.** If something about money or goods already touches the
application (an order attributed to her, a payroll month, a payment, an
adjustment, a parcel or a proof file), or her account also holds a staff role,
it cannot be erased. It is declined as before: kept as `declined`, her code
released or closed, *Reconsider* available. A declined applicant who is
kept is **not on the Targets grid**, and inviting her address says her
application was declined and to reconsider it from her profile, rather than
calling her a model. In practice this means only an applicant with orders
already counted to her.

### Her code can be changed while her application waits

While an application is **pending and no order has been counted to it**,
staff may change its code, **whether or not Shopify has confirmed it**. The
code is then checked against Shopify straight away, as before. The row is
rewritten, not closed and replaced: nothing has been attributed to it, so
there is no history to keep, and leaving the wrong code would keep it held.

If her start month is the replaced code's start, it was taken from that
code, so it is taken from the new one instead (or left unknown until the new
one is found on Shopify). A different start month, which somebody typed, is
left alone.

Once she is approved, or as soon as any order is counted to her, her code
does not change (ADR 0053 unchanged).

On the profile, under *Setup before approval*, the code is shown **in an
editable box with its value filled in**, and the button reads *Save and
check* once it has been changed. A confirmed code on a pending application
has a *Change* button that opens the same box. This step was not drawn in
an approved export beyond the box itself; the change is this ADR's.

## Consequences

- **A declined application cannot be reconsidered.** It is gone, and the
  way back is a new invitation. The owner chose that over *Reconsider*,
  which ADR 0052 picked on 30 September because a re-invite was refused.
  *Reconsider* remains only for the kept exception.
- **The decline reason is the only record.** Who she was, what code she
  typed and where she wanted to be paid are deleted with her. A question
  about her later has only the surviving audit entry.
- Erasing deletes audit rows. Until now only an admin could make that happen,
  through *Erase*. Declining now makes it available to everyone who manages
  models, but only for applications with nothing about money or goods on
  them.
- What she sees after being declined: she no longer has an account, so she
  cannot sign in to read *not accepted this time*. Nothing is emailed, as
  before.
- A verified code on a pending application can now be rewritten. That is safe
  only while nothing is attributed to it, and the server checks that first.

## Alternatives considered

- **Keep decline as it was and let an invitation revive a declined account.**
  He would still have been on the roster and the Targets grid in the
  meantime, and a *declined* row for a person who was never a model is what
  the owner objected to.
- **Delete on decline but keep her details in the audit entry.** It would
  keep the personal data of someone the business turned down, which is
  what a true delete exists to avoid (ADR 0052 chose a true delete for the
  same reason).
- **Leave code correction for unconfirmed codes only.** A mistyped code that
  happens to exist on Shopify (another live code, for example) would then
  have no fix but declining, which is what happened here.
