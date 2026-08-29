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

### 🟢 Orders placed before a code was registered *(fixed, Phase 4 Task 6)*

**The limit, as it stood.** §9.2 says an unattributed order may be attached when
its code is registered for the first time. That was not built, because attaching
means writing `attributed_order` and the table did not exist until Phase 4.

**Why it mattered.** Models arrive at HBA with codes **already live and already
selling** (ADR 0022). Everything a code earned before somebody typed it into the
platform belonged to nobody, permanently, and nothing said so.

**Fixed.** Registering a code queues a background job that finds every indexed
order using it, in the months they own, and attaches the unattributed ones. Each
goes through the same `attribute_order` as a live order, so a backfilled month is
worth the same as one that arrived by webhook.

All three paths that create ownership queue it — `register_code`,
`replace_code` (a corrected typo is a different code with its own history), and
`retire_and_replace`. A path that creates ownership and forgets to backfill
leaves those orders belonging to nobody, which is the whole failure this entry
described.

**What it will not do.** Attach an order that already has an owner. §9.2 is
explicit — this assigns an orphan, it does not move an order — so a mistyped
registration cannot quietly take a sale from the model who was paid for it. The
job reports and carries on rather than failing on a row it was never entitled to
touch.

*Still true:* `/api/operations/unregistered-codes` remains the report for codes
that belong to nobody at all. Nothing backfills those, because there is no one
to backfill them to.

### 🟠 A model's login email is the one they were invited at, not one they type

**The limit.** `accept_invitation` creates the account with the **invitation's**
email. The application form (Phase 8) collects an email from the model, but that
is a *contact detail* on their profile - it does not become their login.

**Why it is this way.** The invitation link was sent to that address and
approved against it. Letting the form silently repoint the login would mean the
person you invited is not necessarily the person who ends up with the account.

**What failure looks like.** They type the email they actually uses, is approved,
and then cannot sign in - because the login is the address you invited, which
may be one they rarely checks. Nothing errors; they just cannot get in.

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
asking why they were not paid.

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

### 🟠 Orders indexed before Task 2b know nothing about delivery

**The limit.** Delivery, return and refund fields were never requested until
Phase 4 Task 2b. The migration adds the columns; it cannot invent the data. All
**529 orders already indexed carry `delivery_state = NULL`**, and an order with
no delivery state never earns.

**What failure looks like.** A model's January to August sales show as pending
for ever. Their month calculates to zero earned, correctly, and it looks exactly
like a month with no sales — the same symptom as a dead delivery signal, from a
completely different cause.

**What exists instead.** The reconciliation sweep refreshes recent orders on its
own, so the window it covers heals without anyone doing anything. Everything
older needs `POST /api/operations/start-import` run again — it is idempotent,
upserts by Shopify order id, and `first_seen_at` is deliberately excluded from
the update so re-importing does not rewrite history.

*What to do before the first real payroll:* re-run the import from
`2026-01-01`, then check `GET /api/operations/order-facts` — `already_indexed`
will show delivery states once they are populated. **A month of zeroes is not
evidence of no sales.**

### 🟠 An order half delivered and half failed resolves neither way

**The limit.** A split shipment where one parcel arrives and another fails
reduces to `in_flight`, not to delivered or failed. It stays there.

**What failure looks like.** The order never earns and never voids. It sits in
the model's pending column indefinitely, and nothing reports it.

**Why it is deliberate.** Both alternatives are wrong in a way that costs
somebody money: calling it delivered pays commission on goods that came back,
and calling it failed refuses commission on goods they genuinely sold. The
honest answer is that a person has to decide, and the honest state until then is
*not yet*.

**What is missing.** Nothing lists these orders. Splitting the commission base
across parcels would be the real fix and is not built — it needs line-item
detail this platform does not store, for a case that has not been observed once
in HBA's live data.

*What to do if one appears:* it will show as an order pending long after its
neighbours settled. Decide it by hand until there are enough to justify
building for.

### 🟠 An order stuck at "attempted delivery" is invisible

**The limit.** `ATTEMPTED_DELIVERY` is treated as still in flight, because
Bosta retries and most of those parcels do land. It was **10 of 50** orders in
the live sample — one in five.

If a parcel is attempted, refused, and Shopify is never moved to
`NOT_DELIVERED`, the order stays pending for ever. It costs nobody money —
pending pays nothing — but the model sees it in their pending column indefinitely
and eventually asks about it.

**What failure looks like.** Not a wrong number. A number that never becomes
right, and a question nobody can answer from the dashboard.

**What exists instead.** Nothing yet. The natural fix is a report of orders
pending well past the point their neighbours settled, which is also what catches
the split-shipment case above. Worth building once there is a month of real data
to size the threshold from, rather than guessing at one now (ADR 0019).

### 🟠 Nobody has explained any of this to the people using it

**The limit.** The platform is full of ideas a model has never met — carried
forward, earned versus pending, why a returned order still shows in a month they
were paid for, why their sales total and their payment are different numbers. **None
of it is explained anywhere they can reach.** The same applies to the team: an
invited `target_recorder` lands on a bulk grid with no idea what verification
unlocks or why approval is blocked.

**What failure looks like.** Not a wrong number — the same question, asked by
every model, every month, answered by hand each time. Support load that grows
linearly with the roster, and a quiet loss of trust: a figure they cannot explain
is a figure they do not believe.

**What exists in the design already.** §16 specifies **commission policy
versions** — the rules written in plain language, effective-dated, with every
snapshot recording which version produced it, so a model viewing July sees
July's rules through an ⓘ control. That is stronger than a glossary, because it
answers *"what were the rules when I earned this?"* rather than *"what are the
rules generally?"* — and those diverge the moment a rate changes.

**What is still missing, and is Phase 10 work:**

- The plain-language text itself. Versioned rules with nothing written in them
  is a table, not an explanation.
- **Wording that removes the need to look anything up.** If a label needs a
  glossary, the label is wrong. *"Carried forward"* is jargon; *"paid in your
  September payment"* is not. A glossary is a patch over vocabulary nobody
  chose.
- **Settlement labelling per order** — which payroll actually paid each order.
  Without it a model reconciling a month by hand cannot arrive at their own
  payment figure, and this is the single largest source of the questions above.
  The mechanism is `attributed_order.settled_in_snapshot_id`, built in Phase 6.
- **Team onboarding.** A first-login walkthrough was considered. Cheaper and
  more durable: blockers and states that explain themselves where they appear
  (*"Approval blocked: Nour's target is recorded but not verified"*), which
  §11.3 already requires. A walkthrough is read once and forgotten; an
  explanation at the point of confusion is read every time it is needed.

*Recorded now because the decisions that make it possible are being taken now* —
what a month total means, what an order line carries. Deferring the writing is
fine. Deferring the data it needs is not.

### 🔴 Shopify's refund figures do not say what HBA actually refunded

**The limit.** The money recorded against a return in Shopify is not what the
customer received, and sometimes nothing is recorded at all. Confirmed by HBA,
25 August 2026:

- **Return shipping is deducted from the refund.** A customer returning E£600 of
  goods receives E£480 — the fee is E£120 today and moves with the currency.
- **Exchanges are sometimes settled outside E-stebdal**, the request closed by
  hand, and the order left on Shopify still saying a refund is owed.
- **A refund is not always recorded on Shopify** at all.
- **A partial return can void an order-level discount.** Returning one of four
  items removes the 4-plus-items automatic 20%, and the whole order is
  recalculated at full price before the refund is worked out.

**What failure looks like.** Any commission rule derived from "how much was
refunded" is derived from a number that is sometimes wrong and sometimes
absent. It would not fail loudly — it would pay slightly wrong amounts,
indefinitely, and reconcile against nothing.

**What is decided instead.** The base is expressed in **goods, not money**:

> Commission base after a return = the value of the products the customer kept.

**Read directly, never by subtraction.** An earlier version of this rule
computed it as *order total minus returned goods* — which inherits every
adjustment made to that total: return shipping, and the manual balance
corrections HBA does by hand. HBA rejected it, correctly. Summing the product
lines touches none of that.

Shopify's `LineItem.currentQuantity` is the quantity minus what was refunded —
literally what the customer kept — and `discountedUnitPriceSet` is the price they
paid after their code, so a E£1,000 jacket on a 10% code reads as E£900 with
nothing configured anywhere. Jacket kept, pants returned, base **E£900**.

The E£120 return fee is HBA's cost of handling a return, not the model's, and it
cannot reach the figure because nothing in the calculation ever looks at the
order total. Probed by `kept_items`, which also cross-checks the line sums
against the order subtotal on ordinary orders — if they already agree, the
change is invisible where nothing was returned and correct where something was.

