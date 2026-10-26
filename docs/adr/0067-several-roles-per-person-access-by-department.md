# 0067. Several roles per person, and access set per department

**Status:** Accepted — owner, 25 October 2026, with the approved mockup `docs/design/hba-os-shell-2026-10-25.html` (frame 5). **Decisions 1–3 and 7–9 built** (Phase 1, batch 1.2, migration `c3e7a1f90019`); **decisions 4–6 built** (batch 1.3, migration `d5a2c8e40020`), with the requirement behind `TWO_STEP_ENFORCED`, off until the owner switches it on. Accepting an operations-manager invitation gives both of his assignments, so no one's access changed.
**Date:** 2026-10-25
**Builds on:** ADR 0007 (permissions in code), ADR 0006 (identity rooted in user_account). **Amends:** ADR 0057 and ADR 0059 in how the operations manager's access is made up, not in what it is.

## Context

Every staff check asks one question: what is this person's role?
`active_role` (`app/api/deps.py`) returns the **newest** live assignment and
ignores any other, although `role_assignment` already allows several rows per
person. The frontend chooses whole screen trees by the role's name
(`frontend/src/App.tsx`: `role === "operations_manager"`,
`role === "customer_service"`), and about thirty places in the backend and five
in the frontend compare role names.

So a mix of jobs has to be invented as a role of its own. The operations
manager is defined as Operations **plus** the Inbox (`app/core/permissions.py`)
because a person could hold only one role. With Production, Finance and People
coming, every combination somebody might need (customer service who also looks
up models; a production lead who also sees Operations) would be another
invented role.

Three more gaps matter once more people hold money and customer data:

- There is **no second step at sign-in**. A stolen password is a full login.
- The session table already records each device, address and last-seen time
  (`auth_session`), but nobody can see or end their sessions except by
  changing a password.
- `audit.view` shows the **whole** trail: anyone who may read it reads payroll's
  history as well as their own department's.

## Decision

1. **A person may hold several roles at once. What they may do is everything
   their live roles grant together.** Roles stay named bundles defined in code
   and covered by tests (ADR 0007 stands); only how many a person holds
   changes. Assignments are still revoked, never deleted, so the trail can
   still say what access someone had when they acted.
2. **The kind of account is separate from its roles.** Staff hold roles.
   A model reaches the portal by owning the model record (ADR 0006), and a
   supplier reaches Production's supplier portal the same way (ADR 0069): by
   owning the work assigned to them, never through a staff permission.
3. **Each department offers levels: viewer, staff, manager**, with the owner
   above all. Each department defines in code what each level grants. Where a
   department's real jobs do not fit the ladder, it keeps a named role (the
   content manager of ADR 0018 stays as defined). Today's roles become:
   - admin → **owner**
   - operations manager → **Operations manager** and **Inbox staff**
   - customer service → **Inbox staff**
   - affiliate manager → **Affiliates manager**
   - content manager → **Affiliates content manager**, as now
4. **Money is created, approved and paid under three separate permissions, and
   no role but the owner's holds all three.** Today's split (approving payroll
   is not recording a payment) becomes the rule for every department that
   handles money.
5. **Two-step sign-in, with an authenticator app**, is required for the owner
   and for anyone who can approve or pay money, and available to everyone
   else. Losing the phone is recovered with one-time recovery codes, or by the
   owner resetting it, which is audited.
6. **Each person can see where they are signed in and sign out everywhere.**
   The owner can do the same for anyone, and **suspending** someone removes
   every role and ends every session in one action.
7. **The audit trail carries the department of each entry.** Reading the
   trail becomes per department; only the owner reads all of it.
8. **The rules that already hold keep holding**, now stated against levels:
   nobody grants access they do not hold (`can_grant`, checked against the sum
   of their roles); there is one Operations manager at a time (ADR 0057);
   customer details show only to Inbox holders (ADR 0059).
9. **The interface asks about permissions, never role names.** Screens are
   chosen by what a person may do (ADR 0068's department list), so adding a
   role never means editing a list of names.

## Consequences

- Every role-name comparison changes, about thirty in the backend and five in
  the frontend, each with its test. The session's single `role` becomes a list.
- A person with many roles can collect more access than anyone intended.
  Team and access shows, in words, what a person's levels give them (the
  approved mockup's *What this gives* line), so it can be read at a glance.
- Two-step sign-in adds a step for the people who handle money, and a
  recovery path that must itself be safe: the owner's reset is audited, and
  recovery codes are shown once and stored only as hashes.
- An entry's department has to be set by the code that writes it. Older entries
  have none and stay visible only to the owner.

## Alternatives considered

- **Keep one role per person and invent combinations** (today). Grows with
  every department and every mix of jobs; each new role is a code change and a
  migration of the role check.
- **Tick permissions per person.** Rejected by ADR 0007 for good reasons: easy
  to misconfigure, hard to explain six months later.
- **Rules by record** ("this agent sees only their own chats", "this
  supervisor sees only their workshop"). Not built in general. A department
  adds such a filter when it has a real need, in its own code.
