# 0080. Targets offers a box only where a save keeps it, and is a list of cards on a phone

**Status:** Accepted (owner, 10 November 2026)
**Date:** 2026-11-10

## Context

The Targets refinement (`docs/design-refinement/targets/JOURNAL.md`) found the
approved grid (`Admin Dashboard.dc.html`, lines 465-525) offering boxes where
nothing typed could be kept:

- an agreed month, which the server refuses on save (`assert_recordable`), so
  the whole grid's save failed with one banner;
- a month from before the platform, which holds an outcome and no counts
  (ADR 0036), drawn as empty boxes *of 0*;
- achieved counts for a month that has not started, which the server accepted;
- achieved counts for a model with no requirement, which the screen skipped in
  silence: *0 rows saved*, and the figures disappeared.

The export also has no phone layout for this screen. At 390px the table kept
its columns; the stories box, the outcome and the date sat off the right edge.

The weekly pace line (D08) stayed on finished months, where it repeated the
outcome or contradicted it (*Below target · On pace · 18 of 18*), because pace
adds videos and stories while the target needs each. The owner kept the total
in any mix as the weekly rule (10 November 2026).

Bare applications (pending, no terms) were listed with empty boxes and an
amber *No record yet*.

## Decision

1. **A row or month that cannot be saved shows its figures as text, with the
   reason:** *Agreed in payroll*; a note that the month is before the
   platform; a note that the month has not started, with *Set requirements*;
   *Set requirements first* in place of the boxes for a model nobody has asked
   anything of. The grid's rows carry `agreed` (read-only) for this. No server
   guard changes.
2. **Pace shows in the running month only**, as *Week 2 · on pace* /
   *Week 2 · 3 short* / *Not updated in week 2*. Its rule is unchanged.
3. **Bare applications are left off the grid** (`grid_roster`), and so off
   Today's *targets not set* count, which reads the same roster. A pending
   model HBA has given terms stays.
4. **On a phone (≤ 640px) each model is a card:** name and arrangement, then
   the outcome, then *Videos* and *Stories* side by side; the date is left
   off. The `<table>` stays underneath for screen readers. Controls are 44px,
   inputs 16px.
5. Smaller wording, from the export where it has words: *No model matches that
   search.*, *Requirements saved for November 2026*, a marked box with its
   reason under it, *Whole year*'s consequence written beside it, *Confirm*
   saying what it releases and why it is greyed.

## Consequences

- The screen departs from the export on a phone, and in drawing locked rows as
  text. The export's desk layout is otherwise unchanged.
- Today's *targets not set* no longer counts bare applications; its number
  can drop by the number of open applications.
- A requirement cannot be emptied from the grid (it never could; now it says
  so: *Type 0 for nothing asked*).
- The date of the last update is not on the phone card.

## Not changed

Every calculation, the pace formula, the save and confirmation requests,
permissions, the revision check, and every server refusal.

## Alternatives considered

- **Pace per kind** (behind if videos or stories is short of its own line):
  recommended first, then dropped: it reverses the owner's *any mix* rule, and
  hiding pace on finished months already removes the contradiction.
- **Keep the boxes and let the server refuse:** the refusal arrives after the
  typing, for the whole grid, and in the no-requirement case never arrived.
- **A horizontally scrolling table on the phone:** what it was; the answer
  (the outcome) was the part that scrolled away.
