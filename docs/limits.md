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

### 🟠 Succeeded background jobs accumulate

**The limit.** `background_job` keeps every completed job.

**Handled:** `prune_succeeded_jobs` runs daily from the schedule, removing
succeeded jobs older than 30 days. **Failed jobs are never pruned** — they are
the record that work did not happen.

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

**A 32-bit `integer` would cap a single field at E£21,474,836.47.** That is fine
for a per-order column and *not* fine for an aggregate: a programme-wide annual
total passes it in the first year. One money type is used everywhere so the
distinction never has to be got right — measured at 2 MB over five years
(ADR 0019).

Overflow is loud, not silent. Postgres raises `integer out of range` and refuses
the write; it does not wrap or truncate. **The symptom would be an order failing
to record, not a wrong number.** A test stores a E£20 million order so that
narrowing the column later fails in the test suite rather than in production.

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
| `background_job.last_error` | 2000 | **Truncated deliberately** — a huge traceback must not fail the failure-recording path |

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

### 🟠 The webhook secret changes or goes missing

Every webhook fails signature verification and is rejected with 401. **Nothing
is recorded for a rejected webhook**, deliberately — otherwise anyone could fill
the append-only event table. Orders would then arrive only via the
reconciliation sweep: correct, but delayed.

**Now signalled** rather than silent: each rejection reports `webhook_rejected`,
and `/api/health/ready` reports `shopify.webhooks_configured` so a missing
secret is visible without waiting for a delivery to fail.

### 🟢 Shopify deletes an order

`sync_one_order` returns nothing rather than raising, and reports
`order_not_found`. A deleted order is not an error, and treating it as one would
retry forever against something that will never come back.

---

## Concurrency and process

### 🟠 More than one replica

The worker runs inside the API process (ADR 0009). Leasing uses
`FOR UPDATE SKIP LOCKED`, so a second replica is *safe* — two workers take
different jobs. But the platform is currently sized and priced for one, and
scheduled work would run twice as often.

### 🟢 A worker crashes mid-job

The lease expires after 60 seconds and the job is picked up again. Handlers must
therefore be idempotent, which order indexing is by construction.

**A deploy does this every time.** The worker is cancelled with the API, so a job
in flight is abandoned and re-run up to a minute later. Correct, but it means the
`lease_reclaimed` signal is expected around every restart.

### 🟠 A failure that retrying cannot fix

**The limit.** The queue retries everything five times over about eight minutes.
For a missing credential, an ungranted scope, or a payload naming nothing, all
five fail identically — delaying the signal and burying the one line that
explains it under four copies.

**Handled:** a handler raises `PermanentFailure` and the job fails at once, with
`attempts` set to the maximum so it is not leased again.

**The risk is the reverse mistake.** Classifying a *temporary* failure as
permanent means a Shopify blip permanently fails an order that would have
synced on the next attempt. `PermanentFailure` is for causes only a person can
resolve. Everything else — timeouts, throttling, network errors — must stay
retryable.

### 🟠 The bulk import outlives its lease

**The limit.** Ingesting a year of orders can take longer than the 60-second
lease. The lease then expires while the job is still running, and another
worker may take it.

**Why it is survivable now:** there is one worker, running one job at a time,
so nothing else can claim it. And the ingest is idempotent, so a second run
would waste time rather than double anything.

**What would change that:** a second replica. Then two workers could ingest the
same export at once — wasteful, not wrong, but `lease_reclaimed` would fire and
the import would take twice as long. Raise the lease for this job before adding
a replica.

### 🟠 Recurring work stops silently

**The limit.** Nothing external triggers the reconciliation sweep or the prune.
They are queued by the worker itself, on a timer, and **if the worker stops so
do they** — with no error, because nothing failed. Orders would still arrive by
webhook, so the dashboard would look normal while the safety net was gone.