**What is still open.** Deciding *which* products the customer kept requires
telling an exchange from a plain return, and E-stebdal opens an identical
Shopify return for both. Since ADR 0024 they resolve to **opposite** outcomes —
an exchange finalises the order at the full base, a plain return reduces it — so
this is not something to infer.

**Shopify refused to answer it.** `GET /api/operations/order-facts` probed
`Order.returns` in three shapes on 25 August 2026 and got the same reply to all
three: **"Access denied for returns field."** That is a scope, not a missing
feature — `read_returns` is not granted. Two ways forward:

| Option | Cost | Risk |
|---|---|---|
| Grant `read_returns` | A scope change and an app release — the same dance `read_discounts` needed | None once granted. `exchangeLineItems` is structured data that cannot drift. |
| Read E-stebdal's **order tags** | Nothing. `tags` is readable with `read_orders`, already held. | A tag is a convention. Renaming it, or one untagged return, silently breaks the rule. |

The tags path is probed by `estebdal_tags`, which reports which tags appear
**only** on orders with a return — a tag on every order discriminates nothing —
and counts **returns carrying no tag at all**, because that number is what
decides whether the scheme works. Run it with `?sample_size=250`: returns are
about one order in eight and a sample of 50 recent orders showed only two.

**Recommendation: grant `read_returns` anyway.** Tags are worth reading if they
already exist, but a convention that silently stops being followed is exactly
the failure shape this register keeps finding, and this one would pay the wrong
amount rather than raise an error.

*If neither works:* a human decides, which is not new work — HBA already
calculates every one of these refunds by hand. The platform records that
decision rather than re-deriving it, the way §9.2 already holds a multi-code
order for a person.

### 🟢 The commission base never needs the discount percentage

**The question**, asked by HBA on 25 August: a E£1,000 jacket with a 10% code
costs the customer E£900, and it is E£900 the model earns on. Does the platform
need the code's discount percentage recorded to work that out?

**No, and it must not use it.** The base is `total the customer paid − shipping −
tax`, read from the order. Shopify has already applied every discount by then,
so the paid figure is the discounted figure. A jacket at E£900 and pants at
E£540 give a base of E£1,440 with nothing configured anywhere.

`expected_customer_discount_bp` already exists on `compensation_period`,
separate from `commission_rate_bp`, exactly as HBA describes — a code may give
the customer 10% while the model earns 15%. **It is for verification only**
(§10.4): checking the Shopify code still matches what HBA recorded.

**Calculating money from it would be a bug.** It records what HBA *expects*. If
somebody edits the code in Shopify to 15%, the customer pays 15% less and the
platform would still calculate at 10% — silently overpaying on every order that
code touches, with no error anywhere. *Read what was paid. Never infer money
from a configured rate.*

**What is not yet verified:** that Shopify's refund line items are expressed in
the same discounted terms, so that subtracting a returned item leaves the right
figure. It should be — `subtotalSet` carries the line's discount allocation —
but the live sample contained **zero refunds**, so there was nothing to check it
against. Task 3 pins it with a test and it wants confirming against one real
refunded order before a payroll depends on it.

### 🟠 The 4-plus-items discount is harmless only while it cannot combine

**The limit.** HBA's automatic 20% discount for four or more items **cannot
currently be combined with a model's code**. That single fact is what keeps the
discount-voiding problem above away from commission entirely: an order carrying
the automatic discount has no model code, so it is unattributed and no
commission is calculated on it.

HBA expects this may change.

**What failure looks like if it does.** A model's order gets the automatic
discount. The customer returns one of four items. HBA voids the discount and
recalculates the remaining three at full price — so the goods the customer kept
are worth **more** than the discounted price they were sold at. Subtracting the
returned item's discounted price from the base would then leave a figure that is
too low, and the model is underpaid on an order that got *larger*.

*What to do before combining is enabled:* revisit the return rule above. It is
correct only while an attributed order can carry at most one discount that a
partial return cannot retroactively remove.

### 🟠 `partially_paid` earns like any other delivered order

**The limit.** §9.1 names `partially_paid` as a status the old dashboard
"handled nowhere", so a mid-exchange order passed through as normal at up to 47%
inflated value. **This platform does not special-case it either** — a delivered
order with no unresolved return earns, whatever its financial status says apart
from `refunded` and `voided`.

It is **25 of 537** live orders, about one in twenty.

**Why, and why it is not the old defect.** The 47% was an *inflated base*, and
the freeze (ADR 0011) is what stops that — not the state machine. Requiring full
payment before earning would be worse than it sounds: for cash on delivery,
delivery *is* payment and Shopify's financial status lags the courier. **118 of
537 orders sit at `pending`**, so a payment condition would park most of the
shop. And treating "some money" as worse than "no money" is backwards.

**What failure looks like.** An order genuinely stuck part-paid — a customer who
paid a deposit and never the balance — earns full commission. The mid-exchange
case §9.1 worries about is caught by the return being unresolved, so this is
narrower than it sounds, but it is not nothing.

**What exists instead.** Nothing. `partially_paid` is a number worth watching
once a month of real payroll exists: if it climbs, or if any of those orders
never reach `paid`, the rule needs revisiting with evidence rather than the
guess that would be made now (ADR 0019).

### 🟠 An order delivered with no timestamp never finishes

**The limit.** `is_finalised` measures the 10-day return window from
`delivered_at`. Some couriers report `DELIVERED` without a date. Such an order
**earns and pays normally** — that part is unaffected — but it never reaches
finalised, so it stays recalculable for ever and shows on a dashboard as *may
still change* long after it cannot.

**What failure looks like.** No wrong payment. A permanent asterisk on an order
that is in fact settled, and a row that keeps being re-read from Shopify when it
has nothing left to say.

**Why not fall back to another date.** The alternatives are worse: using the
order's own date would finalise it before it was even delivered, and using
"first seen" would finalise a historical import instantly. Leaving it visibly
open is the honest answer.

*What to do:* `GET /api/operations/order-facts` reports
`fulfilments_carrying_a_delivered_timestamp` against the delivered count. In the
live samples so far the two have matched exactly — every delivered fulfilment
carried a date — so this is currently theoretical.

### 🟠 A return after delivery is not deducted at all *(accepted, ADR 0025)*

**The limit.** Once an order is delivered it is finished with. A customer who
receives the goods and sends them back — for money, or in exchange — leaves the
model paid in full, and HBA absorbs it.

**Why, rather than because it was hard.** Three separate attempts failed on the
data, and ADR 0025 records each: Shopify's refund figures are not what HBA
actually refunds, Shopify refuses to say whether a return was an exchange
(`read_returns` is not granted), and an exchange may swap **any** number of items
for any other number — so no rule expressible from this data would be reliably
right. Building precision on an input known to be wrong is the expensive way to
be confidently incorrect.

**The measured cost.** Across the 537 orders indexed on 26 August 2026, six show
money having gone back: one `refunded` and five `partially_refunded`. **1.1% of
orders**, and only a fraction of any one of them is commission.

**The case that will eventually be noticed.** A customer receives E£5,000 of
goods and returns all of it. The model is paid on a sale that fully reversed.
That is accepted knowingly, not overlooked.

**This was put to HBA and decided, not left implicit.** Voiding a fully refunded
order is one boolean and would remove the case above — but HBA chose to keep the
rule whole: nothing related to an edit after delivery belongs in V1, a full refund
included. One exception invites the next, and each carries back a little of the
machinery ADR 0025 removed.

It is recorded in §3 of the specification as the **first** thing to add whenever
reversal is revisited.

**It is reversible.** `order_index` still stores `return_status`,
`return_activity`, `refunded_total_piastres` and `refunded_merchandise_piastres`
on every order. The facts keep arriving; the engine does not read them. A later
phase can measure exactly what a real year cost and decide again with evidence.

### 🟠 An order first seen mid-exchange freezes at the inflated figure

**The limit.** The base is fixed at whatever it was **when the order was
delivered**. That only works if the platform saw the order before then. One first
indexed *after* delivery, with an exchange already open, has no previous value to
keep, so it takes what Shopify shows — which for `#29115` mid-exchange was E£1,675
of goods against E£1,062 actually paid.

**What failure looks like.** A single order overstated by up to about 47%, and
frozen there. It does not correct itself, because the whole point of the freeze
is that the figure is never re-read.

**Who this hits.** Only the historical import, and only orders that were
mid-exchange at the moment it ran. Every order arriving by webhook is seen while
it is still travelling, so its base is right before anything can inflate it.

**What exists instead.** Nothing automatic — the correct figure is not in any
data the platform ever saw, and since ADR 0025 nothing later will correct it
either.

