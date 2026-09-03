# 0014. Pre-go-live months show sales, never commission

**Status:** Superseded by [0036](0036-pre-go-live-months-are-ordinary-months.md)
**Date:** 2026-08-22
**Superseded:** 2026-09-04

> **Why this was superseded.** The decision below rests on one premise: that
> the compensation terms in force before go-live *"exist only in the old system
> and in people's memory"*. That stopped being true when the business chose to
> enter them by hand, month by month, through the pay-history editor. With the
> terms in the database, those months can be calculated by the same engine as
> any other month.
>
> **What ADR 0036 keeps:** a pre-go-live month can never be paid. The
> protection moves from refusing to calculate the month to the month's balance
> being structurally zero, which is the stronger guarantee.
>
> **What ADR 0036 changes:** those months now show a commission figure, and
> the `historical` state disappears from every model-facing screen.

## Context

The platform starts with no data and rebuilds order history from Shopify back to
1 January 2026. That gives every affiliate several months of orders with no
payroll records attached.

Without intervention, every one of those months would appear unfinalised and
owed - money the business already settled outside the platform. Showing an
affiliate that they are owed eight months of back pay would be alarming and
wrong.

Calculating those months correctly is not possible either. It would require the
compensation terms in force at the time, which exist only in the old system and
in people's memory.

## Decision

A configured **go-live month** divides time. Months before it have their own
state, `historical`: imported and visible, but never payable, never approvable,
and never appearing in "owed".

**Historical months display order counts and net sales only - never a commission
figure.** Historical compensation terms are not reconstructed.

They are labelled *"Settled before the platform"*.

## Consequences

Affiliates and staff can see real sales history, so the platform is useful from
day one rather than starting blank.

Nobody is shown a commission figure that would be a guess. Applying today's rate
to last March's sales would produce a number that looks authoritative and is
not, which is worse than showing nothing.

If historical commission is ever genuinely needed, it must come from the old
dashboard, which is kept read-only for exactly this reason.

## Alternatives considered

**Reconstruct historical compensation terms by hand.** Possible, and it invites
transcription errors nobody could later verify, in service of figures that will
never be paid.

**Import orders only from go-live.** Simpler, and it throws away real sales
history that costs almost nothing to keep.
