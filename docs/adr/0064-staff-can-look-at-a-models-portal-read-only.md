# 0064. Staff can look at a model's portal, read only

**Status:** Accepted
**Date:** 2026-10-18
**Builds on:** ADR 0006 and §6.1 (a model reaches her data by owning it, never by a permission)

## Context

On 18 October 2026 the owner asked to see what the ambassadors see, *"so that
I notice things that they might miss or at least see the dashboard from their
eyes"*.

Nothing let him. Every portal screen reads `/api/me/...`, gated on
`current_affiliate`: the signed-in account must **own** the profile. That gate
is deliberate (`app/api/deps.py`): a route that accepted either a model or a
permission would let a maintainer act *as* a model, and the audit trail could
not then tell her actions from somebody else's. The admin profile shows the
same facts, but in the admin's layout and words, which is not what he asked to
see. The only ways to see her real screen were signing in with her password or
looking at the staging test model, whose numbers are not hers.

## Decision

On a model's profile, **View her portal** opens her portal as she sees it, with
her real figures, **read only**.

- **Her screens, not a copy.** The preview renders the same portal components
  she uses. Their reads go to `/api/affiliates/{id}/portal/...`, which answer
  by calling the same handlers as `/api/me/...` for the profile named in the
  path. One implementation, so the preview cannot drift from what she sees.
- **A second gate, never a merged one.** The preview routes require
  `affiliates.view` (whoever may already open her profile) and are separate
  from `current_affiliate`, which is unchanged. Nothing under `/api/me` accepts
  a permission, so this does not let anybody act as her.
- **Reads only.** The preview router has no write route, and a test fails if
  one is added. In the browser, the preview refuses every write before it is
  sent, and the controls that would change something (her address, sizes,
  payout details, notification switches, Sign out) are hidden or disabled.
- **Her payout details stay shortened.** The preview does not offer *Show them
  in full*; it has no route for the unmasked read. Staff who need the full
  details already have the audited reveal on the payments side.
- **Audited.** Opening the preview records `portal.previewed` against her
  (*"Looked at Nour's portal (read only)"*), under the staff member who looked.
  It is never recorded as her.
- **Phone-sized by default.** Most models use a phone, so the preview opens in
  a phone-width frame, with a switch to full width. The frame is a real
  viewport, so her phone layout is what renders, not a squeezed desktop.

## Consequences

- A second address for each of her reads. A test ties them together: every
  read the portal makes under `/api/me` must have its preview counterpart,
  apart from the unmasked payout read, so a new portal screen fails the suite
  until the preview can show it too.
- Anybody with `affiliates.view` can see her ranking row and her transfer
  screenshots in the portal layout. They could already see both on the admin
  side (`/api/payments/{id}/proof` has required `affiliates.view` since
  Phase 7), so this exposes nothing new to anyone.
- The preview's own navigation is not in the browser's address bar (it runs
  inside the frame), so reloading returns to her Home. That is acceptable for
  a look and not worth an addressing scheme of its own.
- What she sees and what the preview sees can differ in one way: the theme.
  Hers is stored on her device and the preview uses the viewer's.

## Alternatives considered

**Sign in as her (impersonation).** It shows exactly what she sees, but every
click would be recorded as her, it needs a session minted for somebody else,
and a wrong press would change her real record. ADR 0006's gate exists to
prevent exactly this.

**Let `current_affiliate` accept staff with a permission.** One line, and it
merges the two gates the codebase keeps apart on purpose. Every write under
`/api/me` would then be callable by staff as her.

**A separate "model's view" screen in admin.** Easy to build and wrong for the
request: a re-drawn version would drift from her real screens, and drift is
exactly what he wants to catch.
