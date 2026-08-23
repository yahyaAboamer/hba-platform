# 0006. Identity is rooted in user_account, not affiliate

**Status:** Accepted
**Date:** 2026-08-22

## Context

The platform's governing principle is to build a generic spine and one module.
The first draft of the data model contradicted that: identity was rooted in the
affiliate record, with staff treated as a special case.

An external review caught it. The consequence would have surfaced in V2, when
Hussam's production team and Amr's operations team arrive and discover that the
"generic" identity system is shaped around affiliate creators - at which point
every later module works around it, or a migration touches every table.

## Decision

Identity lives in `user_account`, which knows nothing about any business role.
`role_assignment`, `auth_session` and `invitation` hang off it.

An affiliate is a `user_account` with an `affiliate_profile`. Staff are
`user_account` records without one. Later modules attach their own profiles the
same way.

## Consequences

One extra table and one extra join to reach an affiliate's business data. That
is the entire cost.

A structural test queries `information_schema` and fails if an `affiliate` table
ever becomes the identity root, so the decision cannot quietly erode.

## Alternatives considered

**Affiliate as the root, staff as a special case.** Simpler on the single day
when the affiliate module is the only module, and wrong on every day after it.
