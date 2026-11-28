# 0091. The owner corrects the cut counts

**Status:** Accepted
**Date:** 2026-11-28

## Context

Once cutting is recorded, its counts could change only by reopening cutting
(ADR 0084), and only the latest finished stage can be reopened. So once
making or the inspection was done, a wrong cut count could not be fixed
without unwinding everything after it. The owner (28 November 2026) wants to
edit the cutting count himself.

## Decision

1. `production.owner` may correct the cut counts per size on an open order
   once cutting is done (`PATCH /api/prod/orders/{id}/cut`). Cutting stays
   done and no later stage is reopened. The QC manager and the factory cannot.
2. A reason is required and is kept in the order's history with the sizes
   that changed (old → new). No money is written there.
3. The checks of recording the cut still hold: at least one piece; a
   shortfall against the plan needs reasons adding up to it (the reasons are
   replaced by the ones sent); no size below what has been inspected.
4. Once the final inspection is complete, each size's cut must equal what
   was inspected, so the counts there change by reopening the inspection.
5. The cut date, the promised delivery date and the factory's cut report are
   left as they were.
6. The factory is paid per piece cut, worked out when the order is settled,
   so a correction changes what it will be owed. Settled and cancelled orders
   cannot change (as before).

## Consequences

The owner fixes a miscount in one step. Reopening cutting remains for redoing
the cut as a stage (a new date and promise).