*What to do before the first real payroll:* after re-running the import, check
`/api/operations/order-facts` for orders with a return open. Anything in that
list that predates the platform is worth eyeballing against Shopify — it is a
handful of orders, once.

### 🔴 Line-item prices do not include the discount code

**The finding.** `GET /api/operations/order-facts?sample_size=250` on 26 August
2026 compared each order's line-item totals against its own subtotal. **Only 71
of 250 agreed.** The 179 that disagreed did so by a constant ratio:

| Line items sum | Order subtotal | Ratio |
|---|---|---|
| 199,700 | 179,730 | 0.9 |
| 109,800 | 98,820 | 0.9 |
| 99,800 | 89,820 | 0.9 |

That is a **10% discount code**. `LineItem.discountedTotalSet` and
`discountedUnitPriceSet` carry only *line-level* discounts. The order-level code —
the model's code — is applied at the order, and appears only in
`currentSubtotalPriceSet` and `currentTotalPriceSet`.

**What failure this prevented.** HBA asked for the commission base to be built by
summing the items the customer kept. Built from those line-item fields it would
have used **pre-discount prices**, paying every model commission on the shelf
price rather than what the customer actually paid — roughly **10% too much on
every attributed order carrying a code**, silently, for ever.

**What the platform does instead**, and why it was already right: the base is
`total the customer pays − shipping − tax`, read from the **order**, where the
discount has already been applied. A E£1,000 jacket on a 10% code arrives inside a
total of E£900, and no percentage is configured anywhere.

*The rule this leaves behind:* **money comes from the order, never from the sum of
its lines.** If the kept-items approach is ever revisited (§3 of the
specification), it must read `discountAllocations` per line, or apply the order's
own discount ratio — not `discountedTotalSet`.

### 🟢 The delivery signal, confirmed at scale

250 shipped orders sampled on 26 August 2026: **163 delivered, every one carrying
a timestamp.** No unrecognised statuses, and no order needing the
`unknown_fulfilment_status` fallback.

**13 were `NOT_DELIVERED`** — 5.2%, one order in twenty refused at the door. That
is the loss ADR 0012 exists to prevent, and it is not theoretical: the old
dashboard pays commission on every one of them unless an external Shopify
automation happens to cancel it first.

**E-stebdal's tags will not distinguish an exchange from a return.** Every
return-bearing order carried tags, but they are workflow markers — `bosta_synced`,
`Confirmed ✅`, `Call Confirmed📞` — with one exception (`Est-R1-Damaged_products`)
appearing once in 250. Moot since ADR 0025, and recorded so the idea is not
revisited on the assumption it would have worked.

**Refunds are mostly not refunds.** 40 orders carried refund line items worth
E£34,444 of merchandise against **E£2,689 actually refunded** — a factor of nearly
thirteen. Goods come back; money largely does not. That is the exchange pattern
ADR 0011 identified, now measured across a real sample rather than one order.

### 🟠 Recording a target and verifying it are the same person

**The limit.** `targets.record` and `targets.verify` are separate permissions,
because one person recording a number that unlocks a payment is one person
deciding what somebody is owed. **HBA's `content_manager` role holds both**
(ADR 0018), so today the separation is structural rather than organisational:
the platform enforces a split the staffing does not.

Phase 3 recorded this for compensation. Phase 5 is where it starts **deciding
payments** — a verified, achieved target is what applies a base guarantee (§9.5),
and Sara can record the actuals and confirm them themselves.

**What failure looks like.** Not fraud, most likely. A miscount confirmed by the
person who made it, and a guarantee paid on a month that did not qualify. Nothing
errors, and the audit trail shows a correctly-followed process.

**What exists instead.** The full trail: who recorded, when, who verified, when,
and a written reason required to take a verification back. Re-recording actuals
**clears any verification**, so a correction cannot inherit somebody else's
confirmation.

*What to do:* when there are two people, give `targets.verify` to somebody who
does not hold `targets.record`. The endpoint check is already there and will start
meaning something the day the roles differ.

### 🟠 Nothing stops a target being changed after payroll

**The limit.** §15 says recording is blocked once a month is `approved`.
`assert_recordable` is where that rule lives and **it blocks nothing**, because
approved months do not exist until Phase 6.

**What failure looks like.** A target edited after a month was paid, changing
whether a guarantee applied and therefore what the month was worth — after the
money moved. The payroll snapshot would disagree with the target it was
calculated from, and nothing would reconcile them.

**Why it is a seam rather than a check.** The same shape as
`assert_correctable` for compensation in Phase 3: one place for the rule to live
so it is not remembered at three call sites later, called from every mutating
path, and tested as being called.

*Phase 6 must wire it*, and this entry is what says so.

### 🔴 The go-live month is not chosen, and nothing can be approved until it is

**The limit.** §11.2 divides time at a configured **go-live month**: everything
before it is `historical` — imported, visible, and **never payable**, because it
was settled outside the platform. §21 lists choosing it as an open question, and
it is still open.

`GO_LIVE_MONTH` is blank, and blank **blocks every approval** with
`go_live_month_is_not_configured`.

**Why blank rather than a default.** A default would silently make eight months
of imported orders look approvable — money HBA has already paid, presented as a
debt and ready to be paid a second time. Refusing until somebody chooses is the
entire point of the feature, so refusing loudly is the only honest default.

*What to do:* set `GO_LIVE_MONTH` on Railway to the first month the platform is
responsible for paying, as `YYYY-MM`. Everything before it will show sales only,
labelled *"Settled before the platform — commission not calculated"* (ADR 0014).

**Choose it before the first real payroll, not during.** Moving it afterwards
would turn already-approved months into historical ones, or historical months
into payable ones, and neither has a defined behaviour.

### 🟠 A reopened month that is never re-approved

**The limit.** Reopening returns a month to `draft` and preserves the snapshot
payments were made against. Nothing forces it to be approved again.

**What failure looks like.** Not a wrong number — a month sitting in draft with
real money already paid against a superseded version. `balance_due` is computed
from the **active** snapshot, and a reopened month has none, so the amount
outstanding for that model is unanswerable until somebody re-approves.

**Why it is allowed at all.** Reopening exists precisely because something was
wrong; forcing an immediate re-approval would mean approving a figure nobody had
finished checking.

**What exists instead.** `GET /api/payroll/{month}/reopened` lists them, and
§11.5 requires a home-screen alert once there is a home screen. **The dangerous
state is not reopening; it is forgetting.**

### 🟠 A code created before the switch cannot be handed over

**The limit.** `retire_and_replace` ends the old code the month **before** the
new one starts, and takes the new one's start month from **when Shopify created
it**. Those are the same date only because HBA creates a code at the moment of
switching a model onto it. Nothing enforces that habit.

**What failure looks like.** `NEW10` is created on Shopify in July, but they
keep earning on `OLD10` through August. Switching them in September derives a
July start, which ends `OLD10` in June — so their July and August `OLD10` orders
fall outside every period they own. Two months of their sales belong to nobody.
Nothing errors, nothing recalculates, and the only visible trace is a smaller
payout than they expect.

The mirror case is as bad: if somebody else used `NEW10` in those months, those
orders become theirs.

**What exists instead.** The handover is **refused** when it would strand
anything. Before ending the old period, `_orders_on_or_after` counts orders on
the old code in the new code's start month or later; any at all and the request
fails with a 400 naming the code, the count, and this file.

The check is on the *harm*, not the calendar. A code created early that nobody
used strands nothing, so it is allowed — sizing the guard to the failure rather
than to the shape it usually arrives in (ADR 0019).

**What is missing.** A way to say **which month they actually moved over**,
separate from when the code was created, with the orders the new code already
accumulated shown before the decision is confirmed. Deliberately not built:
HBA does not work this way today, and a handover month that can be typed is a
handover month that can be typed wrong — which silently re-attributes real
money in both directions.

*What to do if the refusal appears:* do not work around it by retiring the code
by hand. It means the two dates genuinely disagree, and someone has to decide
which months belong to which code. Raise it, and build the feature above.

### 🟢 A base guarantee is paid *(fixed, Phase 5)*

**The limit, as it stood.** §9.5 pays a `base_guarantee` affiliate
**max(commission, base amount)**, but only when targets were achieved *and*
verified. Targets did not exist, so the calculation reported their commission and
refused to resolve the guarantee — which meant **no base-guarantee model could be
paid through the platform at all.**

**Fixed.** `monthly_target` records what they were asked for and what they produced;
verification confirms it; `calculate_month` applies §9.5.

| Situation | Result |
|---|---|
| Achieved and verified | `max(commission, base)` |
| Achieved, unverified | **Blocked** — verification is what unlocks it |
| Recorded, missed | Commission, and the month approves |
| Nothing recorded | **Blocked** — nobody knows |

