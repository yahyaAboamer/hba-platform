# Phase 4 — Commission engine, commission states, rounding

**Spec:** `docs/specs/2026-08-22-hba-platform-v1-design.md` §9 (all), §8, §10.2, §17
**ADRs this phase implements:** 0002, 0003, 0004, 0011, 0012, 0023
**Depends on:** Phase 2 (order index, Shopify client) and Phase 3 (who owns which code when)
**Delivers:** what each affiliate is owed for a month, and why.

---

## What this phase is for

Phase 3 answered *whose sale is this*. Phase 4 answers *what is it worth*, and it is the
first phase where a wrong answer costs real money.

It exists to fix two confirmed defects in the live dashboard (§9.1), both verified against
baseline commit `46d942b` and real order data:

**Commission is paid on undelivered orders.** `_with_commission()` applies the rate to every
order in the month regardless of status. Failed deliveries are neutralised only by an
external Shopify automation that auto-cancels them — protection that lives outside the
codebase and would vanish silently if anyone switched it off. For a brand shipping
cash-on-delivery through Bosta, refusal rates are material.

**In-flight exchanges inflate the base.** Order `#29115` is the worked example: the customer
paid **E£1,157** (E£1,062 of goods plus E£95 shipping), but mid-exchange Shopify reports 3
items totalling **E£1,675** because E-stebdal has added the replacement without removing the
returned item. The old dashboard calculated on roughly E£1,557 — **about 47% too much on one
order** — and handled `partially_paid` nowhere.

Both are arithmetic failures with the same root: **reading Shopify's current numbers at
calculation time.** This phase reads them once, decides when to stop reading them, and stores
what it decided.

### The one sentence the whole phase serves

> **Commission base = total the customer pays − shipping − tax**, after all discounts,
> **frozen the moment a return or exchange begins.**

`#29115` gives `1,157 − 95 = E£1,062`. That number is an acceptance test, not an
illustration.

---

## The three properties that must hold

**1. An order's affiliate never changes.** (§9.2, §17) Orders do not move between models. An
unattributed order may be *attached* when its code is registered for the first time — that
assigns an orphan, it does not reassign. Enforced by trigger, not by care.

**2. Nothing is truncated mid-chain.** (§9.6, ADR 0003) `base × rate_bp` produces fractional
piastres: `106,237 × 1000 ÷ 10,000 = 10,623.7`. The numerator is carried un-divided.
Rounding happens **once**, half-up, on the **final month total**, never per order. Rounding
each of forty orders before summing compounds forty errors.

**3. A house account can never enter a payable total.** (§8, §17) `HBA10` is a real code used
by real customers and needs a working dashboard for verification. It is not owed money.

---

## What is not yet a fact

Two things this phase depends on cannot be settled by reading the codebase, and **will be
turned into facts before anything depends on them** — the same way `/shopify-scopes` turned
"is the scope granted?" from a guess into an answer.

**Exactly what Shopify calls a delivered order, and on how many.** ADR 0012 makes `earned`
mean *delivered*, not *fulfilled*. Those are different: `displayFulfillmentStatus` reaches
`FULFILLED` when the parcel leaves HBA, and delivery is a courier event afterwards.

HBA has confirmed Shopify's status does update as the shipment moves, and ADR 0023 settles
that this is the source — Bosta is not integrated. What remains is the specific enum values
the live shop actually produces, because the state machine in Task 4 is written against them
and *shipped* must not be mistaken for *delivered*. For cash-on-delivery through Bosta, the
gap between the two is where refusals live.

**The signal can also stop without saying so.** Whatever writes that status into Shopify sits
outside this codebase, exactly like the auto-cancel automation in §9.1. If it breaks, every
month calculates to zero earned — correctly, silently, and indistinguishably from a month
with no sales. Recorded in `docs/limits.md` as 🟠 before the code exists; the watch that
catches it is sized to the failure rather than to a second courier integration (ADR 0019).

**Which return and refund fields are actually readable.** `Order.returnStatus` and the refund
objects may sit behind `read_returns` rather than `read_orders`. Task 2 probes them against
the live shop and records what came back. **No new write scope is requested by this or any
phase.**

---

## Task list

| # | Task | Delivers |
|---|---|---|
| 1 | `attributed_order` | The table, and `affiliate_id` immutable by trigger |
| 2 | The facts orders carry | Delivery, returns and refunds — and what the live shop actually reports |
| 3 | Base, freeze, refunds | ADR 0011 as code, with `#29115` as the test |
| 4 | Commission state | ADR 0012 as code: `pending` / `earned` / `void` |
| 5 | Attributing as orders arrive | Attribution stops being read-only |
| 6 | Backfill on registration | The orphans Phase 3 deferred, attached |
| 7 | The month calculation | Three compensation types, exact arithmetic, one rounding |
| 8 | Earnings API | What a month is worth, and what is blocking it |

---

## Task 1: `attributed_order`