**What failure looks like:** no `shopify_reconcile` rows appearing in
`background_job` over a day. That is the thing to check when orders seem to be
going missing.

**Why it is built this way:** a scheduler process is a second thing to deploy,
pay for, and monitor. `docs/limits.md` records the trade rather than the
schedule pretending to be more reliable than it is.

### 🟠 A recurring job that fails permanently buries the next real failure

**The limit.** A scheduled job whose cause cannot resolve itself fails once per
interval, for ever, with an identical message. Each failure is correct and each
is kept — failed jobs are never pruned on a timer — so they accumulate.

**Seen in production on day one.** `shopify_reconcile` ran every 30 minutes for
19 hours before Shopify credentials were set, leaving **37 identical rows**
saying `Shopify is not configured`. It healed itself on the next cycle once the
credentials arrived, which is the behaviour we want — but the residue is
permanent.

**What failure looks like.** `/api/operations/failed-jobs` returns 100 rows of
one resolved problem, and `jobs.failed` reads alarmingly high for ever. **The
next genuinely different failure is invisible inside it.**

**Why it is not fixed by stopping the schedule.** Giving up after N identical
failures would mean the sweep never resumes once the cause is fixed — trading a
noisy signal for a silent one, which is the worse of the two.

*What to do:* clear a resolved incident deliberately. It is a human act, not a
timer:

```sql
delete from background_job
where status = 'failed' and last_error like '%not configured%';
```

### 🟠 Payout destination changes are stored safely but not yet guarded

**The limit.** §6.4 treats repointing a payout destination as a money-impacting
change and requires five things. Phase 3 builds two of them — append-only
storage with supersession, and masking so no raw account number reaches an
audit record.

**Not yet built:** the affiliate re-entering their password, and the maintainer
being notified immediately. Both need the affiliate portal and the notification
outbox, which arrive in Phase 8.

**Half-built:** the payment-screen warning. `changed_recently()` answers *when
the destination last changed, if it changed lately* — the fact the warning needs
— and deliberately returns nothing for an affiliate's *first* destination,
because that is not a redirection. **Nothing displays it yet.** The payment
screen is Phase 7.

**Why this matters now.** Until then, **the protection against a compromised
account silently redirecting a payout is that affiliates cannot reach the
platform at all.** That holds only while the portal does not exist. Phase 8
must not ship self-service without these, or it removes the one thing currently
preventing it.

### 🟠 Orders placed before a code was registered stay orphaned

**The limit.** §9.2 says an unattributed order may be attached when its code is
registered for the first time. **That is not built.** Attaching an order means
writing `attributed_order`, which arrives in Phase 4, so the backfill goes with
it.

**What failure looks like.** A model's sales from before her code was set up
never appear anywhere and never pay. Nothing errors — the orders are indexed
and simply belong to nobody.

**What exists instead.** `/api/operations/unregistered-codes` reports every code
whose orders are unowned, **and which months are unowned**, so the gap is
visible and registering the code starts from the right month rather than
leaving one.

*What to do until Phase 4:* check that report before approving an affiliate. If
her code already has orders, register it from the earliest month listed, not
from today — otherwise the backfill, when it arrives, has a gap to find that
nobody recorded.

### 🟠 A model's login email is the one she was invited at, not one she types

**The limit.** `accept_invitation` creates the account with the **invitation's**
email. The application form (Phase 8) collects an email from the model, but that
is a *contact detail* on her profile - it does not become her login.

**Why it is this way.** The invitation link was sent to that address and
approved against it. Letting the form silently repoint the login would mean the
person you invited is not necessarily the person who ends up with the account.

**What failure looks like.** She types the email she actually uses, is approved,
and then cannot sign in - because the login is the address you invited, which
may be one she rarely checks. Nothing errors; she just cannot get in.

*What to do:* the form shows the invited address, and correcting it is a
maintainer action - see the affiliate edit endpoint. That keeps the change
deliberate and audited rather than silent.

