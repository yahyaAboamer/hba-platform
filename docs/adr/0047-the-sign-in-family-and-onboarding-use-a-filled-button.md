# 0047 — Sign-in and onboarding: portal look, and a filled button

**Status:** accepted — a recorded divergence from the approved export
**Date:** 2026-09-26
**Related:** `frontend/src/screens/SignIn.css` (`.auth`);
`frontend/src/components/AuthShell.tsx`; `frontend/src/screens/Apply.tsx`;
`frontend/src/screens/ApplicationPending.tsx`; `styles/base.css`
(`.button--primary`, "There is no filled button in the approved design")

## The situation

The approved exports draw no sign-in, invitation, password or application
screen. Ours were the maintainer's light, laptop-first form, so a model
arriving from her email met a page that looked like neither the admin nor her
own portal. The owner, 26 September, after walking it on a phone:

> It doesn't match the style of the dashboard. So it needs to match the
> model's style.

He was shown a mockup and chose, for these screens:

- **the portal's look for everyone** - the sign-in page is shared by staff
  and models, and he chose one look rather than two;
- **a filled green button with dark text.** White on the portal green is
  about 3:1, under the 4.5:1 a 16px label needs; dark text on it is about 7:1.

## Decision

- Every screen in the sign-in family (`SignIn`, `AcceptInvitation`,
  `ResetPassword`, `FirstRun`) and the model's application and waiting
  screens render inside `.auth` / the portal root with the device's portal
  theme (`storedTheme("portal")`, dark unless she chose light).
- **Inside `.auth` only**, `.button--primary` is filled: `--accent` ground,
  `--paper` text. Everywhere else the export's rule stands - the strongest
  action is an accent hairline and tint, and `base.css` still says so.

## What it costs

A second primary-button style exists, scoped. It is a divergence the owner
chose, written down so nobody finds it and "fixes" it back to the export -
and so nobody reads it as licence to fill buttons elsewhere.
