# HBA Platform — V1 Design Specification

**Date:** 2026-08-22 (revised after external review)
**Status:** Draft for review
**Supersedes:** the current `hba-operations-dashboard` application (frozen at cutover)
**Code references anchor to:** baseline commit `46d942b` — line numbers drift, the commit does not.

---

## 1. Purpose

HBA Aesthetics sells on Shopify in Egypt. Affiliate creators ("models") promote the brand
using personal discount codes and are paid monthly on the sales those codes generate. The
current dashboard performs this job but grew feature-by-feature across three unrelated
business needs, producing inconsistent interfaces, inconsistent data handling, and
financial rules that do not match how the business actually operates.

This specification defines a replacement: a single, deliberately designed internal platform
for HBA, built on one shared foundation, beginning with the affiliate module.

### The governing principle

> **Design the spine for the platform. Build only the affiliate module.**

Identity, permissions, audit, notifications, navigation, and the interface system are built
once, generically, so later modules plug into an existing frame. V1 ships exactly one
module. No speculative tables, no half-built screens for future departments.

### What "done" means for V1

HBA runs its entire affiliate programme on this platform — onboarding, attribution,
commission, targets, payroll, and payouts — without touching the old dashboard, without
spreadsheets for anything the platform owns, and without manual arithmetic.

---

## 2. Background: why the current system is inconsistent

Understanding the cause prevents repeating it.

The application began as an affiliate dashboard for Boda (marketing) and the models. It was
then extended twice, for unrelated reasons, by unrelated people:

| Origin | Owner | What was added |
|---|---|---|
| Affiliate commission tracking | Boda | The original dashboard |
| A production-planning HTML file | Hussam | The Production tab |
| Operational monitoring across Shopify / Bosta / E-stebdal | Amr | `hba-operations-hub`, partly merged as a Bosta tab |

Three products share one deployment because a server already existed. Nothing was designed
against a common model, so each module invented its own screens, its own editing widgets,
and its own conventions. The inconsistency is structural, not cosmetic — which is why a
visual refresh alone would not fix it.

---

## 3. Scope

### In scope for V1

- Identity, staff accounts, roles, permissions, and audit trail
- Affiliate onboarding and self-service accounts
- Discount-code attribution with Shopify verification
- Commission calculation and effective-dated compensation terms
- Monthly content targets (video/story) and verification
- Payroll lifecycle: draft → approved, with reopen and reconciliation
- Payouts with proof of transfer, and a payment allocation ledger
- Shopify order synchronisation (historical import + live webhooks + reconciliation)
- Admin interface and affiliate portal

### Explicitly out of scope for V1

| Excluded | Reason |
|---|---|
| Production module | Hussam's current HTML has diverged from what was merged; the existing Production tab is discarded entirely. V2. |
| Bosta / Operations module | Requires its own requirements exercise. V2. |
| E-stebdal API integration | E-stebdal already writes into Shopify; V1 reads Shopify. V2 adds it as settlement truth. |
| Public brand website | Future scope. V1's only public pages are the invite/apply form and login. |
| Arabic / RTL | English only. Strings must not be hardcoded, so Arabic can be added without redesign. |
| Inventory, purchasing, HR, accounting | Long-term ERP ambition; not built speculatively. |
| Dynamic permission builder UI | Deliberately rejected — see §6.3. |

### Known future needs — not built, but not designed against

**Product allocation (Boda).** Linking each product physically sent to a model, so the team
knows what content that model can produce, and what they have *not* received when deciding
whether to ship more. Needs a genuine new entity — roughly `product_allocation` (affiliate,
product, quantity, sent date, source). **Not V1**, but the affiliate and product models must
not be shaped in a way that blocks it.

**Performance ranking, possibly AI-assisted.** Requires **no new storage** — order history,
commission history, and target history already provide the inputs.

**Reversing a sale after delivery.** V1 finishes with an order the moment it is delivered
and ignores every return, exchange and refund that follows (ADR 0025). A future version may
want some of that back. The order to add it in, easiest and most valuable first:

1. **Void an order that was fully refunded.** `financial_status = 'refunded'` means every
   piastre went back, which no exchange produces. One boolean — no line items, no scope, no
   ambiguity about item counts. It removes the only case that is individually noticeable: a
   customer returns everything and the model keeps full commission.
2. **Reduce a partly-returned order.** Needs the value of the goods the customer kept, read
   from the order's line items rather than subtracted from its total — the total carries
   return shipping and HBA's manual balance corrections.
3. **Tell an exchange from a return.** The hard one, and the reason 2 is not enough on its
   own. Needs `read_returns`, and even then an exchange may swap **any** number of items for
   any other number, so it needs a rule for what the customer ended up holding rather than
   for what came back.

**Requires no new storage.** `order_index` already carries `return_status`,
`return_activity`, `refunded_total_piastres` and `refunded_merchandise_piastres` on every
order, written but never read. Whenever this is picked up, the history is already there —
which also means the real cost of ignoring it can be measured before deciding.

**Target types HBA defines itself.** V1 has two fixed numbers per model per month, videos
and stories, because that is what Sara tracks today (confirmed 26 August 2026). The shape
HBA wants eventually is **named numeric fields the business creates** — add a field, name
it, give each model a number for it — rather than two columns everyone shares whose only
difference is the target value.

