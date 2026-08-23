# Known limits and foreseeable failures

Every system has boundaries. The dangerous ones are the boundaries nobody wrote
down, because they are met years later by someone who has no idea they exist and
who experiences them as "it just stopped working".

This register lists what will eventually break, what happens when it does, and
what to do about it. **A limit belongs here even when it is currently
impossible to reach** — the point is that the next person can find it.

**When adding a limit, say what the failure looks like from outside.** "The
database fills up" is not useful. "Order sync stops and the operational view
shows failed jobs with a disk-full error" is.

---

## Legend

| Severity | Meaning |
|---|---|
| 🔴 | Will happen on a known timescale. Needs a plan. |
| 🟠 | Will happen if the business grows or an assumption changes. |
| 🟢 | Practically unreachable. Recorded so nobody re-derives it. |

An entry marked **(planned)** describes a component that is designed but not yet
built. It is written down now so the limit is designed in rather than discovered
later.

---

## Storage and growth

### 🔴 `integration_event` grows forever and cannot be pruned *(planned)*

**The limit.** Every inbound webhook writes an immutable receipt. The table is
append-only by design (ADR 0008), so `DELETE` and `TRUNCATE` are refused —
including to us. Whatever it stores, it stores permanently.

**Why that matters.** The obvious design stores the full webhook body as JSONB.
Roughly 30,000 orders a year, around three events each, payloads of a few
kilobytes: **on the order of 270 MB a year**, against a free-tier Postgres
offering 500 MB to 1 GB.

**What that failure would look like.** Somewhere in year two or three, writes
begin failing with a disk-full error. Webhooks return 500, Shopify retries and
eventually gives up, and orders quietly stop arriving. The operational view
fills with failed jobs. Nothing names the cause.

**Decision, applied when the table is built in Phase 2 Task 3.** Store a payload
*digest* and the handful of fields actually used — not the whole body. The
receipt's job is to prove an event arrived and to deduplicate it; it is not an
archive of Shopify's JSON. That takes the figure from hundreds of megabytes a
year to a few.

**If the ceiling is met anyway.** Archive old rows to object storage and drop
them through a deliberate, reviewed migration that temporarily disables the
trigger. That is a conscious act requiring a migration and a review — which is
the point. No stray script can do it.

### 🟠 Succeeded background jobs accumulate *(planned)*

**The limit.** `background_job` — Phase 2 Task 3 — keeps every completed job.
Nothing prunes them.

**What failure looks like.** Gradual slowdown of the lease query, then the same
disk pressure as above. Much slower than `integration_event` — rows are small
— but unbounded.

**Mitigation.** A periodic prune of `succeeded` jobs older than, say, 30 days.
**Failed jobs are never pruned automatically:** they are the record that work
did not happen (ADR 0009).

### 🟢 `order_index` growth

About 150 bytes per order, roughly 30,000 orders a year: **around 4.5 MB a
year.** Decades of headroom on a free tier. Recorded so nobody "optimises" it
by discarding unattributed orders, which would break code registration and the
unregistered-code alert (ADR 0010).

### 🟠 Payment proof images *(planned)*

~20 affiliates × 12 months × ~200 KB ≈ **50 MB a year**, on free-tier object
storage. Fine at current scale; revisit if affiliate numbers grow tenfold.

---

## Numeric limits

### 🟢 Money columns

Piastres in `bigint`. Maximum **E£92,233,720,368,547,760 in a single field** —
not cumulative, not a count of orders. Unreachable.

Recorded because the *previous* type matters: a 32-bit `integer` would cap a
single order at **E£21,474,836.47**. A test stores a E£20 million order so that
narrowing the column later fails loudly instead of silently truncating.

### 🟢 Commission rate

Basis points, validated to `0 < rate <= 10000` (0% exclusive to 100%
inclusive). A rate above 100% is refused rather than clamped.

### 🟢 Commission numerator

`base_piastres × rate_bp` is computed in Python's arbitrary-precision integers
and never stored, so it cannot overflow. It becomes `Decimal` only at the final
division (ADR 0003).

### 🟠 String column lengths

