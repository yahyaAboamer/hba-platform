# What HBA needs to supply before historical months can be finalised

One list, for Yahya. Nothing here can be worked out from the data — each item
is a fact only HBA holds, and the platform refuses to guess any of them.

**Finalising is locked until these are supplied and checked.** The *review* is
open and needs no unlock: Settings → Historical setup names every gap, per
model, and links to the screen that fills it.

---

## 1. When each model actually started with HBA

Her **collaboration start month**, not her first sale. They are different for
anyone signed before she sold anything, and the months in between are exactly
where a salary belongs.

- Where it goes: the model's profile.
- What happens without it: her month list is derived from her earliest order,
  so months before that are invisible and cannot be arranged.

## 2. What each model was paid on, for every month since she started

The **arrangement per month**, with no gaps:

- `commission` — and the rate,
- `fixed_plus_commission` — the salary *and* the rate, both,
- `base_guarantee` — the floor *and* the rate.

- Where it goes: the model's pay-history grid.
- What happens without it: the month cannot be calculated at all. This is the
  single most common gap in the current data.

## 3. Whether each guaranteed month's targets were met

For **guaranteed-minimum months before go-live only**: met or missed.

The counts were never kept for those months, so the recorded outcome *is* the
evidence. The platform will not assume a pass, and will not read a missing
answer as a failure.

- Where it goes: the pay-history grid, beside the month.
- What happens without it: the guarantee cannot be decided, so the month
  cannot be finalised.

## 4. Confirmation that the order import is complete for those months

A statement from you that the orders imported for every pre-go-live month are
**all** of them — no missing range, no code that was live and never imported.

This one is not a screen. It is a judgement, and it is the most consequential
item on the list: finalising approves a figure calculated from whatever orders
are present, 05B means an agreed month is never unmade, and a month approved
on a partial import is wrong permanently and has to be corrected rather than
fixed.

## 5. Which environment to unlock, and when

Finalisation is refused until `HISTORICAL_FINALISATION_UNLOCKED` is set on the
environment being finalised. Staging and production are separate services with
separate databases, so this is set per environment, deliberately, once 1–4 are
true for that environment's data.

---

## What you do **not** need to supply

- **Transfers for historical months.** Nothing here creates a payment, a
  receipt or an opening debt. A month with no imported transfer keeps having
  none — ADR 0036 makes a pre-go-live month unpayable by construction.
- **Anything about live months.** Finalisation stops at go-live. September
  onwards is approved the way it always has been, by somebody looking at it.
- **Re-entering anything already recorded.** A month already agreed is skipped,
  so this can be run again after you fill a gap and it will pick up only what
  changed.

## How to see where you stand

Settings → **Historical setup**. The table says, per model, how many of her
eligible months can be calculated and which is the first that cannot; the
review below it totals what is ready and names every model still waiting,
with what each is waiting for.