*Not V1, and deliberately:* it turns a target from two columns into a definition plus values,
which is a schema, a form, and a set of questions about what happens to history when a field
is renamed or removed. **The input type is always a number**, which keeps it far smaller than
a general custom-field system — worth remembering when it is picked up.

Nothing in `monthly_target` blocks it: the achieved rule is *every requirement met*, which
generalises to any number of fields without changing.

**Unspecified future features.** The business expects more. This is the reason for the
governing principle in §1.

---

## 4. Design principles

Binding. Every rule below derives from them.

1. **The weight of the interface matches the weight of the decision.** Editing a phone
   number must not feel like changing someone's pay — and vice versa.
2. **Block the impossible before it is attempted.** Invalid states are unreachable in the
   control, not rejected after submission.
3. **Every money change explains itself before it commits.** Plain-English "what this
   changes", showing old value, new value, and affected months.
4. **Financial history is appended, never rewritten.** Snapshots are versioned; payments are
   immutable; corrections are new records.
5. **Show what supports a decision, not everything known.** Density is earned. A list does
   not automatically deserve summary metrics.
6. **One editing system, applied without exception.** Three patterns, chosen by risk (§12.2).
7. **All money is integer piastres in storage.** No floating-point currency anywhere.
8. **Invariants are enforced by the database, not only by application code.**

---

## 5. Users and roles

### People

| Person | Role at HBA | Relationship to the platform |
|---|---|---|
| **The maintainer** (Yahya) | Technical & operations manager | Builds and runs the platform. Sole admin at launch. |
| **Boda** | Owner — marketing; owns the affiliate programme | Manages models. Account added after launch stabilises. |
| **Sara** | Works under Boda | Records monthly video/story counts. |
| **Hussam** | Owner — production | No V1 access. Production module is V2. |
| **Amr** | Owner — operations | No V1 access. Operations module is V2. |
| **Models** (~20, growing) | External affiliate creators | Self-service portal. |

### 5.1 Roles

| Role | Grants |
|---|---|
| `admin` | Everything. Held by the maintainer. |
| `affiliate_manager` | Affiliates, compensation, targets, payroll preparation and approval, invitations. Intended for Boda. |
| `target_recorder` | **Record target actuals only.** Sees affiliate names, requirements, and recorded counts. No compensation, payroll, payment, or invitation authority. Intended for Sara. |
| `affiliate` | Own portal only. |

`target_recorder` exists because Sara's job is recording video and story counts. Granting
their compensation and payment authority they never uses would violate least privilege and
make the audit trail less meaningful. The role can be widened later if their responsibilities
actually expand; widening access is easy, explaining a mistake made with unnecessary access
is not.

**No account is ever shared.** Boda and Sara receive individual accounts from their first
use of the platform. Working under the maintainer's login would destroy the attribution
that the audit trail exists to provide, and it is precisely the practice this rebuild is
meant to eliminate.

Additional roles (`production_*`, `operations_*`) are added when those modules ship.

---

## 6. Identity and access

### 6.1 The identity spine

Identity is **not** rooted in the affiliate record. The platform must support staff today
and Production/Operations staff later, so the generic entities come first:

```
user_account       — email, password hash, status, created_at
  ├── role_assignment  — user, role, granted_by, granted_at, revoked_at
  ├── session          — token hash, expiry, revoked_at, ip, user agent
  └── invitation       — email, role, token hash, expiry, accepted_at, invited_by

affiliate_profile  — hangs off user_account; the affiliate's business data
```

An affiliate is a `user_account` **with** an `affiliate_profile`. Staff are `user_account`
records without one. This keeps §1's promise: when Hussam's and Amr's teams arrive, the
identity system already fits them rather than having been shaped around models.

### 6.2 Authentication

**Affiliates:** email and password, set by the model during application. No magic links, no
permanent bearer URLs. Sessions are revocable and HttpOnly.

**Staff:** invitation only. The maintainer sends an invite and selects the role; the invitee
sets their own password. **There is no public staff signup page.** Passwords are never seen,
set, or transmitted by another person.

### 6.3 Permission model — decided

Permissions and role definitions live **in code**; assignment of users to roles happens **in
the UI**.

A UI for composing arbitrary permission sets is explicitly rejected. Such builders are
complex to test, easy to misconfigure into a security hole, and hard to reason about later.
Defining roles in code means permission changes are version-controlled, reviewed, and
test-covered. Everything done routinely — invite someone, change their role, revoke access
— needs no code at all.

All permission checks are enforced **server-side**. Hiding a control in the UI is
presentation, never protection.

### 6.4 Payout destination changes — a high-risk operation

**Changing where money is sent is a money-impacting change**, not an ordinary profile edit.
A compromised affiliate account that can silently repoint an InstaPay address can redirect
an entire payout. It is therefore treated with compensation-level weight:

1. Affiliate requests the change and **re-enters their password**
2. Old and new destinations are displayed **masked** for confirmation
3. The maintainer is **notified immediately**
4. The change is recorded in the audit log with **sensitive fields masked** — raw account
   numbers and InstaPay addresses are never copied verbatim into generic before/after JSON
