# 0007. Permissions are defined in code, assigned in data

**Status:** Accepted
**Date:** 2026-08-22

## Context

The business asked whether roles should be composable through the interface -
tick twelve permissions per person at invitation time - so that a new role needs
no developer.

Dynamic permission builders are among the most reliably over-engineered features
in internal software. They are complex to build, hard to test, easy to
misconfigure into a security hole, and difficult to reason about afterwards:
"why can this person see payouts?" becomes an archaeology exercise.

## Decision

Permissions are constants in code. Roles are named bundles of them, also in
code. Assigning a person to a role happens in the application and needs no
deploy.

Adding or changing a *role* is a code change, which means it is
version-controlled, reviewed, and covered by tests.

Every check is enforced server-side. Hiding a control in the interface is
presentation, never protection.

## Consequences

A genuinely new role requires a developer and a deploy. At this organisation's
size that is minutes of work a handful of times a year, and it buys three
things: a role's safety is tested once and stays tested; "who can approve
payroll?" is a single lookup rather than a scan of every account; and granting
five people the same access is one action rather than sixty checkboxes.

`frozenset` is used throughout, so a caller cannot mutate a returned set to
grant itself a permission at runtime.

An unknown permission name raises rather than returning `False`, so a typo fails
loudly in development instead of silently denying access in production and
looking like a permissions bug.

## Alternatives considered

**Per-person permission checkboxes.** Rejected for the reasons above. The
flexibility would be exercised perhaps twice a year; the auditability it removes
is needed constantly.
