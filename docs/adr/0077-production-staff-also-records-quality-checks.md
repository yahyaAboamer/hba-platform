# 0077. Production staff also record quality checks

**Status:** Accepted — owner, 7 November 2026.
**Date:** 2026-11-07
**Amends:** ADR 0076 decision 5 and its consequence "A person holding both QC
and Staff work is given Manager". Everything else in ADR 0076 stands.

## Context

ADR 0076 gave Production four levels, as the old app had them: Viewer, QC,
Staff and Manager. QC was kept apart from editing orders, so the person who
ran an order was not the one who passed its checks. Somebody doing both had to
be made Manager, which also hands them suppliers.

Before the team was given access, the owner said that the people who will use
quality control also run the production work, and asked for one level that
combines both instead of the two separate ones (7 November 2026). On that day
nobody held Production QC or Production staff on staging or production; only
Production manager had been given.

## Decision

1. **Production staff** run orders, phases, tasks, samples, photos and
   documents **and** record quality checks.
2. **Production QC is no longer a level.** Production offers Viewer, Staff and
   Manager, the same three words as every other department.
3. **Manager** stays Staff plus suppliers and the supplier portal. Approving a
   supplier payment stays the owner's alone.
4. Migration `e3c5a9d20026` moves anyone who held Production QC (or a pending
   invitation to it) to Production staff, then narrows the role checks so it
   cannot be given again.
5. In Production's own screens a staff member keeps the staff controls and
   also gets the quality-control checklist (`canCheckQc` on the signed-in
   person); they do not get the manager's supplier and settings controls.

## Consequences

- The separation between making and checking is gone: one person can run an
  order and pass its checks. The audit trail still names who ticked each check.
- A QC-only person (checks but cannot edit orders) can no longer be set up.
  Bringing it back is a new level and a new ADR.
- Rolling the migration back widens the checks again but cannot tell which
  staff were once QC; nobody was on the day it shipped.

## Alternatives considered

- **Keep QC and add a fifth combined level.** More choices for the same
  people; the owner asked for the separate ones to go.
- **Let a person hold Staff and QC together.** Team and access gives one level
  per department; holding two would break that rule for one department.
- **Use Manager for these people.** It also hands them suppliers.
