# 0003. Commission multiplies first and divides once

**Status:** Accepted
**Date:** 2026-08-22

## Context

Commission is a base amount times a rate. The obvious implementation calculates
it per order and sums the results.

That truncates a fraction of a piastre on every order. Demonstrated with three
real-shaped orders:

| | |
|---|---|
| Truncated per order, then summed | 20,622 piastres |
| Exact | 20,623.7 piastres |
| Lost | 1.7 piastres |

Small on three orders. Across a month of orders, across twenty affiliates, it
becomes a systematic shortfall that nobody reconciles because nobody can see it.

## Decision

`commission_numerator(base, rate_bp)` returns `base × rate_bp` **undivided**.
Callers sum those integers across every order in a period, and
`exact_commission_piastres()` performs the single division at the end.

Rates are stored in basis points so the multiplier is an integer.

## Consequences

Commission cannot be read off a single order without context: the per-order
figure is a numerator, not an amount. Any future per-order display must divide
for presentation only and must not feed that result back into a total.

The intermediate carries a fractional piastre, so it is `Decimal` rather than
`int`. This is the one place fractional money legitimately exists, and it never
reaches storage.

## Alternatives considered

**Round each order to the nearest piastre.** Halves the drift rather than
removing it, and still produces a total that disagrees with the exact figure.

**Store rates as decimals.** Reintroduces the float risk 0002 exists to prevent.
