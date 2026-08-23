# 0013. Payroll is an action, not a schedule

**Status:** Accepted
**Date:** 2026-08-22

## Context

Orders do not finish neatly at month end. An order placed on 29 August is
routinely still in transit when payroll would run, and Egyptian cash-on-delivery
shipping makes that the common case rather than the exception.

That creates an apparent contradiction: if only settled orders count, a fixed
payout date will always leave some of the month unresolved.

## Decision

Payroll is an action the maintainer takes, not a scheduled job. Running it for
August freezes whatever is `earned` **at that instant** and pays it.

Anything still `pending` rolls into the next run automatically, appearing as a
labelled line - *"Carried forward from August - 2 orders, E£840"*. Nothing is
lost and nothing is paid early.

An order's **attribution month is the month it was placed** and never changes,
so an affiliate's "August sales" always means orders placed in August. What
moves is only *when* the money is paid.

A reminder fires on a configurable day, defaulting to the 5th, so a month is not
forgotten. It is a nudge, never a trigger.

## Consequences

Payroll can be run twice in a month, or late, or early, and the arithmetic stays
correct because it is driven by state rather than by the calendar.

Reporting and payment can differ for a given month, and that is intended. Anyone
comparing "August sales" with "the August payout" must understand the
carry-forward, so the interface labels it explicitly rather than quietly
reconciling.

Carry-forward interacts with reopening: if the destination month is still draft
the orders are reclaimed into the reopened month; if it has been approved they
stay, because that month is settled. See `docs/limits.md`.

## Alternatives considered

**A fixed payout date.** Simple, and it either pays unsettled orders or delays
the whole month for one straggler.

**Wait until every order in a month is final.** Cleanest books, and one stuck
order holds an affiliate's entire month hostage.