**The distinction that survives.** Missing information blocks; poor performance
does not. A model who missed their targets is paid what they earned, promptly, and
their month closes. The block exists only where the platform genuinely *does not
know*, never as a penalty for a quiet month.

*The warning that is no longer needed:* switching a model from `base_guarantee`
to `commission` to unblock a month silently removed their guarantee. There is now a
correct way to unblock one — record their actuals and have somebody confirm them.

### 🟢 Correcting pay terms is blocked by payroll *(fixed, Phase 6)*

**The limit, as it stood.** `assert_correctable` was a seam that blocked
nothing, because approved months did not exist. A rate corrected after payroll
would change what a month was worth **after the money moved**, and the frozen
figure would silently disagree with the data it came from.

**Fixed.** Correcting terms that cover an approved month is refused, naming the
month and pointing at reopen — which requires a written reason.

**Narrower for *ending* terms, deliberately.** Closing a period in August does
not change what April was worth: April was on those terms and still says so.
Only a close that would leave an approved month with **no terms at all** is
refused, because that month would be incalculable if it were ever reopened. This
distinction was found by a test that was right to fail.

The same wiring closed `assert_recordable` for targets: a target decides whether
a base guarantee applied, so editing one after payroll changes what the month was
worth.

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

### `attribution_held`

An order carried **two or more registered model codes**. Nothing was written for
it: §9.2 makes it wait for a person rather than silently paying the wrong one or
paying twice.

HBA's Shopify configuration makes this unlikely, but Shopify permits combinable
codes in general and settings change. The log line names every code that
conflicted — a person cannot resolve it without knowing what collided.

*What to do:* decide which model the sale belongs to and close the other code's
period so the months no longer overlap. §11.3 makes an unresolved one a **hard
blocker** on approving that month.

---

### `attribution_conflict`

An order that already belongs to one affiliate resolved to a **different** one.
Nothing was changed — orders never move between models (§9.2, §17), and the
database trigger would refuse it anyway.

This reports *why* rather than letting an `IntegrityError` surface from
somewhere unrelated. It means a code changed hands with overlapping months, or a
period was registered wrongly.

*What to do:* look at the code's periods. The order keeps its original owner,
which is correct — the fault is in the registration, not in the order.

---

### `unknown_fulfilment_status`

A Shopify fulfilment carried a display status nothing has classified. It was
treated as **still in flight** — the order neither earns nor voids on a value
nobody has decided about.

Courier integrations add statuses. Without this line the order would simply sit
pending for ever, and the reason would be invisible: an unrecognised status and
a parcel genuinely still travelling look identical from outside.

*What to do:* the log line names the status. Decide which of the three sets in
`app/services/shopify/fulfilment.py` it belongs to — `DELIVERED_STATUSES`,
`FAILED_STATUSES` or `IN_FLIGHT_STATUSES` — and add it there. **Match the set,
never a substring:** `OUT_FOR_DELIVERY`, `ATTEMPTED_DELIVERY` and
`NOT_DELIVERED` all contain the word *deliver*, and reading any of them as a
delivery pays commission on goods the customer does not have.

---

### `work_deduplicated`

Work was queued for something already queued, and was absorbed. **Expected in
ordinary operation** — Shopify sends create, update and paid for one order
within seconds.

*What to do:* nothing, unless the rate is high, which means a sender is looping.

---

### 🟠 A summed money column comes back as a string *(fixed, guarded)*

**The limit.** Postgres `SUM()` over a `bigint` returns **`numeric`**, not
`bigint`. psycopg hands that back as a `Decimal`, and a `Decimal` reaching the
API is serialised as a **string**.

**What failure looks like.** Every balance arriving as `"180000"` instead of
`180000`. Nothing errors — JSON is happy to carry a string — and it breaks in the
client, where `balance - paid` becomes a type error or, worse, a string
concatenation. Money silently stops being a number at the boundary.

**How close this came.** Caught by a test comparing a balance to an integer,
which failed with `assert '180000' == 180000`. Without that comparison it would
have shipped and surfaced as an inexplicable frontend bug months later.

**Fixed** in `app/services/payments.py`: every `func.sum` over piastres is
wrapped in `int()`. ADR 0002 says money is integer piastres everywhere, and
"everywhere" includes on the way out of an aggregate.

**Recorded because it applies to every future sum.** `func.count()` is safe;
`func.sum()` over `bigint` is not. Any new total over a money column needs the
same wrapper, and the symptom will look like a frontend problem rather than a
database one.

### 🟠 "Out for delivery" is not "delivered" *(fixed, guarded)*

**The limit.** Shopify's fulfilment display statuses include `DELIVERED`,
`OUT_FOR_DELIVERY`, `ATTEMPTED_DELIVERY` and `NOT_DELIVERED`. The obvious test —
does the status contain the word *deliver* — reads **all four** as a delivery.

**What failure looks like.** A parcel still on the van, a failed delivery
attempt, and a customer who refused the goods at the door would each count as
money earned. For cash-on-delivery through Bosta that is precisely the loss
ADR 0012 was written to prevent, and it would arrive as commission quietly paid
on sales that never happened — the old dashboard's defect, rebuilt.

**How close this came.** The first version of `delivery_verdict` used
`"DELIVER" in name and "NOT" not in name`, which excluded `NOT_DELIVERED` and
happily accepted `OUT_FOR_DELIVERY`. It was caught by a test written to assert
the opposite outcome, before the function was ever called against the live shop.

**Fixed** in `app/services/shopify/facts.py`, which now matches an explicit
`DELIVERED_STATUSES` set. Guarded by
`test_a_status_that_merely_contains_the_word_is_not_a_delivery`, parametrised
over every lookalike, and by `test_delivered_and_not_delivered_do_not_overlap`.

Recorded because the same trap waits for Task 4, which turns these statuses into
`earned`. **String matching on a status name is how the wrong parcel gets paid
for.** Match the set, never the substring.

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

## UI copy asserted a failure the backend does not have

**Symptom.** Malak's profile showed a red banner reading "Shopify has not
confirmed this code yet, so no orders are being attributed to it" — directly
above a panel reading **Sales that count: E£2,100.00**. The page contradicted
itself in two adjacent boxes.

**Cause.** Mine, in the copy. I assumed verification gated attribution. It does
not: `registered_codes` matches on *registered* periods and never looks at
`shopify_verified_at`, so a code nobody has confirmed still attributes orders
perfectly well. The list screen inherited the same wrong idea and counted such
affiliates under "cannot earn yet".

**What verification actually buys.** Confirmation that the code exists on
Shopify. If it was mistyped, or was never created there, **no order will ever
carry it** — and the failure is silent, because an affiliate with no sales looks
exactly like an affiliate who made none. The risk is real; it is just a
different risk, and one degree less severe than "their money is going nowhere".

**Fixed** in `Affiliates.tsx` and `AffiliateDetail.tsx`: the column is
*Needs attention*, missing pay terms is listed first as the one that genuinely
stops payroll, and the unconfirmed-code text says what the actual exposure is.

**Worth recording even though nothing shipped.** An interface that overstates a
problem is not a safe error to make. Somebody who is told twice that a working
code is broken learns to ignore the warning, and the warning is there for the
day the code really is wrong. The reason this was caught at all is that the
seed data put a contradiction on one screen — reasoning about the copy alone
would not have found it.

---

## The payment screen could not have paid anyone by bank transfer

**Symptom.** None yet — found by the business reading the design, before the
payment screen was built.

> "People that will not go with InstaPay and choose maybe e-wallets or bank
> accounts, they won't have this link."

**Cause.** Spec §13.1 and §14 were written entirely around InstaPay, whose
**Payment Address URL** sits behind a *Pay* button that deep-links into the
app. That flow has a property nobody noticed was load-bearing: **the payer
never has to read the address.** The link carries it.

`mask_destination` is the only representation the API returns, so an account
number reaches every screen as `…756`. For InstaPay that is fine. For a bank
transfer it is fatal — the entire act is *read the number, type it into your
banking app* — and there was **no endpoint anywhere** that could hand over the
real value. The payment screen, as specified, could not have completed a bank
or wallet payout at all.

**Two faults, and the second is the one that mattered.** A *Pay* button with
nothing to open is visible the moment somebody presses it. A missing path to
the number is invisible until the first non-InstaPay model is due money — most
likely at month end, with a person waiting to be paid.

**Fixed** by ADR 0028: a reveal endpoint gated on `payments.record`, audited
without the value, returning only the fields that method needs.

