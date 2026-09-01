# Running the platform

What to look at, in what order, when something seems wrong — and the few things
that have to be done by hand.

Everything here needs an account. Nothing operational is public.

---

## The one page to check first

```
GET /api/operations/sync
```

```json
{
  "shopify_configured": true,
  "webhooks_configured": true,
  "orders_indexed": 18422,
  "last_order_synced_at": "2026-08-23T18:42:11+00:00",
  "last_event_received_at": "2026-08-23T18:42:09+00:00",
  "jobs": {"pending": 0, "running": 1, "succeeded": 9120, "failed": 0},
  "recurring": {
    "shopify_reconcile": {
      "last_succeeded_at": "2026-08-23T18:15:00+00:00",
      "next_due_at": "2026-08-23T18:45:00+00:00",
      "scheduled": true
    }
  }
}
```

**How to read it:**

| What you see | What it means |
|---|---|
| `webhooks_configured: false` | **Every delivery is being rejected.** No orders are arriving live. Set `SHOPIFY_WEBHOOK_SECRET`. |
| `last_event_received_at` hours old | Webhooks have stopped. The sweep is still covering you; see [`shopify-webhooks.md`](shopify-webhooks.md). |
| `failed` above zero | Work that did not happen. Look at it — see below. |
| `recurring.*.scheduled: false` | **The safety net is off.** The worker is not queueing recurring work. |
| `last_succeeded_at` over an hour old | The sweep is not completing. Check failed jobs for `shopify_reconcile`. |

The last two matter more than they look. Recurring work is queued by the worker
itself, so if the worker stops, it stops too — **with no error, because nothing
failed.** Orders keep arriving by webhook and everything looks normal.

---

## When work did not happen

```
GET /api/operations/failed-jobs
```

Returns the last 100 failures with the payload, the attempt count, and the last
error. A failed job is **never deleted** — it is the record that work did not
happen.

To make one run again, set it back to `pending`:

```sql
update background_job set status = 'pending', attempts = 0, run_after = now()
where id = 412;
```

Fix the cause first. A job that failed five times will fail a sixth.

---

## When an order is missing

In order:

1. **Is it indexed?**
   `select * from order_index where shopify_order_id = '5123456789';`
2. **Did a webhook ever arrive for it?**
   `select * from integration_event where entity_id = '5123456789';`
3. **Did a job try?**
   `select * from background_job where payload->>'order_id' = '5123456789';`
4. **Search the logs for `ANOMALY`** — the reason is usually already written
   down. Every name is explained in [`limits.md`](limits.md).

If there is no receipt at all, the delivery was rejected — look for
`ANOMALY webhook_rejected`, which reports whether the secret was configured.

The sweep re-reads the last 48 hours every 30 minutes, so an order missed by a
webhook appears within the half hour without anyone doing anything.

---

## Codes nobody owns

```
GET /api/operations/unregistered-codes
```

Discount codes appearing on real orders, most-used first. A code here that
belongs to no affiliate is **sales being attributed to nobody** — usually a code
created in Shopify without being registered on the platform.

---

## The go-live month — set this before the first real payroll

```
GO_LIVE_MONTH=2026-09
```

A Railway service variable. **Chosen by HBA on 26 August 2026: September 2026 is
the first month the platform is responsible for paying.**

Everything before it is `historical`: imported, visible, and **never payable**.
January to August 2026 were settled outside the platform, and without this line
they would all appear as unfinalised debt.

Those months show **sales only, never a commission figure** (ADR 0014). March's
rates exist in the old system and in somebody's memory; applying today's rates to
last March would be actively misleading, and reconstructing them by hand invites
errors nobody could later verify. They are labelled *"Settled before the platform
— commission not calculated."*

**Blank blocks every approval**, with `go_live_month_is_not_configured`. That is
deliberate: a default would silently make eight months of already-paid orders
look approvable, ready to be paid a second time.

