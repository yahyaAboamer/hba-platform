# 0019. Size to the requirement, and record the measurement

**Status:** Accepted
**Date:** 2026-08-23

## Context

The money columns were made `bigint` with this reasoning: a 32-bit column
overflows at E£21,474,836.47, and `bigint` puts the ceiling somewhere
unreachable.

The business rejected the reasoning, correctly:

> in engineering we make things that does the job with low cost and no failures,
> not make the failure unreachable twice as much as it was already unreachable.

That is right. "Safer" is not a justification. A limit that cannot be reached is
not made better by moving it further away, and the habit of reaching for the
larger, more defensive option produces a system that is expensive and slow for
reasons nobody can point at.

## Decision

**A choice between a cheaper option and a safer one is settled by measuring, not
by instinct. The measurement goes in the commit or the ADR, so the decision can
be re-examined rather than re-argued.**

Three questions, in order:

1. **What is the largest value this actually has to hold?** Not the largest
   imaginable — the largest this column, buffer or limit will see in the life of
   the system.
2. **What does the safer option cost?** In bytes, milliseconds, or money. If the
   answer cannot be stated as a number, it has not been measured.
3. **What does being wrong cost?** A loud failure that is cheap to fix is
   different from a quiet one that corrupts data.

When the measured difference is immaterial, **say so and stop**. The decision
does not deserve more time, and neither does re-opening it.

This is not a licence to build something fragile. It rules out defensive
padding, not engineering.

## The first application: the money columns

Measured on 150,000 rows — five years of orders at current volume:

| | table size | bytes per row |
|---|---|---|
| `bigint` money columns | 35 MB | 202.7 |
| `integer` money columns | 33 MB | 186.7 |

**`integer` saves 16 bytes a row: 2 MB across five years.** No CPU difference —
64-bit arithmetic on a 64-bit processor costs the same as 32-bit.

Being wrong is loud, not silent: Postgres raises `integer out of range` and
refuses the write. It does not wrap or truncate. The order simply fails to
record.

**Decision: `bigint` stays**, for one reason that is not "safer":

`order_index` holds *per-order* values, where `integer` is genuinely
sufficient — no single order approaches E£21 million. But the money columns
still to come in Phase 3 are **aggregates**: monthly and annual totals across
the whole programme. Even at a conservative E£2 million a month, an annual total
passes the 32-bit ceiling in the first year. Those columns must be `bigint`
regardless.

So the real choice is between two money types with a per-column rule about which
to use, or one money type everywhere. The second costs **2 MB over five years**
and removes an entire category of mistake — picking the wrong one, or a
per-order column later being summed into an aggregate. At that price, uniformity
wins.

**Had the saving been material, the answer would have been the opposite**, and
the rule would have been: per-order `integer`, aggregate `bigint`.

## Consequences

Decisions of this shape now cost a measurement. That is the point — it is a few
minutes against a number that settles the question permanently.

Some of these measurements will overturn a choice already made. That is also the
point.

`docs/limits.md` remains the place where an unreachable limit is *recorded*.
Recording a limit is free; padding against it is not. The two are different acts
and this ADR only constrains the second.