**Why it was missed.** The masking rule in §6.4.4 is about *records* — audit
rows, logs, notifications, the confirmation shown when a destination changes.
I read it as an absolute and implemented it as one, which made a necessary task
impossible rather than safe. A security rule that stops the work is not a
strict reading of the rule; it is a misreading of what the rule was protecting.

---

## The payroll screen showed a working number in the face reserved for debts

**Symptom.** Caught on screen during the first run of the payroll table, before
it shipped. Two models read *Approved · E£5,512.00* in the mono face — which
under ADR 0027 means **this is an obligation and it cannot change.**

It could change. The figure came from `calculation.payout_piastres`, which
`blockers_for` recomputes on every request.

**Cause.** `_row` returned one amount for both questions. For a draft month
"what would this come to" and "what is owed" are the same number, so nothing
looked wrong. For an **approved** month they are different by design: §11.4
says an order settling after approval lands in the *next* month and never
alters the one already agreed. Egyptian COD delivery straddles month end
routinely, so the two figures would have diverged within days of going live.

**What it would have looked like.** A month approved at E£5,512. Two orders
land on 2 October. The payroll screen still says *Approved*, still sets the
number in mono, and now reads E£5,900 — a figure nobody agreed, in the typeface
that promises somebody did. The payments screen, reading the snapshot, would
have said E£5,512. Two screens, two numbers, both labelled as the debt.

**Fixed.** `_row` now returns `approved_obligation_piastres` from the active
snapshot alongside the recalculation, and every place that prints the word
*approved* or *agreed* uses the snapshot. Guarded by
`test_an_approved_row_reports_what_was_agreed_and_what_it_would_be_now`, which
approves a month, lands a late order, and asserts the agreed figure has not
moved while the calculation has.

**Worth recording.** The typographic rule did its job: the number was wrong
long before the face was, but it was the *face* that made it obvious, because
mono is a promise. A design rule that makes a data bug visible has earned its
place.

---

## A credit could only carry into a month that had already been approved

**Symptom.** Recording an overpayment as a credit into the following month was
refused:

> Nour has no 2026-10 for the credit to land on. Open that month first.

**Cause.** `adjust` looked the destination up with `get_month`, which returns
nothing until a row exists — and `open_month` was called from exactly one
place, `approve_month`. So a credit could only land on a month that had already
been agreed.

That is backwards from when the situation actually arises. §11.5's overpayment
is discovered by reopening a settled month and re-approving it lower. In early
October, with September just corrected, **October has not been approved and
therefore does not exist.** The credit had nowhere to go.

**Why it was worth fixing rather than documenting.** The refusal named a step —
*"open that month first"* — that nothing in the platform could perform. There
is no "open a month" action anywhere, because ADR 0013 says month rows are
created on demand rather than on a schedule. So the two ways out were to write
off money that should have carried forward, or to remember to come back after
October's payroll — and §11.5 exists precisely because *remembering to come
back* is the thing that fails.

An error message describing a workflow that does not exist is the tell. It was
an oversight, not a constraint.

**Fixed** by opening the destination on demand, which is what `open_month` is
for. The credit sits on the draft month and changes nothing until that month is
approved, at which point `credited_into` folds it into the balance. Three
tests: the month is opened, the credit waits and then applies, and a month
opened only to receive a credit is **not** reported among the
reopened-and-forgotten — it has no superseded snapshot and no payment stranded
against one, and noise on that warning is the one thing it cannot afford.

---

## Carry-forward is identified, displayed, and never paid

**Fixed** — ADR 0029. Left below in full, because the symptom is what somebody
will recognise if it ever returns.

**Symptom.** An order placed 29 August, still travelling when August payroll
runs, delivering on 8 September. September's payroll row shows the line §11.4
asks for — *"1 order from August, E£1,000 of sales"* — and September's payout
does not include a piastre of it.

Proven directly:

    August approved at 20,000p  (10% of 200,000p)
    September says carried forward: [{'from_month': '2026-08', 'orders': 1,
                                      'piastres': 100000}]
    September payout: 30000p  from earned base 300000p

    September's own sales   300,000p -> commission 30,000p
    August's late order     100,000p -> commission 10,000p
    September actually pays  30,000p          <- the late order is never paid

**Cause.** `calculate_month` selects `AttributedOrder.business_month == month`
and nothing else. `carried_into` finds the late orders and
`carry_forward_summary` renders them, but no code path adds them to a payout.
Every test around carry-forward asserts *identification* — that the right
orders are found, that they keep their own month, that a settled one does not
carry twice. **None asserts one is ever paid.**

**Why it matters more than it looks.** §11.4 calls this "the common path, not
an edge case": Egyptian cash-on-delivery routinely straddles month end, and
118 of 537 live orders sit undelivered at any moment. This is not a rare
correction — it is a slice of every month, silently unpaid, for every model.

**And it forces the one thing §11.4 forbids.** Today the only way that order
reaches them is to reopen August, which the spec's own words rule out:
*"Orders settling after approval never alter the approved month."* The platform
currently requires the operation it tells you not to perform.

**How it was fixed.** The three open questions were business decisions and
were answered by HBA: the source month's rate, on top of any guarantee, settled
by the paying month. ADR 0029 records all three and the alternatives rejected.

**The second bug, found while fixing the first.** Settling a carried order in
September meant reopening August would recalculate August to include it — and
re-approving would agree commission September had already paid. Reproduced,
then closed by a single rule: *an order counts toward a month unless a
different month's payroll paid it.* Both halves matter; excluding **every**
settled order instead would make each month recalculate to zero the moment it
was approved.

---

## Accepting an invitation worked and looked like it had not

**Symptom.** Filling in the accept-invitation form and pressing "Get started"
did exactly what it should on the server - created the account, issued a
session, set the cookie - and left the person looking at the same empty form
with no sign anything had happened. `/api/auth/me` from that same browser
confirmed a live session; the screen simply never moved.

**Cause.** `/accept-invitation` is a public route, reachable whether or not
somebody is already signed in - deliberately, since an existing admin opening
their own invite link to check it is a real case (§13). `onSignedIn(session)`
updates state one level up in `App`, but nothing on the route itself reacts to
that by navigating anywhere. `/sign-in` redirects once a session exists
because its own route element checks for one; this route had no such check
and no navigation call at all.

**Fixed** by calling `navigate("/", { replace: true })` immediately after
`onSignedIn` succeeds, rather than relying on a route-level redirect - the
form is filled with a live password on screen at that moment, and leaving it
rendered a beat longer than necessary was the wrong side to err on.

**How it was found.** Not by reading the code - by finishing the whole loop in
a browser: invite, copy the link, accept it, expect to land in the tool. A
"it returned 201, so it must be fine" check on the endpoint alone would have
shipped this. Recorded because the same shape - a successful mutation with
nothing downstream to carry the person forward - is exactly the class of bug
that unit tests on an endpoint cannot catch.

---

## The onboarding guide image was served as the SPA fallback

**Symptom.** The InstaPay guide on the application form rendered as its alt
text: *"The InstaPay home screen, with the Link button under your account
circled"*. The file was on disk, the path was right, and the request returned
**200**.

**Cause.** `app/main.py` mounts exactly one static directory, `/assets`.
Anything else falls through to the catch-all that serves `index.html`, so
`/guides/instapay-link.png` returned 465 bytes of HTML with a 200 and an
`image/*` request quietly failed to decode.

A 404 would have been obvious. **A 200 that returns the wrong content type is
the version that wastes an afternoon**, and it is what any unmounted path does
in a single-page app with a catch-all route.

**Fixed** by importing the image in the component instead of referencing a
URL. Vite fingerprints it into `/assets`, which is the directory that is
actually mounted — one pipeline rather than a second mount to keep in step
with it.

**Found the same way as the last one:** by looking at the rendered page rather
than trusting the status code. `curl -o /dev/null -w "%{http_code}"` said 200
and would have ended the investigation; `%{size_download}` said 465 bytes and
gave it away.

**Also fixed on the way past:** the screenshot was 1.4 MB. It renders at 11rem
tall on a form a model fills in once, on a phone, on Egyptian mobile data.
Resized to 720px tall — 224 KB, 84% smaller, still sharp on a 3x screen.

---

## A failed action wiped the record it failed against

**Symptom.** Pressing *Check it* on an affiliate's review panel, against a
machine with no Shopify credentials, replaced the entire page with one line:
*"Shopify is not configured: set SHOPIFY_SHOP_DOMAIN"*. Correct message,
nothing else left on screen — their name, their arrangement, their payout details,
the two steps still outstanding, all gone. The only way back was to navigate
to the list and find them again.

**Cause.** `AffiliateDetail` had one `error` state and one early return:

    if (error) return <p className="notice notice--refused">{error}</p>