5. The payment screen shows a prominent warning when a destination changed recently
   (*"Payout destination changed 2 days ago"*)

Every payment record stores a **snapshot of the destination actually used**, so historical
payments never change meaning when a destination is later updated.

### 6.5 What a model may never do

A model may **never** edit anything determining what they are owed — commission rate, fixed
salary, base amount, targets, order data, or month state. Enforced server-side.

---

## 7. Timezone — a financial invariant

**Timestamps are stored in UTC. The business month is derived in `Africa/Cairo`.**

This is not a display preference; it decides which payroll month an order belongs to and
therefore who gets paid what. An order placed at 21:30 UTC on 31 August is 23:30 on 31
August in Cairo during standard time, but 00:30 on **1 September** during daylight saving.

**Never use a fixed offset.** Egypt reinstated seasonal clock changes in 2023, so UTC+2 and
UTC+3 both occur within a year. All month derivation uses the `Africa/Cairo` zone with a
maintained timezone database.

The same rule governs the 10-day return window, target deadlines, and payroll dates.

---

## 8. Domain model

Field lists are indicative, not exhaustive.

**`affiliate_profile`** — business data for an affiliate `user_account`.
`user_account_id`, `name`, `phone`, `status` (`pending` | `active` | `inactive` | `archived`),
`account_kind` (`model` | `house`), `created_at`, `deleted_at`.

`account_kind = house` replaces today's confusing `code_type='test'`. It represents HBA's own
code (`HBA10`) — a real code used by real customers, needing a working dashboard for
verification, but **excluded from payable totals and rankings**. The separate
`test_discount_codes` table is dropped; it is unused and duplicates this concept.

**`payout_destination`** — where money is sent.
`affiliate_id`, `method` (`instapay` | `bank` | `wallet`), `instapay_address_url`,
`instapay_phone`, `bank_name`, `bank_account_holder`, `bank_account_number`, `wallet_phone`,
`approved_by`, `approved_at`, `superseded_at`.

Append-only: a change creates a new row and supersedes the old, so past payments can always
resolve the destination in force at the time.

**`discount_code_period`** — effective-dated code ownership.
`affiliate_id`, `code`, `start_month`, `end_month`, `shopify_verified_at`.

**`compensation_period`** — effective-dated pay terms.
`affiliate_id`, `start_month`, `type` (`commission` | `fixed_plus_commission` |
`base_guarantee`), `commission_rate_bp` (basis points), `fixed_amount_piastres`,
`base_amount_piastres`, `expected_customer_discount_bp`.

One effective-dated table replaces today's three parallel period tables. Adding a fourth
compensation type requires no schema change.

`expected_customer_discount_bp` is stored **separately** from `commission_rate_bp` because
they are different commercial concepts (§10.4).

**`monthly_target`** — content requirements.
`affiliate_id`, `month`, `required_videos`, `required_stories`, `actual_videos`,
`actual_stories`, `recorded_by`, `verification_status`, `verified_by`, `verified_at`.

**`order_index`** — thin record of every Shopify order (§10.2).
`shopify_order_id`, `order_number`, `placed_at_utc`, `business_month`, `discount_codes[]`,
`total_piastres`.

**`attributed_order`** — full detail, attributed orders only.
`shopify_order_id`, `affiliate_id`, `business_month`, `commission_base_piastres`,
`refunded_merchandise_piastres`, `commission_state` (`pending` | `earned` | `void`),
`base_frozen_at`, `financial_status`, `fulfillment_status`, `settled_at`,
`settled_in_snapshot_id`, plus line items.

`affiliate_id` is **immutable once set** (§9.2). `business_month` is the month the order was
**placed**, derived in Cairo time — an affiliate's "August sales" always means orders placed
in August, and this never shifts. `settled_in_snapshot_id` records which approved snapshot
paid the order, which is what makes carry-forward (§11.4) computable.

**`payroll_month`** — one month for one affiliate. **Two independent states:**
`affiliate_id`, `month`, `calculation_state` (`historical` | `draft` | `approved`),
`active_snapshot_id`.

Settlement is **not** a state on this row — it is derived (§11.1).

**`payroll_snapshot`** — versioned frozen calculation.
`payroll_month_id`, `version`, `payload_json`, `content_hash`, `approved_obligation_piastres`,
`exact_unrounded_piastres`, `approved_by`, `approved_at`, `reopened_by`, `reopened_at`,
`reopen_reason`, `policy_version`.

**The payment ledger** — three entities, because one transfer can cover several months:

```
payment_transaction     — money that actually moved
  id, affiliate_id, amount_piastres, occurred_at,
  destination_snapshot_json, proof_file_id, reference, note, created_by

payment_allocation      — how that money is applied
  payment_transaction_id, payroll_snapshot_id, allocated_piastres

payroll_adjustment      — credits, write-offs, corrections
  type (credit | writeoff | correction),
  source_payroll_month_id, destination_payroll_month_id,
  amount_piastres, reason, created_by
```

A single E£10,000 InstaPay transfer allocates E£7,000 to August and E£3,000 to September
without pretending two transfers occurred. All three tables are append-only.

**`commission_policy_version`** — the rules themselves, versioned (§16).

