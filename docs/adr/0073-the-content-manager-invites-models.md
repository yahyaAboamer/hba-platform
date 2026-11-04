# 0073. The content manager invites models

**Status:** Accepted
**Date:** 2026-11-04

## Context

Inviting a model (Affiliates → Models → Invite, and the resend, withdraw and
"finish your application" reminder beside it) needs `invitations.send`.
Until now only the admin and the affiliate manager held it. The content
manager already sees and edits every model, sets her pay terms and runs her
targets, but could not bring a new model in: the Invite page showed her the
list and the line "for an administrator or affiliate manager".

`invitations.send` was withheld from the content manager when one permission
covered **staff** invitations too, and an invitation is a grant of access.
Batch 2.3 (3–4 November 2026) moved staff invitations, their resend and their
withdrawal to `settings.manage` (`invitation_permission`), so
`invitations.send` now reaches models only. A model's role grants nothing.

The owner asked for it on 4 November 2026.

## Decision

1. The `content_manager` role holds `invitations.send`. She may invite a
   model, resend or withdraw a model's invitation, and remind somebody who
   made her account to apply — exactly what the affiliate manager may do.
2. Staff invitations are unchanged: only `settings.manage` (the owner) sends,
   resends or withdraws them. The content manager still grants no staff
   access.
3. Nobody's assignment changes; the role itself gains the permission, so
   every current content manager has it at once. No migration.

## Consequences

- Two people can now start a model's onboarding; both are in the activity
  log (model invitations count as Affiliates', which she reads).
- The content manager now sets the terms and verifies the targets of models
  she may also have invited. Approving payroll and recording payments stay
  elsewhere, so the money is still settled by somebody else.
- Should staff invitations ever go back to `invitations.send`, this role
  would gain the power to invite staff; `invitation_permission` and the
  tests in `test_permissions.py` and `test_staff_api.py` are what stop that
  happening silently.

## Alternatives considered

- **A separate `models.invite` permission.** Cleaner names, but
  `invitations.send` already means exactly that since Batch 2.3, and a rename
  touches every route, test and the frontend for no change in behaviour.
- **Give it per person (an extra role).** No role grants only invitations,
  and every content manager does the same job, so the role is the right
  place.