That branch was written when the only thing that could fail was **loading the
affiliate**, where replacing the page is right — there is nothing to show. Batch C
added actions to the same component, and every one of them called the same
`setError`. An action failing is a completely different situation: everything
the person was looking at is still valid, and they need it to decide what to do
about the failure.

**Fixed** by making the branch conditional on there being nothing to show:

    if (error && !detail) return <full-page error>

With a record loaded the error renders in place, above the panel it came from.

**Worth recording** because the fault was in reusing a state variable, not in
the error handling — both call sites looked correct in isolation. The general
shape: **a component that both loads and acts needs to distinguish "I have
nothing" from "that did not work",** and a single `error` state cannot.

**Found by running the failing path on purpose.** Shopify is deliberately
unconfigured locally, so pressing the button was the fastest way to see what a
maintainer with a misconfigured deploy would see. Testing only the success path
would have shipped it.

---

## A guaranteed minimum that did not apply was never mentioned

**Symptom.** Sara is on a guaranteed minimum of E£8,000. Their targets for
September had not been recorded, so §9.5's comparison had no answer and the
month paid their commission: E£1,100. Their portal showed *STILL ADDING UP*,
E£1,100, a breakdown reading *Commission on this month's sales*, and a note
saying nobody had recorded their posts yet.

Every figure on that screen was correct. The word "guarantee" did not appear on
it anywhere.

**Cause.** The month endpoint returned `guarantee_applied: false` and nothing
else about the guarantee. That was enough for the maintainer's screens, which
show the arrangement in a column beside the figure - and useless on theirs, where
the arrangement is not on the page at all because they are assumed to know it.

They do know it. That is exactly why its absence reads as *they have forgotten
my minimum* rather than as *the comparison could not be made*.

**Fixed** by returning the guarantee whether or not it applied, with the three
target states §15 distinguishes, and saying which sentence applies:

| Target state | What they read |
|---|---|
| Not recorded | *Whether it applies depends on your targets, and nobody has recorded them yet.* |
| Met, not confirmed | *You met your targets, so it applies as soon as HBA confirms the numbers.* |
| Missed | *It applies in a month where your targets are met. They were not this month, so you are paid your commission instead.* |

The third one matters most and is the one to keep an eye on in future edits: a
missed target costs them the guarantee and **nothing else** (§11.3), and any
wording that makes it sound like a penalty is wrong about the rule as well as
unkind.

**Worth recording** because no test could have found it. Every endpoint
assertion passed; the figure was right; the blocker was right. What was missing
was a number that was never asked for, on a screen whose reader brings context
no test has. **Found by signing in as a model and looking at their own month** -
the discipline that has now caught this, the invitation redirect, the guide
image, and the page-wiping error, none of which any status code disagreed
with.

---

## A test asserted a blocker that was never raised

**Symptom.** A new test claimed an agreed month stays settled even when a
later multi-code order re-blocks it. It passed. It also passed with the guard
it was testing replaced by `if False`.

