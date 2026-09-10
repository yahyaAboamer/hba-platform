# Decision — D05

**Owner's question:** Should positively priced personal purchases appear in the
same wardrobe, and count as possession for promotion eligibility?

**Owner's actual answer**, 10 September 2026:

> Anything that she bought? Then it's not shown in the wardrobe. We only return
> the products from the orders that have zero price. Anything else we don't
> care about it.

**Status:** confirmed.

---

## What this settles

**The wardrobe is what HBA sent her.** Only orders whose original price was zero
put a product in it. A model who buys something with her own money has bought
something; it is not the platform's business and it does not appear.

It follows directly that **a purchase does not make her eligible for a feature
request** either. W10 gates that on having the product *in the wardrobe* — no
wardrobe entry, no eligibility. There is no second rule to write.

This overrules the recommendation put to the owner, which was to show both with
the provenance in the details. The owner's answer is simpler and it draws the
line in a better place: the wardrobe is a record of what the business gave her,
not an inventory of her cupboard.

## What still gets recorded, and why that is not a contradiction

The gift/purchase classification stays exactly as 03B writes it. W04 asks for
the classification and its order evidence to be preserved, and the answer above
is about **what the wardrobe returns**, not about what the platform knows.

Two reasons that distinction earns its keep:

- A purchase misfiled as a gift, or the reverse, is a question somebody will
  eventually ask about a specific parcel. Throwing the record away makes it
  unanswerable.
- Reversing this decision later becomes a query change rather than a backfill of
  history nobody kept.

Storing it costs a column that already exists. Showing it is what was declined.

## The third state, which the answer does not mention

**`unknown`** — an order whose original price cannot be established. F04 warns
this is real for orders first seen after a cancellation.

Unknown is **not** zero, so under this rule it does not appear in the wardrobe.
That is the safe direction and it matches W04's *unknown original value remains
unknown*: the platform would otherwise be telling a model she owns something it
cannot show HBA gave her. It surfaces in the staff diagnostics instead, where
somebody can resolve it against the real order.

## Affected rules, APIs, migration and checks

- **W04** — classification unchanged, still decided from the *original* net so a
  cancellation cannot turn a purchase into a gift.
- **W08** — the wardrobe shows Received products, then a compact not-received
  area. Both are now gift-only.
- **W10** — feature-request eligibility follows the wardrobe, so it is gift-only
  too. Server-evaluated, as it already had to be.
- **No migration.** `model_shipment.classification` already carries it.
- **Checks:** AC19, AC20, AC21, AC22, AC23.

## What remains unchanged

Everything about attribution. A model still earns commission on every order sold
through her code whether or not she owns the product — W11's *a model can sell
products they never received* is untouched, and was never the same question.

## Required implementation phase/batch

**03C**, which is the batch that builds the wardrobe.