### 🟠 The delivery signal can die without saying so

**The limit.** ADR 0012 makes an order `earned` — the only state that pays — when it is
**delivered**. That fact is read from Shopify (ADR 0023), where it is written by whatever
integration reports the shipment's progress. HBA has confirmed the status does update.

Nothing in Shopify announces when that stops.

**What failure looks like.** The integration's token expires, or an app is disabled, or
somebody changes a setting. Orders keep arriving and keep shipping, and none of them ever
reaches delivered. Every affiliate's month then calculates to **zero earned**, correctly and
silently — it looks exactly like a month with no sales. The first person to notice is a model
asking why she was not paid.

This is the same failure shape as the auto-cancel automation in §9.1: protection that lives
outside the codebase and disappears without a symptom.

**What exists instead.** Nothing yet — recorded before the code that depends on it.

- Phase 4 Task 2 builds `GET /api/operations/order-facts`, which counts the delivery signals
  present across the orders already indexed. It says which fulfilment statuses the live shop
  actually reports and on how many orders — the same instrument as `/shopify-scopes`, and the
  thing that turns "Shopify updates the status" into a number.
- The watch itself: **orders still shipping, none reaching delivered** for an extended period
  is an anomaly the maintainer sees. Sized to the failure rather than to a second courier
  integration (ADR 0019, ADR 0023).

*What to do:* read that report before believing any earnings figure, and read it again if a
month comes out unexpectedly low. A zero month is not evidence of no sales.

**A related trap, worth keeping separate.** *Shipped* is not *delivered*. If the report shows
the live shop only ever reaches `FULFILLED`, earning on that instead would pay commission on
every parcel a customer refuses at the door — which for cash-on-delivery through Bosta is the
precise loss ADR 0012 was written to stop. That would be a decision about real money and
belongs to the business, not to whoever is writing code that week.

### 🟠 A code created before the switch cannot be handed over

**The limit.** `retire_and_replace` ends the old code the month **before** the
new one starts, and takes the new one's start month from **when Shopify created
it**. Those are the same date only because HBA creates a code at the moment of
switching a model onto it. Nothing enforces that habit.

**What failure looks like.** `NEW10` is created on Shopify in July, but she
keeps earning on `OLD10` through August. Switching her in September derives a
July start, which ends `OLD10` in June — so her July and August `OLD10` orders
fall outside every period she owns. Two months of her sales belong to nobody.
Nothing errors, nothing recalculates, and the only visible trace is a smaller
payout than she expects.

The mirror case is as bad: if somebody else used `NEW10` in those months, those
orders become hers.

**What exists instead.** The handover is **refused** when it would strand
anything. Before ending the old period, `_orders_on_or_after` counts orders on
the old code in the new code's start month or later; any at all and the request
fails with a 400 naming the code, the count, and this file.

The check is on the *harm*, not the calendar. A code created early that nobody
used strands nothing, so it is allowed — sizing the guard to the failure rather
than to the shape it usually arrives in (ADR 0019).

**What is missing.** A way to say **which month she actually moved over**,
separate from when the code was created, with the orders the new code already
accumulated shown before the decision is confirmed. Deliberately not built:
HBA does not work this way today, and a handover month that can be typed is a
handover month that can be typed wrong — which silently re-attributes real
money in both directions.

*What to do if the refusal appears:* do not work around it by retiring the code
by hand. It means the two dates genuinely disagree, and someone has to decide
which months belong to which code. Raise it, and build the feature above.

### 🔴 Correcting pay terms is not yet blocked by payroll

**The limit.** A mistyped rate, salary or base amount can be corrected, which
it must be - until now the only fix was editing the database by hand. But
`assert_correctable` currently blocks nothing, because **payroll does not exist
until Phase 6** and no month can yet be approved or paid.

**Why it is safe today.** Nothing downstream consumes pay terms. Correcting
them changes a number nobody has been paid against.