**Cause.** The test's `_affiliate` helper posted `{"user_account_id", "name",
"code"}` to `POST /api/affiliates`. `CreateAffiliateBody` has no `code` field,
so Pydantic dropped it in silence. No discount code period was ever registered,
`resolve_order` matched nothing, the order resolved as *unattributed* rather
than *held*, and the blocker the test was named after never existed.

**Fixed** by writing the `discount_code_period` row directly, the way
`test_orders_api.py` already does - registering one through the API calls
Shopify to settle the start month, which is not what that file is about. An
assertion against the maintainer's own payroll view now proves the blocker is
raised before the portal is asked to suppress it.

**Worth recording** for the method rather than the bug: **a guard is not tested
until the test has been seen to fail without it.** Breaking it on purpose took
one edit and thirty seconds, and it was the only thing that distinguished a
real test from a decorative one. Pydantic ignoring an unknown field is the
general hazard - a request body is not a schema check unless the model has the
field.

---

## The dev server and the test suite share one database

**Symptom.** A full `pytest` run finished `1315 passed, 4 errors`, the errors
being a Postgres deadlock and `{"detail":"An account already exists"}` from
bootstrap. Re-running with nothing else touching the machine: `1317 passed`.

**Cause.** `uvicorn` was left running against the same local Postgres the suite
uses. `fresh_database` truncates every table between tests; the server held
connections and pooled sessions across those truncations, so the two fought for
locks and occasionally left a committed row behind.

**Not a bug to fix** - one local database is the right setup for developing
screens against seeded data. Recorded because the symptom is alarming and the
cause is not in the code: **stop the dev server before trusting a full test
run**, and treat any bootstrap or deadlock error in the suite as this until
proven otherwise.

---

## Browser verification: synthetic input does not reach a React input

**Symptom.** Driving the sign-in form through the browser tools, clicks landed
and keystrokes did not. `form_input` set the field's `value` and the page
showed the text, but submitting sent nothing - and repeated `Page.captureScreenshot`
calls timed out with *the renderer may be frozen*.

**Cause.** React tracks a controlled input's value on the DOM node itself.
Writing `element.value` sets the DOM property and leaves React's copy behind,
so its `onChange` never fires and component state stays empty.

**Worked around** by setting the value through the native prototype setter and
dispatching a bubbling `input` event, which is what React listens for:

    const proto = Object.getPrototypeOf(el);
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v);
    el.dispatchEvent(new Event("input", { bubbles: true }));

**Worth recording** because browser verification has caught four real bugs in
this project and is worth keeping usable. When keystrokes stop landing, this is
the first thing to try; when they still do not, navigating straight to a route
by URL and reading the result is a smaller, more reliable check than
reproducing a click path.

---

## A settled month did not account for itself

**Symptom.** Nour's September was agreed at E£2,400.00, transferred as
E£2,340.00 with the remaining E£60.00 written off as a bank fee. Their payments
screen read:

    September 2026        E£2,400.00   paid
    27 August 2026        E£2,340.00   For September 2026   IPN-4471

Both correct. Read top to bottom by the person whose money it is, sixty pounds
went missing. The write-off *was* on the screen — in a separate panel, several
sections further down, headed *Changes without a transfer*.

**Cause.** `balance_for` returns `adjusted_piastres` and `credited_piastres`
alongside the payment total, and the portal payload dropped both. The
settlement state was right, the balance was right, and the row had no way to
say **how** it got to zero.

The maintainer's payment screen has never needed this: it shows the parts in a
column beside the total, and whoever is looking made the adjustment themselves
ten minutes earlier. They did neither.

**Fixed** by carrying both figures on the month row and stating them where they
are looking:

    E£2,340.00 transferred, and E£60.00 settled without a transfer.
    See below for why.

A test now asserts the three account for each other exactly —
`paid + adjusted == obligation` — because that is the property the row exists
to let them check.

**Worth recording** as the same shape as the guaranteed-minimum bug found an
hour earlier, and the shape to watch for through the rest of this phase:
**every figure on the screen was correct, and the screen was still wrong.**
A maintainer's screen can rely on the reader having context. Theirs cannot. The
test that would have caught either one is a person reading the page top to
bottom and trying to make the numbers meet.

---

## Browser verification degraded mid-session, twice over

**Symptom.** Two distinct failures in one session, both silent about their real
cause.

*Synthetic input stopped reaching the page.* Clicks landed, keystrokes did not,
and `Page.captureScreenshot` began timing out with *the renderer may be frozen*.
Worked around by setting React inputs through the native prototype setter — see
the entry below.

*Later, the window collapsed to a zero viewport.* Screenshots failed with
`Failed to deserialize params.clip.scale`, and `window.innerHeight` reported
`0`. Anything measured through `getBoundingClientRect` came back as 3px, which
looks exactly like a CSS bug: a proof screenshot with `max-height: 60vh`
computed to `max-height: 0px` and rendered 3 pixels tall.

**Not a CSS bug.** `60vh` of a zero-height viewport is zero. The image itself
was fine: 200, `image/jpeg`, natural size 900×1400, correct `alt`.

**Worth recording** for the diagnostic, which cost real time: **before
believing a layout measurement, check `window.innerHeight`.** A collapsed
viewport makes every element three pixels and every `vh` unit zero, and the
resulting numbers are indistinguishable from a genuine layout fault.

`resize_window` reported success without restoring it. When that happens,
`get_page_text` still works and still verifies the thing that matters most —
that the right words are on the page in the right order — so the remaining
check is a reading, not a screenshot.

---

## A screenshot that will not load

**Not a failure that has happened**, recorded because the guide-image incident
in Phase 8 was exactly this shape and cost an afternoon.

An `<img>` pointed at `/api/me/payments/{id}/proof` renders as broken alt text
if the request 404s — a deleted proof row, an expired session, a payment id
that stopped being theirs. The payment above it is real either way, so a broken
icon is the least useful thing that could appear.

`onError` now swaps the image for a sentence: *the screenshot would not load;
the transfer above is still recorded.* One line, and it keeps a storage problem
from reading as a payment problem.

---

## A scripted edit made the retry path unreachable

**Symptom.** None, and that is the point. The notification sender's tests
passed, the full suite passed, and the branch that re-queues a failed email had
become dead code:

    if row.attempts >= MAX_ATTEMPTS:
        row.state = FAILED
        _forget_secrets(row)
    return                      # <- dedented one level
    enqueue(...)                # <- unreachable

A mail server that was briefly unavailable would have marked the attempt and
never tried again. Every email queued during the outage would have sat at
`pending` forever, and nothing on any screen would have said so.

**Cause.** A Python script applying the edit computed the indentation of the
inserted `return` from the whitespace of the block it was replacing, and got it
wrong by four spaces. Python accepted it - a `return` at function level after a
conditional is perfectly legal - and no test covered the give-up path and the
retry path in the same run.

**Found by reading the file afterwards**, not by running anything.

**Worth recording** as a rule about how the edit was made rather than about
what it did: **a scripted edit that computes indentation is a scripted edit
that can silently change control flow.** String replacement with the full
surrounding block written out by hand cannot do this; anything that derives
whitespace can. Re-read the region after any patch that inserts a statement
into an existing branch.

The tests were extended so the two paths are exercised in one file, and the
retry now asserts a second job was actually queued.

---

## Backslash escapes do not survive a shell heredoc here

**Symptom.** Three separate `SyntaxError`s while writing Python through
`bash <<'EOF'`, all of the same shape:

    clean = "".join(c for c in name if c not in "
    ").strip()

`"\r\n"` in the script became a literal carriage return and newline in the
written file. The same thing happened to `"\n\n"` inside an email template and
turned a working module into an unterminated string literal.

**Cause.** Not diagnosed precisely, and it does not need to be: the quoted
heredoc should pass its body through untouched, and in this environment it does
not. Long command bodies were separately truncated at the terminator, producing
`unexpected EOF while looking for matching`.

**Worked around** by writing any content containing escape sequences - or
anything over a few dozen lines - with the file-writing tool and having a short
script splice it in. Naming the characters instead of embedding them also
works, and reads better in this case:

    LINE_BREAKS = (chr(13), chr(10))

**Worth recording** because the failure mode is *silent corruption of source*,
not a refused command. The `SyntaxError` was the lucky version. The same
collapse inside a string that still parses - a template, a regex, a SQL
fragment - would have shipped.

---

## Every email failed in production while every test passed

**Symptom.** An invitation was sent from the deployed staging platform. The API
returned 201, the screen said it had been emailed, and nothing arrived — not in
the inbox, not in spam. The logs said:

    job 4 (notification.send) failed:
      TypeError: _forget_secrets() takes 1 positional argument but 2 were given
    ANOMALY job_gave_up attempts=5 job_id=4 kind='notification.send'

Five times, then it gave up. **Every email the platform would ever send was
failing the same way.**

**Cause.** A scripted edit inserted a helper function between
`@register_handler(JOB_KIND)` and the function it was decorating. The decorator
therefore registered `_forget_secrets` as the handler for `notification.send`,
and `send_notification` was registered for nothing at all. The worker called
the helper with `(db, payload)`; it takes one argument.

Python was perfectly happy. So were twenty-one tests.

**Why nothing caught it.** Every test called `send_notification(db, payload)`
**directly**. They covered the send, the skip, the refusal, the retry, the
give-up, and the token erasure — every branch inside the function, and not once
the question of whether anything would ever call it.

> **Calling a function is not the same as it being wired up.**

**Fixed** by moving the decorator, and by adding the two tests that would have
caught it: one asserting `HANDLERS["notification.send"] is send_notification`,
and one that queues an email and runs `run_one` — the worker path production
uses. Both were confirmed to fail against the broken code before the fix went
in.

**Worth recording** twice over. The bug is the second one this phase caused by
a scripted edit computing where to put something (see *a scripted edit made the
retry path unreachable*), and the pattern is now unmistakable: **an edit script
that positions code relative to existing lines can silently move a decorator,
a `return`, or an `except` onto the wrong thing.** Read the region afterwards.

The test gap is the more general lesson. A handler, a route, a signal receiver
and an event listener are all functions whose *registration* is a separate fact
from their behaviour, and a suite that only ever calls them directly tests half
of what ships.

---

## There was no way to invite a model

**Symptom.** The business went to send a model their sign-in link, found *Invite
someone* in Settings, and the role list offered Admin, Content manager and
Affiliate manager. No model.

**Cause.** The invite form hard-coded the three staff roles in its dropdown.
`affiliate` is a real role — §6.1 gives it an empty permission set on purpose —
and it was never offered, so the only way to start the onboarding flow was to
call the API by hand.

Phase 8 built the whole model journey: invitation, acceptance, their own
application, approval. **Nothing could start it.** Every test drove it from the
API, so the suite proved the journey worked while the front door did not exist.

**Fixed** by putting it where models live rather than by adding a fourth option
to the dropdown, which is what the business asked for and is the better answer.
Inviting staff grants somebody permissions over other people's money; inviting a
model puts them on the programme and grants them nothing. Offering both from one
list said they were variations of one decision.

**Worth recording** as a gap a full test suite cannot see: **an end-to-end test
that starts at the API starts one step after the button.** The whole flow was
covered and the entry point was missing, and only somebody using the screen
could find that.

---

## A fix that only worked for people who had not signed in yet

**Symptom.** Reported twice, and the second time after it had supposedly been
fixed: inviting a model said *Authentication required*, and signing out
redirected to the home page instead of signing out.

**Cause of the original bug.** The session cookie is persistent — twelve hours.
The CSRF token lived in `sessionStorage`, which the browser empties when the
tab closes. A returning tab therefore held a live session and no token: every
read worked, the interface showed a signed-in administrator, and every write
was refused as unauthenticated.

**Cause of the fix failing.** The fix issued the token as a cookie — at
sign-in. Only at sign-in. A session that already existed when the fix deployed
never received one, and no amount of reloading could produce it, because
nothing but `POST /login` ever set it.

Which is to say: **the fix restored the invariant only for sessions created
after it, and the person reporting the bug had one created before it.** They
were told to reload. Reloading could not possibly have worked, and nobody had
checked that it would.

**Fixed properly** by making the invariant hold for every session rather than
for new ones: `GET /api/auth/me` now repairs a session that has no usable
token. The page loads it before anything else, so it is the one place
guaranteed to run before a write is attempted. It rotates only when the token
is missing or wrong, so a second tab does not invalidate the first.

**And logout was made exempt from the check.** What CSRF protection buys on a
logout is preventing somebody being signed out of their own session — it reads
nothing, changes nothing, moves no money. What enforcing it cost was somebody
who *could not sign out*, twice, once leaving a live administrator session on a
machine after the person had asked to leave it. That is the worse of the two,
and the exemption is pinned by a test so it stays a decision.

**Worth recording for the method, which is the real failure here.** Two fixes
went out for one bug and neither was verified against the thing that was
broken. What was missing was not care — it was a test that knows only what a
browser knows.

`tests/test_browser_journey.py` is that test now. Its client holds a cookie jar
and nothing else, and derives the CSRF header from the jar exactly as
`api.ts` derives it from `document.cookie`. **The rule for that file is: never
read a token out of a response body.** Every other API test in this project
does, and that single shortcut is what let a platform where no write worked at
all pass fourteen hundred tests.

It also covers the state nobody thinks to write a test for: **a session created
before today's deploy.**

---

## The screen said email was off on a platform where it was on

**Symptom.** Inviting a model returned *"Email is not switched on, so send her
this link yourself"* on staging (the wording the screen carried at the time), where `SMTP_HOST`, `SMTP_USERNAME`,
`MAIL_FROM_ADDRESS` and a valid app password were all set and mail was working.

**Cause.** One missing `return`:

    def invitation_sent(db, email, token, role) -> None:
        queue(db, event=Event.INVITATION_SENT, ...)

The caller decided what to tell the screen with
`invitation_sent(...) is not None`, and the function returned `None` every
time. So every invitation reported that nothing had been sent, **while the
platform sent it anyway.**

The worst kind of wrong: an instruction to do redundant work, and no reason
left to trust anything the screen says about delivery.

**Fixed** by returning the queued row, and by computing the flag from what is
actually true - a notification was queued, and there are credentials to send it
with.

**Worth recording** because the type annotation was `-> None` and honest about
it. The mistake was at the call site, which asked a question the function had
never claimed to answer. **A boolean derived from a function's return value is
a contract; `is not None` on something typed `-> None` is a bug the type
checker will not catch and the reader will not see.**

---

## Signing out worked, and the screen did not notice

**Symptom.** Pressing *Sign out* returned to the Overview showing
"Authentication required" in red, under a full sidebar, with the person's name
still in the corner. A refresh then showed the sign-in page.

**Cause.** The server did its part correctly: the session was revoked and both
cookies cleared. The application never told itself. `signOut()` was followed by
a client-side `navigate("/sign-in")`, React still held the session in state,
the route guard therefore redirected a "signed-in" person away from the
sign-in page to the Overview, and the Overview asked the server a question it
now answered with 401.

**Fixed** by making sign-out a **full document load**. Everything is
re-derived from the server, so there is nothing left to be stale.

That is a deliberate trade: a page load on the one action where nobody minds
waiting, in exchange for removing a whole class of *the screen and the session
disagree* bug rather than fixing one instance of it.

It is also now the **only** way out - `signOutAndLeave` lives in `api.ts` and
both screens call it. Two screens each doing their own version is how one of
them forgets, and one of them had.

**Not covered by a test**, and that is stated rather than hidden: this project
has no component-testing setup, and adding jsdom and a testing library in the
middle of a go-live was the wrong trade. The structural fix is what makes the
absence acceptable - there is one path, it cannot skip a step, and a future
screen that wants to sign somebody out has nothing to get wrong.

---

## Every email failed because the host blocks SMTP

**Symptom.** Not one notification ever arrived - invitations, applications,
approvals, payments, destination changes. Nothing in the inbox, nothing in
spam, over days and two rounds of "fixes" aimed at credentials.

**Cause**, from the deployed logs and unambiguous once looked at:

    notification 4 (invitation.sent) gave up after 5 attempts:
      OSError: [Errno 101] Network is unreachable

**Railway blocks outbound SMTP.** So do most hosts, on ports 25, 465 and 587,
to stop their address space being used for spam. No password, app password or
Gmail setting could ever have fixed it, and the recommendation to use Gmail
SMTP was wrong for this host from the first minute.

**Fixed** by sending over HTTPS through a provider API - port 443, which is not
blocked. `send()` still takes a `Message` and still raises `MailRefused` for a
failure that will not fix itself, so nothing above it changed.

**Worth recording** for what it says about diagnosis. Three rounds were spent
on the *symptom the screen showed* rather than on the logs, which had named the
cause exactly, in one line, from the first attempt. **The platform was telling
us and nobody read it.** Checking `railway logs` is now the first step for
anything that fails on the deployed platform, not the last.

---

## The import failed silently every time it was started

**Symptom.** Pressing *Import from Shopify* said "queued, it takes minutes, the
order count below will climb". The count never climbed.

**Cause.** Shopify rejected the whole document:

    Queries that contain a connection field within a list field are not
    currently supported. Invalid connection fields: 'refundLineItems'.

`refunds` is a list and `refundLineItems` is a connection inside it, which a
bulk operation refuses outright. The job retried five times and gave up, and
the only screen that could have shown that was the one nobody had built yet.

**Fixed** with a bulk-specific field set that omits it. The refund *total* still
comes back; the line-item breakdown does not, so `refunded_merchandise_piastres`
stays 0 on an imported row until the ordinary per-order sync fills it in.

**That gap is real and bounded**: refunded merchandise reduces a commission base
(§9.3), so an imported month can over-report sales until the reconcile sweep
catches up. The alternative was an import that does not run.

---

## `display: block` on a `<td>`

**Symptom.** Payroll's row rules ran level across the first four columns and
then stepped down under *Carried forward* and *Waiting on*. Screenshotted by
the business as "the lines break".

**Cause.** `.payroll__carried` is the class on a `<td>`, and it was given
`display: block`. A cell told to be a block leaves the table layout: it stops
sharing the row's height, and its bottom border is drawn wherever the block
happens to end.

**Fixed** by leaving the cell a cell and stacking only the lines inside it.

**Worth recording** as a rule rather than an incident: **a layout property on a
`td` is almost always a mistake.** The thing that wants to stack is the content,
and it needs a wrapper.

---

## A thousand pronouns, and four ways to get them wrong

**Symptom.** None yet — this is a record of what a bulk rewrite broke while
it was being checked, because each was invisible in a passing test suite.

The platform was written as though every model were a woman. HBA's are men
and women, so 57 strings a person reads and 998 sites in comments, docstrings,
ADRs and plans had to change. That is far too many to hand-write and exactly
the shape of job a find-and-replace ruins quietly.

**Cause, four times over.**

1. **`her` is two different words.** `her month` is possessive and `lets her
   check it` is not. A rule that decided from the *following* word got 979
   right and 19 wrong, all of the same shape: `her` as a verb's object with a
   bare infinitive after it — *lets her check*, *tells her it*, *stop her
   joining*, *gives her no way*. They read as `their check`, `their it`.

2. **A wrapped comment hides the verb.** `she` at the end of a comment line
   puts its verb behind a `#` or `*` on the next line. The rule looked at the
   next word, saw a marker, and left the verb alone: `they is meant to do`.
   Sixteen sites, four of them broken this way. Found before applying, by
   grepping for the pattern rather than by reading the output.

