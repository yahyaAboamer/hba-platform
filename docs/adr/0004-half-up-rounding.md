# 0004. Rounding is half-up, not banker's

**Status:** Accepted
**Date:** 2026-08-22

## Context

Payouts are rounded to whole Egyptian pounds. Python's built-in `round()` uses
banker's rounding, which rounds a half to the nearest *even* number:

```python
round(Decimal("10608.50")) == 10608   # down
round(Decimal("10609.50")) == 10610   # up
```

That underpays roughly half the time, and to anyone reading a payslip the
behaviour looks arbitrary - two months rounding differently for no visible
reason invites a question nobody can answer convincingly.

## Decision

Rounding is half-up: a remainder of exactly 0.50 always rounds away from zero.
`Decimal` with `ROUND_HALF_UP`. The built-in `round()` is never used on money.

Rounding happens **once**, on the final payout total, at the moment a month is
approved. Never per order.

The unrounded figure is stored on the payroll snapshot alongside the approved
one, so the audit trail shows both what was calculated and what was paid.

## Consequences

HBA absorbs a sub-pound difference on every payout. Half-up pays fractionally
more about as often as fractionally less, so it averages to approximately zero -
on the order of E£90 a year across the whole programme, which is not worth the
complexity of carrying remainders between months.

`round()` must never be reintroduced. A test asserts both of the built-in's
results directly, so the reason is recorded where someone will meet it.

## Alternatives considered

**Banker's rounding.** Statistically neutral, which is why it is the default,
but the neutrality is invisible to the recipient and the inconsistency is not.

**Carry the remainder forward.** More precise and materially more complex, for
an error of well under one pound per affiliate per month.
