# 0056. No targets before her start

**Status:** Accepted
**Date:** 2026-10-01
**Follows:** 0055 (terms are set only from her start month)

## Context

After ADR 0055 the owner found that Ali, who started with HBA in April 2026,
could still be given targets for January to March on the Targets screen.
Staging already held three such targets (4 videos each, January to March),
written by *Whole year* before her start was known.

ADR 0055 closed months before her start for pay terms only. The Targets grid
lists every model in every month, and neither the grid, the per-month save nor
the whole-year save looked at her start.

## Decision

1. **A month before her known start has no targets.** Her start is
   `collaboration_start_month`, from her code on Shopify or typed on her
   profile. With no start recorded nothing is refused.
2. **The server refuses** creating a target there, changing its requirement,
   or recording counts against it. A target already on record that is sent
   back unchanged is accepted, because the grid re-sends what it shows.
3. **"Whole year" skips those months** and reports them as
   `before_her_start`, beside the months it already skips (agreed, or before
   the platform).
4. **The grid keeps her row** and draws it closed: disabled boxes, *Starts
   April 2026* beside her name and *Before her start* in the record column.
   It is left out of the save.

## Consequences

- Targets written before this rule stay on record and are not deleted here.
  Ali's January to March targets on staging are the owner's to keep or remove.
- A model whose start is later corrected to an earlier month gets those months
  back at once; one corrected to a later month keeps any targets already
  recorded, closed.

## Alternatives considered

- **Hide her row in months before her start.** Rejected: an absent row reads as
  a model who has gone missing, which this grid was built to prevent.
- **Delete targets before her start by migration.** Rejected without the
  owner's word: a target is a record somebody typed.