**Files:** create `app/models/attributed_orders.py`; one Alembic migration; test
`tests/test_attributed_orders.py`

The second tier of §10.2 — full financials for attributed orders only. Roughly 1.4 KB per row
against ~150 bytes in `order_index`, at about 15% attribution.

**Columns:** `shopify_order_id` (primary key, and a foreign key to `order_index`),
`affiliate_id`, `business_month`, `commission_base_piastres`,
`refunded_merchandise_piastres`, `commission_state`, `base_frozen_at`, `financial_status`,
`fulfillment_status`, `delivered_at`, `return_status`, `attributed_at`, `updated_at`.

**`business_month` is copied, not joined.** It is the month the order was *placed*, derived in
Cairo (ADR 0005) and never recomputed. Copying it means a month's figures cannot shift
underneath an approved payroll because something upstream changed.

**Not append-only.** The base legitimately moves while an order is pending. Only
`affiliate_id` and `business_month` are frozen — a row-level `BEFORE UPDATE` trigger. Making
the whole row append-only would force a new row per fulfilment event, which is storage spent
protecting two fields a trigger protects for nothing (ADR 0019).

**Tests:** the trigger refuses a reassignment and refuses a month change; rewriting the same
affiliate back is not a move; base and state update freely; the row dies with its order; an
affiliate with earnings cannot be deleted out from under them.

### Two corrections to this task, made while building it

**`affiliate_id` is NOT NULL, and attaching an orphan is an INSERT.** This plan said the
trigger would "permit setting `affiliate_id` where it was null". That implied a nullable
column and therefore a row per order — which duplicates `order_index` at nine times the size
and defeats the whole point of two-tier storage (§10.2). A row existing here *means* the order
is attributed. An unattributed order is an `order_index` row with nothing here, and Task 6
attaches an orphan by inserting.

**`business_month` is frozen too, not just `affiliate_id`.** §17 requires only the second. But
the trigger is already firing on every update, so checking one more column costs a single
line, and a month that could move is money moving between payroll periods — the same failure
as reassignment. Free, so taken (ADR 0019).

**`settled_at` and `settled_in_snapshot_id` are deferred to Phase 6.** They record which
approved snapshot paid the order, and snapshots do not exist yet. Adding them now means two
nullable columns with no writer, no constraint and no test, which read as features and are
lies. Phase 6 adds them with the foreign key that gives them meaning, in one migration.

---

## Task 2: The facts orders carry

**Files:** modify `app/services/shopify/queries.py`, `app/services/shopify/normalise.py`,
`app/models/orders.py`; add `GET /api/operations/order-facts`; one migration; tests

Adds to the order query the fulfilment `displayStatus` set, `returnStatus`, and refund
totals. Normalises them into three derived facts: **delivered at**, **is a return or exchange
open**, and **refunded merchandise value**.

**`GET /api/operations/order-facts`** reports, over the orders already indexed: how many carry
a delivery signal, the distribution of fulfilment display statuses, how many have a return
open, and **which of the requested fields Shopify refused**. This is the instrument that
answers both open questions above, and it exists before anything reads them.

*If the report shows the live shop never gets past `FULFILLED`*, Task 4 does not proceed on
assumption. The finding is brought back for a decision — "earned on delivery" would then be
unimplementable as written, and the alternative (earning on fulfilment, carrying real refusal
exposure) is a business decision about real money, not mine.

The report also becomes the maintainer's standing check that the signal is still alive. A
month calculating to zero earned looks identical to a month with no sales; this is what tells
the two apart.

**Tests:** each derived fact against fixture nodes — an order with no fulfilment, a partially
fulfilled one, a delivered one, and one mid-exchange.

---

## Task 3: Base, freeze, refunds

**Files:** create `app/services/commission/base.py`; tests

Pure functions, no database:

```
commission_base(total, shipping, tax) -> int
should_freeze(return_open, has_refund) -> bool
apply_refund(base, refunded_merchandise) -> int
```

**The freeze is the whole point.** The base tracks Shopify while the order is pending and
nothing has been returned, so a genuine pre-shipment edit is reflected. The moment any return
or exchange activity appears, the stored value stops moving — permanently. Because it is
never re-read, the `#29115` inflation cannot reach the calculation.

**Freezing is not the same as ignoring refunds**, and an earlier draft of this rule conflated
them. A customer who buys a jacket at E£1,000 and pants at E£600 and genuinely returns the
pants leaves a base of **E£1,000**, not E£1,600 — while the month is still draft. After
approval, HBA absorbs it (ADR 0012). The freeze defeats a Shopify artefact; it was never
meant to pay for goods that came back.

**Tests:** `#29115` produces exactly `106,200` piastres; a frozen base ignores a later
subtotal change; a partial refund reduces it; a full refund voids rather than reducing to
zero; an exchange with no net refund changes nothing.

---

## Task 4: Commission state

**Files:** create `app/services/commission/state.py`; tests

`pending` — in transit, or an exchange is open. `earned` — delivered, with no open return or
exchange. `void` — cancelled, fully refunded, or failed delivery.

