# Decision — D02

**Owner's question:** Keep the existing whole-EGP half-up rounding for final
payouts, or move to two-decimal payouts?

**Owner's answer**, 12 September 2026: **whole pounds.**

---

## What was decided

A payout settles at a **whole Egyptian pound**, rounded half-up, once, on the
total. 1,247 — never 1,247.35.

**This is what the platform already does** (ADR 0004), so like D01 the decision
changes no code. The point of recording it is that the rule was inherited from
an implementation rather than chosen: the prototype printed decimal totals and
rounded them in JavaScript, and until now nobody had said which was right.

## What it does not change

**Nothing about the arithmetic underneath.** Money stays integer piastres,
rates stay basis points, and the multiply-before-divide rule (ADR 0003) is
untouched. The rounding is the **last** step on the **total**, not something
applied to each order — rounding line by line and summing gives a different
answer, which is the failure ADR 0004 exists to prevent.

**Display precision is not settlement precision.** A screen may show piastres
where that is useful; what leaves the bank is the whole pound.

## What this settles

05A preserved and tested this rule under an instruction to proceed, and
explicitly said so *without* claiming the decision was made. It is made now.
`F05` in `PRODUCT_RULES.md` said "unless D02 explicitly changes it" — it does
not.

Open set after this: **D09 and D10** (both also answered 12 September, see
their records). D02 is closed.