**Do not move it once a month has been approved.** Shifting it would turn
approved months into historical ones, or historical months into payable ones, and
neither has a defined behaviour.

---

## Before believing any earnings figure

```
GET /api/operations/order-facts
```

Asks Shopify what it will actually tell us about **delivery**, **returns** and
**refunds** — the three facts Phase 4 turns into money.

**Read `delivery.signal` first.** It has three answers, and they need different
actions:

| Signal | Meaning | What to do |
|---|---|---|
| `present` | Shipped orders do reach a delivered status | Nothing. This is the expected answer. |
| `absent` | **Not one shipped order has ever been delivered** | **Stop.** See below. |
| `unreadable` | Shopify refused the fields, or no shipped orders to judge from | Read `rejected` — the message usually names the field or a missing scope |

### Why `absent` matters more than it looks

A model earns when their order is **delivered** (ADR 0012), and that fact is read
from Shopify (ADR 0023). If nothing ever reaches delivered, every order stays
`pending`, every month calculates to **zero earned**, and it looks exactly like
a month with no sales. Nothing errors. The first person to notice would be a
model asking why they were not paid.

Whatever writes that status into Shopify lives outside this codebase and can
stop without a symptom — the same shape as the auto-cancel automation the old
dashboard depended on. **So this is not a one-time check.** Read it again
whenever a month comes out lower than expected.

*Do not respond to `absent` by treating `FULFILLED` as delivered.* That pays
commission on every parcel a customer refuses at the door, which for
cash-on-delivery through Bosta is exactly the loss ADR 0012 exists to avoid.
It is a decision about real money and belongs to the business.

`already_indexed` is computed from the platform's own database and works even
when Shopify is unreachable, so there is always some answer.

Administrator only, and not something to poll — it runs several sampled queries
against Shopify.

---

## Checking a code before approving an affiliate

```
POST /api/operations/verify-code   {"code": "NOUR10"}
```

Confirms the code exists in Shopify before anyone is approved against it. A
code that does not exist attributes nothing, silently, until someone notices
months of missing sales.

`exists: false` is a normal answer, not an error — it is what a typo looks like.

**This needs the `read_discounts` scope.** Without it the endpoint returns 403
naming the scope, rather than pretending the code does not exist. That
distinction matters: "no such code" would have someone re-typing a perfectly
good code while the real fix is one setting in the Shopify Dev Dashboard.

**It reports the customer discount, never a commission rate.** A creator may
give customers 10% off while earning 5%. Guessing one from the other would be
wrong exactly when it mattered.

---

## The historical import

Run **once**, to load orders from before the platform existed.

```
POST /api/operations/start-import   {"since": "2026-01-01"}
```

Administrator only. Shopify permits one bulk operation per shop at a time, so a
second request while one is running is refused with 409.

It queues rather than runs: the export takes minutes. Watch it under `jobs` in
`/api/operations/sync`. The job re-checks Shopify every 30 seconds and ingests
the file when it is ready.

**It needs `read_all_orders`.** Plain `read_orders` reaches back only 60 days,
so a January import against it returns nothing at all — and reports
`ANOMALY import_empty` when it does, rather than looking like success.

---

## Reading the logs

Every failure the platform absorbs is one greppable line:

```
ANOMALY job_gave_up attempts=5 job_id=412 kind='sync_order' last_error='...'
```

Search for `ANOMALY`. Each name has an entry in [`limits.md`](limits.md) saying
what it means and what to do about it — and a test fails if a name exists in the
code without one.

---

## If you ever point an uptime monitor at this

**Use `/api/health/ready`, and read the status code.** It answers 200 when the
platform can reach its database and 503 when it cannot.

`/health` and `/healthz` look like health endpoints and are not: every path
that is not `/api/...` is served the app's `index.html`, so both answer 200
forever, including on a platform whose database has gone. A monitor pointed at
either would never tell you anything (docs/limits.md).

## Where the platform runs