**What HBA reports seeing in Shopify**, to be confirmed against live numbers by Task 2:
delivered, failed delivery, and in-transit for everything in between. That maps onto the
three states directly — `DELIVERED` earns, a delivery failure voids, anything else is
pending. Written down here so Task 2 checks a stated expectation rather than browsing an
enum, and so a *missing* third value is noticed rather than assumed away.

Only `earned` counts toward a payout. `pending` is displayed separately rather than hidden,
so a model can see what is coming.

**Tests:** every transition, and specifically that `partially_paid` — handled nowhere in the
old system — does not pass through as normal.

---

## Task 5: Attributing as orders arrive

**Files:** create `app/services/commission/attribute.py`; modify the sync and webhook paths;
tests

Turns `resolve()` (Phase 3, read-only) into a write. On every order that arrives or updates:
resolve it, and where attributed, upsert the `attributed_order` row with its base and state.

**A held order — two registered codes — writes nothing** and raises a visible anomaly. It
waits for a human, exactly as §9.2 requires: `ANOMALY attribution_held` naming the order and
the codes that conflicted, with a `docs/limits.md` entry to match.

**Tests:** an attributed order writes a row; a held order does not; re-processing the same
order does not double-write; an order whose code later moved to another model keeps its
original affiliate.

---

## Task 6: Backfill on registration

**Files:** create `app/jobs/backfill.py`; modify `app/services/codes.py`; tests

The orphans Phase 3 deferred to here. Registering a code enqueues a background job that finds
every indexed order using that code in the months the affiliate owns, and attaches the
unattributed ones.

**Attaching, never moving.** An order that already has an `affiliate_id` is skipped, not
overwritten — Task 1's trigger would refuse it anyway, and the job must not fail because of a
row it was never entitled to touch.

**Affiliate creation never blocks on it** (§10.3). The job reports progress, and a failure is
visible rather than buried.

**Tests:** the two Phase 3 deferred by name —
`test_backfill_attaches_previously_unattributed_orders` and its sibling — plus: an already
attributed order is untouched; only months she owns are attached; the job is idempotent.

---

## Task 7: The month calculation

**Files:** create `app/services/commission/calculate.py`; tests

```
calculate_month(db, affiliate, month) -> MonthCalculation
```

Sums the `earned` bases for the month, applies that month's terms (Phase 3 — historical
months use historical terms), and applies the type:

| Type | Payout |
|---|---|
| `commission` | base sum × rate |
| `fixed_plus_commission` | commission **plus** the fixed amount |
| `base_guarantee` | **max(commission, base amount)** — targets achieved *and* verified |

The base is never added on top of a higher commission, and never caps it.

**`base_guarantee` cannot be fully resolved in this phase.** Targets are Phase 5, so
"achieved and verified" has no answer yet. The calculation returns the commission figure
**and an explicit unresolved marker** — never silently assuming targets were missed, which
underpays, and never assuming they were met, which overpays. Phase 6's approval blocks on it.
Recorded in `docs/limits.md` as 🔴 before the code exists.

**Arithmetic:** `Decimal`, numerator carried un-divided, half-up on the final total only.
Both `exact_unrounded_piastres` and the rounded figure are returned, because the audit has to
show what was calculated as well as what was approved.

**Tests:** each type; a month spanning a rate change; forty orders proving per-order rounding
would drift; a house account returning zero payable; `E£10,608.37 → E£10,608` and
`E£10,608.50 → E£10,609`.

---

## Task 8: Earnings API

**Files:** create `app/api/earnings.py`; tests

`GET /api/affiliates/{id}/earnings/{month}` — the calculation, the orders behind it, and
whatever is unresolved. `GET /api/earnings/{month}` — every affiliate for that month.

Both permission-gated. **No customer PII reaches either**: order number, date, base, state.
Never a name, an address, or a phone number.

---

## Deliberately not in this phase

- **Payroll months, snapshots, approval** — Phase 6. This phase calculates on demand; it does
  not freeze a figure or decide that anyone is owed it.
- **Targets** — Phase 5, which is why `base_guarantee` is left explicitly unresolved.
- **Payments** — Phase 7. Nothing here records money moving.
- **The affiliate-facing view** — Phase 9.

---

## Risks

**The delivery signal.** Not whether it exists — HBA has confirmed it does, and ADR 0023
settles Shopify as the source. The risks are that *shipped* gets mistaken for *delivered*,
and that the signal stops without a symptom. Task 2 answers the first with live numbers and
gives the maintainer the instrument for the second, before Task 4 needs either.

**Freezing at the wrong moment.** Freezing too early misses a legitimate pre-shipment edit;
too late lets the exchange inflation in. The trigger is *any* return or exchange activity,
and Task 3's tests pin both edges.

**A month recalculating differently after approval.** Prevented structurally: `business_month`
is copied onto the row, terms are effective-dated, and the base is frozen. Phase 6's snapshot
makes it permanent.