**`integration_event`**, **`background_job`**, **`notification_outbox`** — durability (§10.5).

**`audit_event`** — append-only business audit trail, with sensitive fields masked.

---

## 9. Commission rules

The financial core, and the primary reason for the rebuild.

### 9.1 What the current system gets wrong

Two defects, confirmed against baseline commit `46d942b` and real order data.

**Commission is paid on unsettled orders.** `_with_commission()` in `main.py` applies the
rate to every order in the month regardless of `order_status`. Pending orders earn commission
immediately. Failed deliveries are currently neutralised only by an external Shopify
automation that auto-cancels them — protection living outside the codebase that would
silently disappear if that automation were disabled.

**In-flight exchanges inflate the commission base.** Order `#29115` is the worked example.
The customer paid **E£1,157** (E£1,062 of products plus E£95 shipping). E-stebdal then began
an exchange, and Shopify's subtotal now counts **both** the returned item (E£550) and its
replacement (E£495) — showing 3 items totalling E£1,675 against E£1,157 actually collected.
Furthermore `partially_paid` is handled nowhere in `shopify_client.py`'s status logic, so a
mid-exchange order passes through as normal at up to **~47% inflated value**.

### 9.2 Attribution

- An order is attributed when it contains **exactly one registered model code**. Any number
  of additional non-model codes (free shipping, seasonal promos) is permitted.
- **Zero registered codes** → unattributed, indexed only.
- **More than one registered code** → **financial hold, manual review.** HBA's current
  Shopify configuration makes this unlikely, but Shopify does permit combinable discount
  codes in general, and settings change. This is a cheap safety net, not the elaborate
  conflict subsystem the old application carried — the order simply waits for a human rather
  than silently paying the wrong person or double-paying.
- **An order's affiliate is immutable once set.** Orders never move between models.
- A previously **unattributed** order may be attached when its code is registered for the
  first time. This assigns an orphan; it does not move an order.

### 9.3 Commission base

> **Commission base = total the customer pays − shipping − tax**, after all discounts.

Verified against `#29115`: `1,157 − 95 = E£1,062`.

**Freezing rule.** The base updates while the order is `pending` with no return or exchange
activity — so genuine pre-shipment edits are reflected — and **freezes the moment any return
or exchange begins**. Because the frozen value is never re-read from Shopify, the exchange
inflation in §9.1 cannot reach the calculation.

**Refunds versus exchanges — these are different, and conflating them was an error.**

| Event | Effect on commission base |
|---|---|
| **Exchange** with no net refund (size swap) | **Base unchanged.** This is what the freeze protects against — Shopify temporarily counting both items. |
| **Partial refund** — customer keeps some items, genuinely gets money back for others | **Base reduces by the refunded merchandise value**, while the month is still `draft`. |
| **Partial refund arriving after approval** | **HBA absorbs it.** The approved figure stands; no clawback. |
| **Full refund or cancellation** | Order **voids** entirely. |

*Why this rule exists — recorded so it is not mistaken for an oversight later:* freezing the
base defeats a specific Shopify artefact where an in-flight exchange inflates the order
subtotal. It was never intended to pay commission on merchandise the customer actually
returned and was refunded for. Buying a jacket at E£1,000 and pants at E£600, then genuinely
returning the pants, leaves a commission base of **E£1,000** — not E£1,600 — provided the
month has not yet been approved. After approval, the absorb rule (§9.4) governs.

### 9.4 Commission state and return exposure

| State | Meaning | Counts toward payout |
|---|---|---|
| `pending` | In transit, or an exchange is open | **No** — displayed separately |
| `earned` | **Delivered**, with no open return or exchange | **Yes** |
| `void` | Cancelled, fully refunded, or failed delivery | No |

An order becomes `earned` **on delivery**, not after the return window expires.

**The risk HBA consciously accepts.** The return window is **10 days** from delivery.
An order delivered 31 August and approved on 5 September still carries six days of return
exposure. **HBA accepts that exposure deliberately**: the affiliate is paid, and if the
customer returns the goods afterwards, HBA absorbs the commission rather than clawing it
back. This is a business decision favouring prompt, predictable payment to creators over
perfect financial precision. It is not an oversight, and it is not probabilistic — the
exposure is real, bounded by the return window, and accepted.

**Manual out-of-window exchanges** created directly in Bosta never appear in Shopify or
E-stebdal, so a Shopify-only V1 cannot see them. This is intended.

### 9.5 Compensation types

| Type | Payout |
|---|---|
| `commission` | Sales commission |
| `fixed_plus_commission` | Sales commission **plus** fixed salary |
| `base_guarantee` | **max(sales commission, base amount)** — only when targets are achieved *and* verified |

The base is never added on top of a higher commission, and never caps it. All terms are
effective-dated by month; historical months use historical terms.

### 9.6 Arithmetic and rounding

**Storage:** all currency amounts are integer piastres.

**Calculation:** commission is `base_piastres × rate_bp`, which can produce a value with a
fractional piastre (`106,237 × 1000 ÷ 10,000 = 10,623.7`). Intermediate commission
calculation therefore uses **exact higher-precision integer arithmetic** — the numerator is
carried un-divided, or `Decimal` is used — and is **never** truncated to piastres mid-chain.
Storing currency as integers and calculating in higher precision are not in conflict; the
earlier draft's claim that nothing below a piastre may exist at any point was mathematically
impossible.