| Column | Limit | Fails when |
|---|---|---|
| `order_index.order_number` | 40 | Shopify order names are far shorter; safe |
| `discount_codes[]` element | 120 | A code longer than 120 characters |
| `user_account.email` | 320 | The RFC maximum; safe |
| `auth_session.user_agent` | 400 | **Truncated deliberately**, never rejected — a hostile header must not break sign-in |
| `background_job.last_error` *(planned)* | 2000 | **Truncated deliberately** — a huge traceback must not fail the failure-recording path |

The two truncations are the interesting ones: both exist so that an unusual
input degrades instead of breaking something more important.

---

## Time

### 🟠 Egypt changes its DST policy again

**The limit.** The business month is derived in `Africa/Cairo` (ADR 0005).
Egypt abolished DST in 2015 and reinstated it in 2023. If it changes again,
every month boundary moves.

**What failure looks like.** Orders near month end file into the wrong payroll
month. Nothing errors — the totals are simply wrong, and only by one order here
and there, which is exactly the kind of discrepancy nobody catches.

**Mitigation in place.** `test_egypt_still_observes_summer_time` asserts the
2026 offsets. **This test failing is a signal to review, not a bug to silence.**
It also depends on `tzdata` being current, so a very stale container image would
carry stale rules.

### 🟠 The Shopify API version is sunset

**The limit.** The API version is pinned (`2026-07`). Shopify supports a version
for roughly a year, then removes it.

**What failure looks like.** Every Shopify call starts returning errors on a date
Shopify published long in advance and nobody was watching for.

**Mitigation.** Treat the pinned version as an expiring dependency. Bump it
deliberately, test, and deploy — never let it drift unpinned, which trades a
predictable failure for an unpredictable one.

### 🟢 Month arithmetic

`YYYY-MM` strings with integer arithmetic; valid to year 9999.

---

## External services

### 🟠 Shopify rate limiting

Cost-based, not request-count. The client retries `THROTTLED` with exponential
backoff, up to four attempts. A sustained overload — a large reconciliation
running alongside a bulk import — exhausts the retries and fails the job
visibly. Historical loading uses the Bulk Operations API specifically to avoid
this.

### 🟠 Shopify credentials rotated or scopes revoked

Token exchange fails, every sync job fails visibly, and the operational view
shows it. The client reports the scopes Shopify grants, so a **missing scope is
named rather than surfacing as an opaque permission error** (ADR 0015).

### 🟠 The webhook secret changes *(planned)*

Every webhook fails signature verification and is rejected with 401. **Nothing
is recorded for a rejected webhook**, deliberately — otherwise anyone could fill
the event table. Orders would then arrive only via the reconciliation sweep:
correct, but delayed, and with no loud signal. Worth an alert if the rejection
rate rises.

### 🟢 Shopify deletes an order *(planned)*

Order sync must treat a missing order as absence, not failure — returning
nothing rather than raising. A deleted order is not an error, and treating it as
one would retry forever.

---

## Concurrency and process

### 🟠 More than one replica *(planned)*

The worker runs inside the API process (ADR 0009). Leasing uses
`FOR UPDATE SKIP LOCKED`, so a second replica is *safe* — two workers take
different jobs. But the platform is currently sized and priced for one, and
scheduled work would run twice as often.

### 🟢 A worker crashes mid-job *(planned)*

The lease expires and the job is picked up again. Handlers must therefore be
idempotent, which order indexing is by construction.

### 🟠 A handler that is not idempotent *(planned)*

Every handler must either upsert by Shopify id or be read-only. Recorded because
it is the assumption a future handler could break silently: re-running would
double-apply, and lease expiry makes re-running normal rather than exceptional.

---

## Business rules with deliberate exposure

These are not bugs. They are accepted costs, recorded so nobody "fixes" them.

| Exposure | Where | ADR |
|---|---|---|
| Commission paid on an order returned after approval | Up to the 10-day window | 0012 |
| Sub-pound rounding difference absorbed on every payout | ~E£90/year programme-wide | 0004 |
| One role sets, records and verifies targets | Releases base guarantees unchecked | 0018 |
| Payment screenshots visible to affiliates | May expose HBA banking details | 0017 |
| Manual out-of-window exchanges are invisible | Created in Bosta only, never reach Shopify | Spec §9.4 |

---

## How to use this file

**When something breaks unexpectedly, read this first.** If the failure is
here, the fix is here too.

**When it is not here, add it** — with what it looked like from outside, not
only what the cause turned out to be. The next person will meet the symptom
before they meet the cause.
