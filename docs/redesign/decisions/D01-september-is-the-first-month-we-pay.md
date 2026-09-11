# Decision — D01

**Owner's question:** What is the first month whose payments will be recorded
under the new process? Which existing statements and transfers are already
real, and which model/months are externally settled?

**Owner's answers**, 11 September 2026.

---

## The boundary

**September 2026 is the first month the platform is responsible for paying.**

Everything before it was settled outside the platform. Those months are still
calculated, approved and frozen — a model opens March and sees what March was
worth — and they are **never payable**: their balance is zero by construction
(ADR 0036), and the ledger refuses a transfer against one.

**This is what production is already configured to do.** `GO_LIVE_MONTH` is
`2026-09` there, and `2026-08` on staging. So the decision is *no change*, and
that is the point of recording it: the setting was a default nobody had
ratified, and it is now a decision somebody made.

## How much history a model sees

> There are models whose code was created on Shopify before 2026, and there are
> models that were created after 2026. So for models that were created before
> 2026, we show them the history till January 2026. And anyone that was created
> after 2026, we show him starting from his starting month.

**The later of January 2026 and her own start**, which is exactly
`max(collaboration_start_month, PLATFORM_START_MONTH)` in `months_for`.

- A model working with HBA since 2025 sees **January 2026 onwards**. Nothing
  earlier, because there are no orders indexed before then to show.
- A model who began in June 2026 sees **June onwards**. Not January, because a
  month that predates her is an empty screen with no way to tell whether that
  means *nothing happened* or *something is broken*.

**Nothing in the code changes.** `PLATFORM_START_MONTH` is already `2026-01`
and `months_for` already takes the later of the two. What changes is that the
behaviour is now the answer to a question rather than an assumption nobody had
checked — and `tests/test_release_rehearsal.py` holds it.

## What this settles, and what it does not

**Settles:** which months are payable, which are history, and what each model
sees. That is enough for Phase 09 to describe a transition.

**Does not settle:** whether any *individual* pre-September month still has
real money outstanding that HBA meant to pay and did not. The boundary says the
platform will not pay those months; it does not audit them. If one of them is
genuinely unpaid, it is settled the way it always was — outside — and the
platform is not the record of it.

**Does not settle D02** (whole-pound rounding), **D09** (a reversed failure
after recovery) or **D10** (finance roles). All three remain open and none
blocks release.