**Rounding happens exactly once**, on the **final payout total**, at approval:

- **Half-up to whole Egyptian pounds:** `E£10,608.37 → E£10,608` · `E£10,608.50 → E£10,609`
- **The total only, never per order.** Rounding each order before summing compounds error
  across dozens of orders.
- **The fraction is absorbed, not carried.** Half-up pays fractionally more about as often
  as fractionally less, averaging to roughly zero. Carrying sub-pound remainders would add
  real complexity for an error on the order of E£90/year across the whole programme.
- **Both figures are stored** on the snapshot — `exact_unrounded_piastres` and
  `approved_obligation_piastres` — so the audit shows what was calculated *and* what was
  approved.

Draft months display rounded figures marked provisional until approval fixes them.

---

## 10. Shopify integration

### 10.1 Required scopes

`read_orders`, `read_all_orders` (history beyond 60 days), `read_products`, read-only
fulfilment scopes, and **`read_discounts`** (new — for §10.4).

### 10.2 Two-tier order storage

Storing every order in full is wasteful — the live Railway volume currently sits at **431MB
of 500MB**. Discarding non-matching orders entirely is also wrong: it makes "was this code
used before registration?" unanswerable without re-scanning all of Shopify.

| Tier | Contents | Which orders | Approx. size |
|---|---|---|---|
| `order_index` | id, number, date, business month, codes used, total | **All** | ~150 bytes |
| `attributed_order` | Full financials, line items, statuses | **Attributed only** | ~1.4 KB |