**What failure looks like once payroll exists.** Somebody corrects a rate for a
month already approved and paid. The platform then reports a different figure
from the money that actually left the account - and the first sign is a model
asking why her payslip changed. Nothing errors.

**Phase 6 must wire the check into `assert_correctable`** in
`app/services/compensation.py`: a period covering any month with an approved
payroll snapshot is refused, and correcting it becomes a reopen-and-reconcile,
not an edit. The function exists and is called from both correction and
closing precisely so there is one place to fill in.

### 🟠 A handler that is not idempotent

Every handler must either upsert by Shopify id or be read-only, and must never
commit the session it is given — the worker owns that. Both rules are stated in
`register_handler`'s docstring and neither is enforced by anything.

Recorded because this is the assumption a future handler could break silently:
re-running would double-apply, and lease expiry makes re-running normal rather
than exceptional.

---

## Prevented failures, and what they mean

These do not stop anything. Each is a failure the platform absorbed, reported
so that the run-up to a real breakage is legible instead of invisible.

They appear in the logs as a single greppable line:

```
ANOMALY job_gave_up attempts=5 job_id=412 kind='sync_order' last_error='...'
```

The names below are the catalogue in `app/core/signals.py`. **A test fails if a
name exists there without an entry here**, because a log line nobody can look up
is barely better than no log line.

### `job_gave_up`

A job exhausted its five attempts. **The work did not happen and will not be
retried without someone acting.** The most important line in this list.

*What to do:* find the job by id — it is still in `background_job`, marked
`failed`, with its payload and last error. Fix the cause, then set it back to
`pending` to re-run it.

### `lease_reclaimed`

A job was found with an expired lease: the worker holding it died mid-flight.
Reclaiming it is the queue working correctly.

*What to do:* nothing, once. A steady stream means workers are dying — check
memory limits and deploy restarts, since a restart mid-job produces this every
time.

### `no_handler`

A job was queued for a kind nothing knows how to handle. **It fails immediately
rather than retrying** — five attempts over eight minutes cannot conjure a
handler, and would only delay the signal.

Almost always a half-finished deploy: something enqueues work the running code
does not implement, or a handler's module stopped being imported so its
`@register_handler` never ran.

*What to do:* check that the module defining that kind is imported at startup —
see `app/main.py`. The job is still in `background_job` with its payload; set it
back to `pending` once the handler exists.

### `worker_iteration_failed`

The worker loop itself failed — not a job failing, which is ordinary and handled
inside `run_one`, but the **queue being unreachable**. The worker survives and
tries again after the poll interval.

*What to do:* one of these around a deploy or a database restart is expected. A
continuous stream means the database is down or the connection pool is
exhausted, and **no background work is happening at all** — orders will not be
syncing.

### `order_not_found`

We asked Shopify for an order and it has no such order. Not an error - an order
can be deleted between a webhook firing and the job running - so the job
succeeds rather than retrying forever against something that will never return.

**This is the answer to "why is this order not on the dashboard?"** Without it
the order simply would not be there, with nothing anywhere explaining why.

*What to do:* nothing if the order really was deleted. If it exists in Shopify
and this still fires, the id being asked for is wrong - check the webhook
receipt's `entity_id` against the real order, particularly for a refund, where
the payload's `id` is the refund and the order is in `order_id`.

### `import_line_skipped`

Lines in a bulk export that could not be read or understood. The rest of the
import went ahead; **those orders are simply not in it**, which is why this is
reported rather than counted quietly.

*What to do:* compare `written` against Shopify's own `objectCount` in the
import log line. A handful of skips is usually child objects. A large number
means the export's shape is not what `normalise_order` expects — likely a
Shopify API version change.

### `import_empty`

A bulk import completed having matched no orders at all.

*What to do:* check the `since` date, and that the app has `read_all_orders` —
plain `read_orders` reaches back only 60 days, so a January import against it
returns nothing and reports exactly this.

