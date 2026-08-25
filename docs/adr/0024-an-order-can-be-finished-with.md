# 0024. An order can be finished with, and an exchange finishes it

**Status:** Accepted
**Date:** 2026-08-25

## Context

ADR 0011 says the commission base **freezes** when a return or exchange begins.
That is correct and it is also weaker than it sounds. "Frozen" describes a
number that has stopped moving; it says nothing about the order, which the rest
of the system still treats as live — recalculated, re-read, and able to change
state.

HBA put it better: *why freeze an exchange when the order is simply finished
with?* A delivered order past its return window is finished. An exchanged order
is finished. Both are cases of the same thing, and the platform had a word for
neither.

The gap showed up as a real bug. `RETURNED` — meaning *the return is complete* —
was treated as "a return is open", so every finished return and every finished
exchange would have sat in `pending` for ever: never paid, never voided, nothing
reporting it. That bug exists because there was no concept of *done*, only of
*changing* and *not changing*.

## Decision

**An order can be finalised.** A finalised order's commission base and state
never change again, and nothing re-reads it from Shopify.

Four things finalise an order:

| Cause | Base |
|---|---|
| An exchange resolved on it | Unchanged — whatever it was before the exchange |
| Delivered, and the 10-day return window elapsed | Unchanged |
| Cancelled, fully refunded, or failed delivery | Zero, `void` |
| Paid in an approved payroll | Unchanged (§9.3 already absorbs later movement) |

**Finalised is not the same as earned.** An order delivered yesterday is
`earned` and pays this month, but it is not finalised — a return in the next
nine days can still void it while the month is draft. Keeping the two separate
is what lets a model be paid promptly (ADR 0012) without pretending the outcome
is settled.

### An exchange finalises the order at the original sale

The model earns on what she sold. The exchange is HBA's service, not hers:

- She keeps her commission on the original order, in full.
- Any price difference — the customer paying more for a pricier replacement, or
  being refunded for a cheaper one — is **HBA's**, in both directions. She sold
  the first item; she did not sell the replacement.
- Refunds settled outside E-stebdal, exchange shipping fees, and the "refund
  needed" flag Shopify is left showing all fall after finalisation and cannot
  reach the calculation.

**Nothing is taken from her and nothing is added.** That was HBA's phrasing and
it is the whole rule.

## Consequences

The unreliable data in `docs/limits.md` — Shopify refund figures that are not
what HBA refunded, and sometimes absent — stops mattering for exchanges
entirely. There is nothing to read, so nothing to read wrongly.

A finalised order is a fact the model's dashboard can show: *this one is
settled*, as against *this may still change*. That is one of the questions
§16's policy text would otherwise have to explain in prose.

**It makes the exchange-versus-return distinction load-bearing.** Both open an
identical Shopify return, and now they resolve to opposite outcomes: an exchange
finalises at the full base, a plain return reduces it. Getting that wrong pays
the wrong amount in one direction or the other, so it is not something to infer.
See `docs/limits.md`.

## Alternatives considered

**Keep only the freeze.** Sufficient for the arithmetic and silent about the
order. It is what allowed a completed return to look permanently open.

**Pay no commission at all on an order that was exchanged.** A stricter reading
of "the model did not do the exchange". Rejected: she did make the original
sale, the customer kept goods of comparable value, and withholding her
commission because a size did not fit punishes her for something she has no part
in and cannot influence.

**Wait for the return window before paying anything.** ADR 0012 already rejected
this — it delays every affiliate's earnings by ten days to recover a small
number of reversals.

---

## Simplified by ADR 0025, 26 August 2026

The idea survives and got stronger: an order can be finished with, and a finished
order is never recalculated or re-read.

What changed is *when*. This ADR listed four triggers, one of which was "an exchange
resolved on it" — which required telling an exchange from a plain return, and that
turned out to be unanswerable from the available data. ADR 0025 replaces all four
with one: **delivery**.

That is simpler and strictly earlier. An exchange can only happen to a parcel the
customer already has, so finalising on delivery covers every case this ADR listed,
without needing to detect any of them.

**The exchange rule stated here is unchanged and now applies to returns as well:**
the model keeps her commission on the original sale in full, and any money moving
afterwards is HBA's, in both directions.