3. **A quotation is not prose.** Three passages quote somebody verbatim —
   HBA's own *"nothing is taken from her and nothing is added"*, the business
   on what creates a model, and a bug report quoting what the screen said at
   the time. Rewriting a quote is not a copy change, it is a false record.
   Restored, and now marked as quoted.

4. **The transform could not see the test names.** It only ever edits inside a
   comment or a docstring, so 31 functions still called
   `test_unverified_targets_never_read_as_her_failure` sat above docstrings
   that now said *they*. Worse than either alone. Renamed by hand, along with
   the assertion messages and two local variables called `hers`.

**Fixed** by treating the transform as a draft and auditing its output: a
script that flags every `their` followed by a word that cannot start a noun
phrase, and every `them` followed by a word that can only be one. That is what
found the 19; reading 801 changed lines would not have.

**Worth recording** as the rule this cost: **a bulk rewrite is a draft, and the
audit is a separate program, not a read-through.** The check has to be
mechanical and independent of the transform, because the transform's own logic
is exactly the thing under suspicion. Also: `git checkout` the moment a
formatter is involved. Running Prettier over the seven changed screens reflowed
lines the copy change never touched and turned 89 insertions into 266 — the
same unreviewable-diff problem the two-pass split existed to avoid.

---

## `railway service scale` adds a region, it does not move one

**Symptom.** Moving the database to Amsterdam with the obvious command:

```
railway service scale --service Postgres --environment staging eu-west=1
```

Railway answered:

```
regions:    EU West (1) · sfo (1)
replicas:   2 replicas configured
```

Two replicas of a **database**, in two continents, sharing one volume that can
only ever attach to one of them. Not what was asked for and not a sane state
for Postgres.

**Cause.** The argument is `REGION=REPLICAS`, and it sets the count for the
region named and leaves every other region alone. It reads like *move to EU
West* and means *also run one in EU West*. For a stateless web service that is
a legitimate scaling operation; for a service with a volume it is not.

**Fixed** by naming both regions in one command, so the old one is emptied in
the same operation as the new one is filled:

```
railway service scale --service Postgres eu-west=1 sfo=0
```

**Worth recording** for the reason it cost nothing: **staging went first.** The
bad state existed for eighteen seconds on a database nobody depends on, and
the production command was written correctly the first time because staging
had already been wrong. A rehearsal environment is only worth having if it is
actually used before the real thing, on the same day, with the same commands.

Two smaller notes from the same operation, both worth knowing before the next
one:

- **`railway ssh` puts its banner on stderr**, so `railway ssh <svc> "pg_dump
  ..." > file.sql` produces a clean dump. Verified with a schema-only probe
  before trusting it with 225 MB of payroll data.
- **Multi-statement `psql -c` over `railway ssh` silently returns only the
  first result**, and quoting a query with inner single quotes loses it
  entirely. Comparing two `pg_dump` outputs is both easier and a stronger
  check: production came through the migration with 22 tables and 6,464 → 6,466
  rows, the two new rows being a Shopify webhook that arrived mid-window.

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
| A late order is paid its commission even where its own month paid a guarantee | Small, in the model's favour; bought an explainable rule | 0029 |

---

## How to use this file

**When something breaks unexpectedly, read this first.** If the failure is
here, the fix is here too.

**When it is not here, add it** — with what it looked like from outside, not
only what the cause turned out to be. The next person will meet the symptom
before they meet the cause.
