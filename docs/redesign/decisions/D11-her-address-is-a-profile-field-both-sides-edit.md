# Decision — D11

**Owner's question** (not in the original list; it arose when Phase 03 asked
whether the shipping address was a Shopify fact or a profile field):
Who owns a model's shipping address, who may see it, and who may edit it?

**Owner's actual answer**, 10 September 2026:

> It's a protected data for the models. But the admins can see it because these
> are the data that will be used when creating their orders. So her address is
> the one that we use to put inside the order details. So it's accessible from
> both sides and the models and admins can edit it.

**Status:** confirmed.

---

## What this changes, and it is not small

**I had this backwards.** The 02B report said:

> Shipping address is still not collected. A05 names it; it belongs with
> recipient matching in Phase 03, where a shipping address is a Shopify fact
> rather than a profile field.

It is not a Shopify fact. **HBA types it into the order.** The shipping address
on a parcel sent to a model is HBA's own copy of her address, entered by
whoever creates the order in Shopify — which means the platform is the source
and Shopify is the copy, not the other way round.

That inverts the direction of `W03`'s matching. The rule reads:

> Shipping-address phone identifies the recipient; Shopify customer identity may
> be Mena's. Do not match against customer phone/email instead.

Still correct, and now for a better reason. The shipping phone is not a stranger's
data being reverse-engineered into an identity — **it is a value HBA put there
from a record HBA holds.** Matching compares the platform's stored phone against
the phone the platform's own staff typed. That is a far stronger basis than the
package assumed, and it explains why the rule works at all.

## What it settles

| | |
|---|---|
| **Where it lives** | On the model's profile, in the platform. Not derived from Shopify. |
| **Who reads it** | The model, and staff. Staff need it because they type it into an order. |
| **Who writes it** | **Both.** Unlike measurements (A05, model-only), this is edited by either side. |
| **Why staff may** | She may give it once and move; the person shipping to her needs the current one and should not have to ask her to update it before a parcel can go out. |

**It is her private data.** Staff see it because they use it, not because it is
public — the same standing a payout destination has, and it belongs under the
same care: not in generic logs, not in unrelated payloads, and never in the
commission order index (§10.2).

## Affected rules, APIs, migration and checks

- **A05** — marketing needs phone, contact/email and shipping information. This
  is the shipping half, and it is now placed.
- **W03** — recipient matching. Its input is this field. Normalisation, ambiguity
  and preserving links across a phone change are unchanged; what changes is that
  the left-hand side of the comparison is a record HBA maintains rather than a
  guess.
- **Migration** — additive columns on `affiliate_profile`, in **Phase 03B**
  where matching is built. Not 03A, which is catalogue ingestion and does not
  read them.
- **The §10.2 boundary is untouched.** A shipping address on a *profile* is not
  customer PII in the *commission index*, and the structural test that keeps
  `order_index` and `attributed_order` free of names, addresses, phones and
  emails still applies exactly as written. The restricted recipient path
  `BACKEND_CONTRACTS.md` describes is still restricted; this decides where its
  left-hand side comes from.
- **Checks:** AC04, AC08, AC17, AC23.

## What this does *not* settle

**Shopify's protected customer data access is a separate question and is still
open.** The owner has answered HBA's policy — who inside HBA may see and edit an
address. Whether Shopify's Admin API will *return* `shippingAddress.phone` to
this app depends on Shopify's protected customer data approval for the app, not
on HBA's internal rules.

Those two are easy to conflate and expensive to conflate. **The engineering fact
must be established against the real shop before 03B relies on it**, and the
platform already has the route that answers it (`/api/operations/order-facts`).

## Required implementation phase/batch

**03B**, with the recipient matching it feeds. Recorded here because it arrived
during 03A and changes what 03B is.
