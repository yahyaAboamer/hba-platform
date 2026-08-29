# 0022. Shopify owns the codes; the platform only records them

**Status:** Accepted
**Date:** 2026-08-25

## Context

The business walked through how affiliate codes actually work, and it did not
match how the platform was asking about them.

Models already have live discount codes on Shopify. Most have been in use for
months and carry real orders. The platform is not where codes are created — it
is where they are watched, and where a model eventually sees their own
performance. "Registering a code" therefore means *recording an existing fact*,
not creating anything.

The registration API asked for a **start month**. That framing was wrong in a
way that would have cost every model their history: the natural thing to type is
the current month, and doing so would have left every order the code had
already earned attributed to nobody. They would have opened their dashboard and
seen an empty page, and nothing anywhere would have errored.

## Decision

**Nothing about a code's dates is ever asked for. It is derived.**

Ownership starts at **the later of**:

- `PLATFORM_START_MONTH` (2026-01) — the earliest month any order data exists
- the month Shopify created the code

The field is removed rather than defaulted, and a supplied `start_month` is
ignored. There is exactly one right answer, so asking a person can only produce
a wrong one.

**Registering a code performs the Shopify lookup itself.** One call answers both
questions that matter — does it exist, and when was it made — so there is no
separate verification step that could disagree with the registration.

`createdAt` is the anchor because **a code cannot be used before it exists**,
making it a safe earliest bound on the orders it can have.

### Three consequences that follow

**A code Shopify has never heard of is still recorded, unverified.** Some models
apply with a code not yet created. Refusing to record what they applied with
would lose information; approving on it would be unsafe. Approval is gated on
verification (§10.4), which is where the difference is enforced.

**A maintainer's registration fails loudly when Shopify is unreachable.**
Registering blind would mean guessing the start month, and a wrong guess orphans
orders silently. Failing while somebody is watching is far cheaper.

**A model's own submission must never fail for the same reason.** When the
application form exists (Phase 8), verification runs in the background on the
durable queue. It would be absurd for their application to be rejected because of
*our* connection to Shopify.

## Consequences

The ordinary path claims a code's whole history without anybody thinking about
it. A model approved today sees their sales from January, or from whenever their
code was created.

**Taking the *later* date, rather than always the horizon, is what makes
handover work.** If a code previously belonged to a different model, starting
everyone at January would collide with their period and be refused by the
exclusion constraint. Each model's ownership now begins exactly when their code
did.

Registration depends on Shopify being reachable, which it did not before. That
is a deliberate trade: an unavailable Shopify blocks an action a person is
watching, rather than silently producing a wrong month.

**The three Shopify failures are kept distinguishable** — unreachable (502),
unconfigured (503), missing scope (403) — because each needs a different action.
Collapsing them would send somebody debugging a network when the fix is one
setting.

## Alternatives considered

**Default the start month to 2026-01 and keep the field.** What was built first.
It fixes the common case and leaves the trap in place: the field still invites a
wrong answer, and a code that changed hands still collides.

**Derive from the code's first *order* rather than its creation.** Tempting, and
wrong for a code with no orders yet — it would have no start at all. Creation is
always defined and always early enough.

**Ask the model for their start date.** They have no way to know when Shopify
created their code, and would be guessing about their own money.

## What this derivation assumes, and where it stops

Deriving the start month from the code's creation date carries a hidden
assumption: **that a code is created at the moment a model is switched onto
it.** That is how HBA works, but it is a habit, not a rule.

When it does not hold — a code set up in July, switched to in September — the
derivation ends the old code in June while they were still earning on it, and two
months of their orders belong to nobody. The creation date answers "when could
this code first have earned?", not "when did they move over?", and the two are
only the same by convention.

So the handover **refuses** rather than guesses, and only when it would actually
strand orders: a code created early that nobody used costs nothing. Choosing a
handover month explicitly is deliberately not built, and is recorded in
`docs/limits.md` under *A code created before the switch cannot be handed over*
with what to do if the refusal ever appears.

Registration (as opposed to handover) is unaffected: a first code has no
predecessor to end, so an early creation date only means their history starts
earlier, which is correct.
