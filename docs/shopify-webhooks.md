# Shopify webhooks: what they are and how to switch them on

## What a webhook is

Two ways to find out that an order happened.

**Polling** — ask Shopify "anything new?" every few minutes, forever. Mostly the
answer is no, and when the answer is yes you learn about it minutes late.

**A webhook** — Shopify calls *us* the moment something happens. One HTTP POST
to a URL we publish, carrying the order.

"Registering a webhook" is telling Shopify: *when this kind of thing happens,
post it to this address.* Nothing more.

## Why it has to be signed

The address is public. Anyone who guesses it can post to it, and a fake order
"delivered" would become real commission.

So Shopify signs every delivery: it takes the exact bytes of the message, mixes
them with a **shared secret** only Shopify and this platform know, and puts the
result in a header. We repeat the calculation. If the two match, the message is
genuinely from Shopify and has not been altered on the way. If not, it is
refused with a 401 and **nothing is recorded**.

That secret is `SHOPIFY_WEBHOOK_SECRET`. Without it, every delivery is rejected
— the platform fails closed rather than trusting anything that arrives.

## What happens when one arrives

The endpoint is deliberately lazy. Shopify gives a webhook a few seconds to
answer and retries anything slower, so doing real work here would produce
duplicate deliveries. Instead:

1. Refuse anything over 1 MB, or that fails the signature.
2. Write an immutable receipt — proof this delivery arrived.
3. Queue one job to fetch the order properly from Shopify's API.
4. Return 200.

**The webhook body is never trusted as data.** It tells us *which order
changed*; the worker then asks Shopify what that order actually is. A signed
message could still be a replay, and Shopify's own payload can be behind its
API.

Shopify sends `orders/create`, then `orders/updated`, then `orders/fulfilled`
for the same order within seconds. Each is recorded separately — they are
separate facts — but they collapse into **one** sync job, because fetching the
same order three times gives the same answer three times.

---

# Switching it on

Two things are needed, in this order.

## 1. Set the secret

`SHOPIFY_WEBHOOK_SECRET` must be set on the Railway service, matching the app's
signing secret in the Shopify Dev Dashboard.

Check it took effect:

```
GET /api/health/ready  →  checks.shopify.webhooks_configured: true
```

**If that says `false`, every delivery is being rejected** and no orders are
arriving. This is why it is reported there rather than left to be discovered.

## 2. Subscribe to the topics

Subscribe in the **Shopify Dev Dashboard**, under the app's webhook
configuration — not through the API.

That distinction matters: subscribing over the Admin API requires the
`write_webhooks` scope, and **this platform never requests a write scope of any
kind** (ADR 0015). A leaked read-only token exposes data; a leaked write token
lets someone alter orders and discounts. Declaring the subscriptions in the app
configuration achieves the same thing with no write access at all.

Point every topic at:

```
https://<the platform's domain>/api/webhooks/shopify
```

Topics to subscribe:

| Topic | Why |
|---|---|
| `orders/create` | A new order exists |
| `orders/updated` | Almost everything else — including payment |
| `orders/cancelled` | Cancellation removes it from the commission base |
| `orders/fulfilled` | Delivery is when commission is earned (ADR 0012) |
| `orders/partially_fulfilled` | Part of a multi-item order shipped |
| `refunds/create` | A refund changes what the customer actually paid |

Anything else that arrives is acknowledged and recorded, but generates no work.
Subscribing to extra topics is harmless; it is not useful either.

## 3. Check it worked

Place a test order, or use the Dev Dashboard's "send test notification".

```sql
select topic, entity_id, received_at from integration_event order by id desc limit 5;
select kind, status, payload from background_job order by id desc limit 5;
```

A receipt with no job means the topic is not one we act on. **No receipt at all
means the delivery was rejected** — check the logs for `ANOMALY
webhook_rejected`, which reports whether the secret was configured.

---

## If webhooks stop

The platform does not depend on them for correctness. Webhooks make sync
*prompt*; the reconciliation sweep makes it *complete*. If deliveries stop
entirely, orders still arrive — late, in a batch, rather than within seconds.

Concretely: **every 30 minutes the worker re-reads every order Shopify says was
updated in the last 48 hours.** A missed webhook costs a delay of up to half an
hour, not a missing order. The sweep is what closes a deploy window, a dropped
delivery, or a rotated secret nobody noticed.

That is deliberate. A webhook is a delivery mechanism, not a source of truth,
and building on the assumption that every one arrives is how a missed delivery
becomes a missing month of commission.