At ~30k orders/year with ~15% affiliate-attributed, roughly **11 MB/year** — safe on
free-tier Postgres and a fraction of current usage. It also enables **instant code
registration**, **unregistered-code alerts** (*"SARA10 used on 23 orders but registered to no
model"*), and **programme reporting**.

### 10.3 Synchronisation

- **Historical import at go-live:** Shopify **Bulk Operations API** (`bulkOperationRunQuery`),
  1 January 2026 → go-live. Server-side, returns JSONL, avoids hundreds of throttled calls.
- **Ongoing:** webhooks for order create/update, refunds, and fulfilment.
- **Reconciliation:** a periodic sweep catching anything webhooks missed or delivered out of
  order.
- **Backfill on code registration:** background, with visible progress. Affiliate creation
  never blocks on it.

### 10.4 Code verification at approval — required gate

Before an affiliate is approved, the platform queries `codeDiscountNodeByCode` and confirms
the code exists in Shopify:

```
✅ NOUR10 found — 10% off, active, 47 uses
⚠️ NOUR1O not found — check spelling, or create it in Shopify first
```

Approval is blocked until verification passes, eliminating the mistyped-code failure class
at source.

**Verification checks the code, not the commission.** The customer-facing discount and the
affiliate's commission rate are **different commercial concepts** — a creator may give
customers 10% off while earning 5%. Verification confirms: the code exists, is active, and
matches `expected_customer_discount_bp` **if HBA has recorded one**. It never infers a
commission rate from a discount value.

### 10.5 Durability — how background work survives

"No queues" means no additional queue infrastructure. It must not mean background work
vanishes when the service restarts. Postgres provides all of it, inside the same Railway
service:

```
webhook received
  → HMAC signature validated
  → integration_event written (idempotency key = Shopify event id)   ← survives restart
  → background_job enqueued
  → worker leases the job, processes, marks success
  → on failure: bounded retry with backoff, then a VISIBLE failed job
  → reconciliation sweep detects anything missed or out of order
```

- **`integration_event`** — immutable receipt of every inbound event; duplicate delivery is
  detected and ignored rather than double-processed.
- **`background_job`** — status, attempt count, lease expiry, last error. A crashed worker's
  leases expire and the job is retried; it does not silently disappear.
- **`notification_outbox`** — emails written transactionally with the change that caused
  them, so a crash cannot produce a payment recorded with no receipt sent, or vice versa.

Failed jobs are **visible in the UI**, not buried in logs. The maintainer learns of a sync
failure from the platform, not from a confused affiliate.

---

## 11. Payroll lifecycle

### 11.1 Two independent states

Calculation and settlement are separate concerns and were previously conflated into one
column — which is what produced the awkward "Approved · Partially paid".

**Calculation state** — has the amount been agreed?

| State | Meaning | Set by | Editable |
|---|---|---|---|
| `historical` | Before go-live; settled outside the platform | Configuration, once | No |
| `draft` | Live, recalculating | System, automatically | Yes |
| `approved` | Frozen snapshot; obligation fixed | **Maintainer**, manually | No — reopen first |

**Settlement** — has money actually moved? **Derived, never stored:**

```
balance_due = approved_obligation
            − Σ payment_allocations
            − Σ credits and write-offs
```

`unpaid` · `partially_paid` · `settled` · `overpaid` are computed from that figure. This
makes a reopened month unambiguous: the calculation returns to `draft` while the platform
still knows exactly how much cash was already transferred against the prior snapshot.

Only one transition is automatic: the system creating a `draft` month when orders arrive.
**Every transition touching money is a deliberate human act.**

Today's `under_review` and `ready` states are **removed** — with one admin they are ceremony.

### 11.2 Historical months — solving the fresh-start problem

Re-importing Shopify from January 2026 gives every model ~8 months of orders with no payroll
records. Without intervention, all would appear unfinalised and owed — money already settled
outside the platform.

A configured **go-live month** divides time. Months before it are `historical`: imported and
visible, but **never payable, never approvable, never in "owed"**. Labelled *"Settled before
the platform."*

**Historical months display sales only — never a commission figure. Decided.** Historical
compensation terms are not reconstructed. Calculating March 2026's commission would require
March's rates, which exist only in the old system and in memory; applying today's rates to
last March's sales would be actively misleading, and reconstructing them by hand invites
errors nobody could later verify. Historical months therefore show order counts and net
sales, labelled *"Settled before the platform — commission not calculated."*

### 11.3 Approval

Available **individually** and **in bulk**, with bulk showing a preview of every model,
amount, and blocker before committing.

**Hard blockers** — approval is refused, not warned:

| Target situation | Approval |
|---|---|
| Not recorded at all | 🚫 **Blocked** |
| Recorded, not achieved | ✅ Allowed — base simply does not apply |
| Recorded and achieved, not yet verified | 🚫 **Blocked** — verification unlocks the base |
| Order on multi-code hold (§9.2) | 🚫 **Blocked** until resolved |

The block is on *missing information*, never on poor performance, and applies only to
`base_guarantee` affiliates.

### 11.4 Carry-forward

Orders settling after approval never alter the approved month. They appear in the next
`draft` month as a labelled line: *"Carried forward from August — 2 orders, E£840."*

This is the **common** path, not an edge case: Egyptian COD delivery routinely straddles
month end, so an order placed 29 August may still be `pending` when payroll runs on
5 September.

**On reopen**, behaviour depends on where carried orders currently sit:

| Destination month | Behaviour |
|---|---|
| Still `draft` | Orders are **reclaimed** into the reopened month, where they belong. Shown explicitly. |
| `approved` | Orders **remain** there permanently. That month is settled. |

### 11.5 Reopen and reconciliation

Reopening an `approved` month returns its calculation to `draft` and **requires a written
reason**, recorded in the audit log. The prior snapshot is preserved as a version, never
overwritten. Re-approval creates the next version, and payment allocations against the old
snapshot remain intact and visible.

Three outcomes on re-approval:

| Outcome | Resolution |
|---|---|
| New obligation **higher** | Underpaid. Record a further payment; `balance_due` shows the gap. |
| New obligation **lower** | Overpaid. **The maintainer chooses**: a `credit` adjustment applied to a later month, or a `writeoff`. Both audited and visible to the affiliate. |
| **Unchanged** | Nothing to reconcile. |

A month reopened and left unapproved raises a home-screen alert.

---

## 12. Interface

### 12.1 Visual direction

Reference point: **Stripe Dashboard** — financial-first, precise numerals, unambiguous money
states, calm density, trustworthy rather than decorative.

- **Admin:** denser; built for month-end work and scanning 20+ affiliates.
- **Affiliate portal:** mobile-first and far simpler.

### 12.2 The editing system

The current dashboard's core defect is that it has **no editing system** — a dozen improvised
widgets invented per feature. V1 defines three patterns applied by risk, without exception.

| Pattern | Used for | Characteristics |
|---|---|---|
| **Inline / fast entry** | Recording target actuals | Bulk grid; tab between fields; one save |
| **A — Focused dialog** | Name, phone, status, code type | One job; inline validation; no money impact |
| **C — Dedicated page** | Compensation, discount code, payroll, payments, **payout destination** | Own URL; full change history; mandatory "What this changes" preview |

**Payout destination sits in Pattern C, not A** — see §6.4. Where money is sent is a money
decision.

**Sara's target entry is a bulk grid** — every model down the side, one month across, tab
straight through, single save.

### 12.3 Navigation and layout

Left sidebar (Overview · Affiliates · Orders · Payroll · Payments · Targets · Settings).

List pages carry a **table ⇄ cards toggle** with a statistics header shown on both views.

*Noted tension:* an external review argued the toggle is unnecessary since responsive rules
already choose table on laptop and cards on phone, and that persistent statistics headers
invite filler metrics. The toggle is retained because it was explicitly requested after
reviewing mockups. Principle 5 still governs the headers: a page carries summary figures
only where they support the decision made on that page — never by default.

### 12.4 The month picker

The native `<input type="month">` is replaced: it selects whole words, ignores typing, maps
digits to month positions, and gives no indication a month is unselectable.

The replacement is a **month grid** where blocked months are **visibly locked before
selection**, with a legend distinguishing historical, approved, and open months.

Clicking a locked month **explains the lock and links to the reopen workflow** — it does not
reopen anything itself. Reopening approved payroll is a high-weight action requiring a reason
and an impact preview; offering it as a one-click button inside a date picker would violate
principle 1.

### 12.5 Responsive strategy

**Breakpoints:** phone `< 640px` · tablet `640–1024px` · laptop `> 1024px`.

| Element | Laptop | Phone |
|---|---|---|
| Sidebar navigation | Permanent | `☰` drawer |
| Data tables | Full table | **Cards** — never horizontal scrolling to read money |
| Statistics header | 3–4 across | Single most important number |
| Affiliate portal nav | Top tabs | Bottom tab bar |

**Admin is laptop-first.** **The affiliate portal is phone-first.** **Money never wraps or
truncates at any width** — if a figure does not fit, the layout changes, not the number.

Precise per-screen layouts are settled during implementation.

---

## 13. Affiliate onboarding

1. **Invite.** The maintainer sends an invitation link.
2. **Application.** Name, email, phone, proposed discount code, payout method and details,
   and a password the model sets.
3. **Confirmation.** Email to the model, email to the maintainer, in-platform notification.
4. **Review and completion.** **Shopify code verification is a required gate** (§10.4). Then
   compensation type, rates, amounts, and target requirements.
5. **Approval.** Email to the model with a sign-in link.
6. **Activation.** Dashboard available; historical backfill runs in the background.

### 13.1 InstaPay details

Collect the **Payment Address URL**, not merely the number, stored behind a **Pay** button
that opens InstaPay with the address pre-filled. The **phone number is collected as a
fallback**.

**Implementation discovery item:** deep-link behaviour must be verified on Android and
iPhone, with and without the app installed, before the Pay flow is built around it. The
behaviour is reported from direct business experience; it is not documented publicly, so it
is tested rather than assumed.

An **illustrated guide** on the onboarding page shows models where to find their Payment
Address. *Asset required from the business: InstaPay screenshots.*

---

## 14. Payments and proof

**The Pay button changes nothing.** It opens InstaPay and alters no state. The platform must
never record a payment that may not have happened.

1. Tap **Pay** → InstaPay opens with the address pre-filled. State unchanged.
2. The maintainer sends the money and screenshots the confirmation.
3. Back in the platform: **amount** (pre-filled with `balance_due`) plus **proof screenshot**,
   then Submit. A `payment_transaction` is written with one or more `payment_allocation`
   rows.
4. Settlement is recomputed. The model is emailed a receipt and sees the payment.

**Why the amount is editable:** partial payments; InstaPay transaction limits forcing a
split; rounding; **one transfer covering two months** (which the allocation ledger now
represents properly); transfer fees; and mistakes, where the record must show the truth.
**Any amount differing from `balance_due` requires a short note.**

**Proof visibility — a documented decision.** The screenshot is shown to the affiliate, as
requested by the business, because visible proof removes an entire category of "did you send
it?" messages. An external review noted the risk: a transfer screenshot may expose HBA's
sender name, account details, transaction identifiers, or balance to ~20 external people.
**The business has accepted this risk knowingly.** Mitigations applied regardless: EXIF is
stripped on upload, images are compressed, file size is capped, and proof is served only to
the affiliate it belongs to.

**Storage:** ~20 models × 12 months × ~200KB ≈ **50MB/year**. Free-tier object storage.

---

## 15. Targets

Models publish content on their own social accounts. Sara tracks these externally and records
monthly totals. **Evidence collection remains external for V1.**

- Requirements set per model per month.
- Actuals recorded by `target_recorder` via the bulk grid (§12.2).
- Verification by `affiliate_manager` or `admin` unlocks the base guarantee.
- **Informational** for `commission` and `fixed_plus_commission`; **determines pay** only for
  `base_guarantee`.
- Recording is blocked once a month is `approved` — reopen first.

---

## 16. Notifications, audit, and policy

| Event | Recipient | Channel |
|---|---|---|
| Application submitted | Model | Email |
| New application received | Maintainer | Email + in-platform |
| Application approved | Model | Email with sign-in link |
| Month approved | Model | Email |
| **Month re-approved after a reopen** | Model | **Email, on re-approval only — see below** |
| Payment recorded | Model | Email **with receipt** |
| **Payout destination changed** | Maintainer | **Email + in-platform, immediately** |
| Sync failure, failed job, unattributed code, multi-code hold, stuck reopen | Maintainer | In-platform + email |
| Payroll reminder (configurable, default 5th) | Maintainer | In-platform |

All emails are written through `notification_outbox` in the same transaction as the change
that caused them.

**A reopen sends no email of its own** (ADR 0030). Reopening and re-approving happen back to
back in practice, so a heads-up at reopen only trains the model to skip it and, eventually,
the real one. The existing "Month approved" event covers re-approval — it is an approval,
just not the first one — with two additions for `version > 1`:

- The difference from the previous version, and the written reason (§11.5), rewritten in
  plain language rather than copied from the audit log.
- If the new figure is **lower** than what was already paid, the email is sent **immediately
  on re-approval, before any correction is applied** — there is no transfer to attach the news
  to, and the model will notice nothing in their bank account otherwise. It states which §11.5
  resolution was chosen: *"E£300 will come off next month's payment"* (credit) or *"nothing
  further is needed from you"* (write-off).

**Every model gets email only.** There is no in-platform inbox for them — that channel belongs
to the maintainer. This applies here as everywhere else in this table.

**Business audit trail.** Every mutation: who, what, when, before/after, and reason where
required. Append-only, enforced by trigger. **Sensitive fields are masked** — account numbers
and InstaPay addresses never appear verbatim.

**System and integration logs** are separate from the business audit and surfaced in an
operational health view.

**Commission policy versions.** The rules are versioned and effective-dated with
plain-language text. Every snapshot records the policy version that produced it, so a model
viewing July sees July's rules via an ⓘ control.

---

## 17. Database-enforced invariants

Application code is not the last line of defence. The database enforces:

- No overlapping `compensation_period` rows per affiliate
- No overlapping ownership of the same code across affiliates
- Exactly one `payroll_month` per affiliate per month
- At most one active approved snapshot per payroll month
- Snapshot versions unique and monotonically increasing per month
- `payment_transaction.amount_piastres > 0`
- Sum of allocations for a transaction never exceeds its amount
- Fixed/base amount fields valid only for compatible compensation types
- `house` accounts can never enter payable payroll
- `attributed_order.affiliate_id` immutable once set
- Append-only tables (`payment_*`, `payroll_snapshot`, `audit_event`, `integration_event`)
  reject UPDATE and DELETE via trigger

---

## 18. Migration and cutover

### 18.1 What actually migrates

"No data migrates" was too broad. Shopify can rebuild orders; it cannot rebuild HBA's
business configuration.

| Data | Source |
|---|---|
| Orders and order history | **Rebuild from Shopify** (authoritative) |
| Affiliate identity and contact details | Manual verified entry, or import from current system |
| Discount code ownership history | Current system + Shopify verification |
| Current compensation terms | **Manual verified entry** — must be correct before first payroll |
| Historical compensation terms | **Not migrated.** Historical months show sales only, no commission figure (§11.2) |
| Target history | Decide per month; otherwise historical view states "not available" |
| Payments | **Nothing to migrate** — confirmed no real payments were ever recorded |
| Production / Bosta data | **Do not migrate** |

### 18.2 Cutover

1. Build V1 while the current dashboard is **frozen**.
2. Configure the go-live month; everything prior becomes `historical`.
3. Run the Shopify bulk import (1 Jan 2026 → go-live).
4. Enter affiliates and current compensation terms; verify every code against Shopify.
5. **Verify a known month against manual calculation before opening access.**
6. Switch over. Old dashboard becomes read-only reference.

Backups are verified and retained outside the hosting provider before cutover, and a
documented rollback path exists.

---

## 19. Technical architecture

| Layer | Choice | Rationale |
|---|---|---|
| Backend | **Python + FastAPI** | Chosen by the maintainer so the code stays readable to its owner |
| Frontend | **React** (built to static assets) | Required for the intended interface quality |
| Deployment | **One service** — FastAPI serves the built bundle and runs the worker | Keeps hosting within budget |
| Database | **PostgreSQL**, free tier (Neon or Supabase) | Removes the SQLite single-replica constraint |
| Object storage | Cloudflare R2 or Supabase Storage, free tier | Payment proof |
| Hosting | Railway | Already in use |

`hba-operations-hub` is **not** carried forward as code. Its Shopify sync, webhook handling,
and retry patterns are studied and reimplemented in Python. It is retired at cutover.

**Budget:** $10/month now, with room to grow. One service, free-tier database and storage,
no Redis. At ~20 affiliates performance is a non-issue, freeing every decision to optimise
for clarity.

**Non-functional:** model-facing data never exposes customer PII; permissions enforced
server-side; CSRF protection; CSV formula neutralisation on export; financial calculation,
attribution, state transitions, and permission boundaries all require tests.

---

## 20. Build sequence

V1 is a complete financial application, not a dashboard refresh. It is therefore released in
**three gated stages**, so HBA receives working value before every convenience exists.

### V1A — Financial core (admin only)

| Phase | Delivers |
|---|---|
| 1 | Skeleton, Postgres schema, identity spine, roles, audit, deploy pipeline |
| 2 | Shopify: two-tier storage, bulk import, webhooks, durability, code verification |
| 3 | Affiliate registry, code periods, compensation terms |
| 4 | Commission engine, commission states, rounding |
| 5 | Targets and bulk entry grid |
| 6 | Payroll lifecycle, approval, blockers, carry-forward, reopen |
| 7 | Payment ledger, proof upload, allocations, credits and write-offs |

**Gate: run one full month of real payroll and verify it against manual calculation.**

### V1B — Affiliate self-service

| Phase | Delivers |
|---|---|
| 8 | Affiliate accounts, onboarding flow, invitations, payout destinations |
| 9 | Affiliate portal: earnings, orders, targets, payment history, receipts |

**Gate: one month where models see their own figures and are paid through the platform.**

### V1C — Polish

| Phase | Delivers |
|---|---|
| 10 | Notifications, policy viewer, operational health, reporting, UX polish |

**This specification is the umbrella; each phase gets its own implementation plan**, written
when that phase begins. Every phase leaves the system working and deployable.

---

## 21. Open questions

1. **Go-live month** — not yet chosen.
2. **InstaPay guide screenshots** — required from the business.
3. **When Boda and Sara receive accounts** — confirmed post-launch, trigger undecided.
4. **InstaPay deep-link behaviour** — must be tested across devices before Phase 8.
