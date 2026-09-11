# Decision — D09

**Owner's question:** How is a later correction to a previously failed Shopify
status settled, once a deduction or absorption has already been used?

**Owner's answer**, 12 September 2026:

> Shopify will never do that because once the status is delivered or failed it
> can't be the other one.

---

## What was decided

**A delivery outcome is final.** Shopify does not move an order from *failed*
to *delivered* or back. So the case D09 was opened for — money recovered on a
failure that later turns out to have been a delivery — **cannot arise**, and
the platform does not need machinery to settle it.

This is the same shape as D03, and consistent with it: *delivered* counts
permanently, *failed* removes the order permanently, and everything in between
is pending until it resolves to one of those two. What D03 established for the
use count, D09 establishes for the money.

## Why this is closed rather than deferred

A manual-review state for an event that never happens is not a safety net. It
is a screen nobody looks at, a code path nobody exercises, and a state a real
order could reach by accident with no one who knows what to do about it. The
cheaper and more honest answer is the owner's: it does not occur.

**If it ever does occur**, the answer is not to reopen this decision under
pressure. `app/services/corrections.py` already handles *"the frozen snapshot
and a fresh calculation disagree"* for any reason at all — a person carries the
difference into a later month or absorbs it (D04). A reversed delivery would
arrive there like any other disagreement, without a bespoke path.

## What this does not settle

D09 as written had a second half: **price edits to a pending order after the
month was approved.** That is not a status flip and the owner's answer does not
speak to it — but it is **already covered**, by the same corrections service and
by the same rule: an agreed month is never unmade, and what changes afterwards
is recorded against it as a correction (05C). Nothing is outstanding.

**No refund or exchange deduction after delivery.** That was the standing
handling and it stands.
