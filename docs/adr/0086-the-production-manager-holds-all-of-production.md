# 0086. The production manager holds all of Production, money included

**Status:** Accepted (the owner, 17 November 2026)
**Date:** 2026-11-17

## Context

ADR 0084 made creating orders, approving samples, settling and every amount
of money the owner's alone (`production.owner`, held only by admin), and
said the QC manager never sees money. The production manager role was given
the QC manager's work plus suppliers, so it could not create an order. The
owner, 17 November 2026: "a production manager should get everything on the
production tab."

## Decision

1. The **production manager** holds `production.owner` as well: creating and
   editing orders, approving samples, settling, writing off, reopening
   stages, the typical days, purchases, payments, the supplier account and
   receipts, ratings, and seeing every cost and balance.
2. **Production staff** stays the QC manager's level: the stage checks, cut
   counts, the final inspection, deliveries, confirming the factory's cut,
   tasks. It **never sees money**, as ADR 0084 decision 9 says.
3. The viewer reads without money; the factory's login is unchanged.

## Consequences

- Giving someone the production manager role gives them Production's money.
  Only an admin can give it (a role is given only by someone who holds all
  of its permissions).
- Every no-money test now covers the viewer and production staff; new tests
  prove the production manager creates, settles and sees the money.
