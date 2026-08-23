# 0002. Money is integer piastres, never floats

**Status:** Accepted
**Date:** 2026-08-22

## Context

The old dashboard stored and calculated money as floating-point numbers. Its own
project history recorded this as a known risk.

Floating point cannot represent most decimal fractions exactly. `0.1` is stored
as `0.1000000000000000055511151231257827...`, so arithmetic drifts. On a system
that decides what people are paid, that drift is invisible until someone
reconciles a payout by hand and finds it a piastre out - by which time the cause
is months in the past.

## Decision

Every monetary value is an integer number of piastres. 1 EGP = 100 piastres.

No float touches money in storage, in transport, or in calculation. The money
module refuses a float argument outright rather than converting it, because a
float arriving at the boundary means precision was already lost upstream where
nothing can recover it.

Currency columns are `bigint`, not `integer`.

## Consequences

Every amount must be converted at the system boundary, and display code must
divide by 100. Shopify's decimal strings are parsed with `Decimal`, never
`float`.

`bigint` costs four extra bytes per value and removes any practical ceiling: the
limit becomes roughly E£92 quadrillion per field rather than E£21 million. A
test stores a E£20 million order specifically so that narrowing the column later
fails loudly.

## Alternatives considered

**`Decimal` throughout.** Correct, and used for intermediate commission
arithmetic (see 0003), but as a storage type it invites accidental float
conversion at every boundary. Integers cannot be silently coerced into
imprecision.

**Floats with careful rounding.** This is what the old system did.
