# 0061. A product can be assigned to a model by hand

**Status:** Accepted
**Date:** 2026-10-15
**Amends:** D05 (only zero-priced orders fill the wardrobe), W02 (the product's coverage)

## Context

On 15 October 2026 the owner asked to assign products to models by hand.
Not every piece a model has reaches her in a gift order: models sometimes
collect a piece from the warehouse, and no Shopify order records it. Until
now the wardrobe and a product's *Model coverage* were built only from
zero-priced orders matched to her (D05), so such a piece was missing from both.

## Decision

On a product's page, *Model coverage* has an **Assign manually** button for
anyone who may manage models. Staff tick the models who have the product,
optionally with the size, and save.

- Each becomes **Received** for that product in the roster, in her
  wardrobe, in the catalogue's coverage count and for feature requests
  (W10). It shows as *Assigned manually* instead of an order number.
- **A model is counted once.** If a parcel already says she received it, the
  parcel is what is shown. If her parcel is still on its way or failed, the
  manual assignment wins and the parcel stays as history.
- Only models who have not received it are offered. House accounts are
  refused.
- **Remove** takes a manual assignment back. Parcels are never touched:
  what an order carried is Shopify's record.
- Both are audited on her (`affiliate.wardrobe_added`,
  `affiliate.wardrobe_removed`).

Stored in a new table, `manual_wardrobe_item`: one row per model and product
(migration `e4a7c1d50016`).

## Consequences

- The wardrobe is no longer only Shopify's record. A hand assignment is
  HBA's word that she has it, and nothing checks it against stock.
- A new migration joins the release gate's rehearsal list. It creates one
  table and touches nothing existing; downgrade drops it and the assignments
  with it.