### `reconcile_truncated`

A sweep stopped before reading its whole window: either it hit the page limit,
or Shopify claimed another page and named no cursor. **The tail of the window
went unchecked**, so an order updated in it may not be indexed.

*What to do:* the next sweep covers an overlapping window, so a single
occurrence usually self-corrects. Repeated `page limit` means the window holds
more orders than 200 pages of 50 — shorten `since_hours` or raise `PAGE_SIZE`.

### `schedule_top_up_failed`

The worker could not queue its recurring work. **Ordinary jobs keep running** —
webhooks still sync orders — but the reconciliation sweep and the prune do not
until this clears.

*What to do:* one of these around a database restart is expected; it retries a
minute later. A continuous stream means the safety net is off while everything
else looks healthy, which is the combination worth an alert.

### `webhook_rejected`

A webhook failed signature verification and was refused with a 401. **Nothing is
recorded for it** — `integration_event` is append-only and cannot be pruned, so
anyone able to write to it could fill the database permanently. This log line is
the only trace the request ever existed, and it deliberately contains nothing
from the body, which is unverified input.

*What to do:* check `secret_configured` in the line. If it is `False`, the
platform has no webhook secret and **is rejecting every delivery** — orders are
not arriving. If it is `True`, either Shopify's secret was rotated without
updating `SHOPIFY_WEBHOOK_SECRET`, or something other than Shopify is posting to
the endpoint. `/api/health/ready` reports `webhooks_configured` for the first
case.

Occasional single rejections from internet noise are normal for a public
endpoint. A steady stream that coincides with orders going missing is not.

### `webhook_unusable`

A webhook verified and was recorded, but nothing could be done with it: an order
topic whose payload does not name an order.

*What to do:* this means the payload is not the shape the code assumes — either
Shopify changed it, or a topic was subscribed to that does not carry an order.
The receipt is in `integration_event` with its topic; compare against
`ORDER_TOPICS` and `order_id_from` in `app/services/shopify/webhooks.py`.

### `event_content_changed`

A webhook arrived twice under the same id carrying **different content**.
Deduplication ignored the second, which is correct, but the sender reusing an id
means an assumption about it is wrong.

*What to do:* compare the two digests in the log line. If this recurs, the
idempotency key for that source is not actually unique and needs rethinking.

### `error_truncated`

A failure message exceeded 2,000 characters and was cut down. The failure is
still recorded; part of the detail is not.

*What to do:* nothing usually. Repeatedly truncating the same job means the
useful part of the message may be past the cut — check the raw exception.

### `work_deduplicated`

Work was queued for something already queued, and was absorbed. **Expected in
ordinary operation** — Shopify sends create, update and paid for one order
within seconds.

*What to do:* nothing, unless the rate is high, which means a sender is looping.

---

### 🟠 Logging can be switched off silently *(fixed, guarded)*

**The limit.** `logging.config.fileConfig` defaults to
`disable_existing_loggers=True`. Alembic's `env.py` calls it, so running a
migration inside a process that has already imported the application switches
off **every logger created before that point** — permanently, without an error.

**What failure looks like.** The logs stop. Nothing else changes. Every
prevented failure above becomes invisible, which is the exact opposite of what
this file exists for.

**How close this came.** Production runs `alembic upgrade head` as a *separate
process* before uvicorn starts (`nixpacks.toml`), so the application's own
loggers were never affected. **The trap was latent, not live** — it fired only in
the test process, which imports the app and then migrates.

That is worth stating plainly: a single change to run migrations in-process at
startup — a reasonable-looking simplification — would have silenced production
logging with no other symptom.

**Fixed** in `migrations/env.py`, which now passes
`disable_existing_loggers=False`, and guarded by
`test_running_migrations_does_not_disable_application_logging`.

Recorded because the same trap applies to any future `fileConfig` or
`dictConfig` call, wherever it runs.

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