Both services, in both environments, run in Railway's **EU West** region
(`europe-west4-drams3a`, Amsterdam). This is not cosmetic: the models are in
Egypt, and the platform spent its first months in California paying roughly
150 ms of pure travel on every request (ADR 0031).

Check it with:

```
railway service scale --service hba-platform
railway service scale --service Postgres
```

**Two rules if you ever change it.**

1. **The app and the database move together, database first.** `DATABASE_URL`
   goes over the private network, so a split leaves the Atlantic between the
   app and every query it makes - far worse than the problem being fixed.
2. **Name both regions in one command**, or you get a second replica rather
   than a move:

   ```
   railway service scale --service Postgres eu-west=1 sfo=0
   ```

Changing the database's region migrates its volume and takes the database
offline for the duration - about a minute at the current size. The app has no
volume and moves with no downtime at all.

Nothing else needs touching: domains, private networking, environment
variables and the Shopify webhook addresses are all unaffected.

## Deploying — staging and production are separate services

Since 2026-08-30 (ADR 0034), **`main` deploys to staging only**, on a
dedicated service, `hba-platform-staging`, at
`hba-platform-staging-staging.up.railway.app`. **Production deploys from its
own `production` branch**, on the original `hba-platform` service, at the
domain everyone already knows: `hba-platform-production.up.railway.app`.

**To ship something to production**, once it has been checked on staging:

```
git checkout production
git merge --ff-only main
git push origin production
```

Railway redeploys `hba-platform` automatically from there. Nothing else
needs touching - variables, region, Postgres are all exactly as they were.

Note which way round this is, because it is the point: `main` is the default
branch, so a pull request opened without thinking targets **staging**.
Production takes a separate, deliberate act. Do not invert this.

**`hba-platform-staging.up.railway.app` (no `-staging-staging`) is dead.**
The original `hba-platform` service used to serve it and still has a service
instance sitting in the `staging` environment, because Railway cannot remove
a service from one environment - it exists in every non-fork environment or
none. That instance is switched off rather than deleted: auto-deploy
disabled for staging, domain removed, deployment taken down. Do not revive
it, do not link the old hostname.

> **Never run `railway service delete` against `hba-platform`.** Its help
> text says "Delete a service from an environment." That is not what it does
> here: an `environmentId` only scopes the delete if that environment is a
> *fork*, and neither of ours is. Scoped to staging, it deletes the service
> in **every** non-fork environment - production included, along with its
> public domain, which cannot be reattached. See `docs/limits.md`.

## Backups

A `db-backup-<environment>` service in each environment dumps its own
database once a day at 00:00 UTC (02:00 Cairo) and uploads it to that
environment's `backups` bucket, keeping the newest 30 days in production and
14 in staging (ADR 0032). Nobody has to run this; it is the whole point of it.

**What to check occasionally.** Open the `db-backup-production` service in
Railway and look at its deployment history - each run is one deployment, and
a run that failed shows as one there. There is no other alert for this today.

**To see what is actually stored:**

```
railway bucket list --environment production
railway bucket credentials --bucket backups --environment production
```

The credentials command hands back an S3-compatible access key, secret, and
endpoint. Any S3 browser (Cyberduck, S3 Browser, the AWS CLI configured with
a custom endpoint) can connect with those and list what is there without
needing a Railway login.

**To restore one**, download the object, then:

```
pg_restore --clean --if-exists --no-owner --no-acl \
  --dbname="<DATABASE_URL>" backup-file.dump
```

This overwrites whatever is currently in the target database. There is no
button for this and there should not be - confirm the target URL before
running it, the same way you would confirm before deleting anything.

## What is not automated

- **Starting the historical import.** Deliberate: it is a one-off.
- **Subscribing to webhook topics.** Done in the Shopify Dev Dashboard, not over
  the API, because the API route needs a write scope this platform never asks
  for. See [`shopify-webhooks.md`](shopify-webhooks.md).
- **Alerting.** Nothing pages anyone. The signals are in the logs and in
  `/api/operations/sync`; something has to look at them.
