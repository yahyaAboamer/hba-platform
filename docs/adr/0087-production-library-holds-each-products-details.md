# 0087. Production's Library holds each product's own details

**Status:** Accepted
**Date:** 2026-11-21

## Context

On 21 November 2026 the owner asked for an "HBA library": every HBA product,
drafts included, and on each one everything about making it - COGS, colour,
size chart, design and design size - typed in by him, with whatever Shopify
already knows taken automatically.

Until now those details lived only on a production order (its Product card,
build plan 2026-11-19): the colour code, fabric, print or embroidery and its
width, pattern files and size charts. A second run of the same style started
from nothing, and a style had no page of its own.

The platform already copies every Shopify product into `product` and
`product_variant` (title, status including draft and archived, one photo, and
the sizes with their SKUs). HBA keeps one colour per Shopify product; sizes are
the variants (W01).

The platform's Shopify app holds `read_products` but not `read_inventory`
(checked on staging, 21 November 2026), and Shopify keeps a variant's "cost
per item" on its inventory item. COGS therefore cannot be read from Shopify
today.

## Decision

- A **Library** section in Production (`/production/library`) lists every
  product in `product`, active, draft and archived, with its photo, status and
  sizes.
- Each product has **one Library record** (`prod_library_item`, keyed by the
  Shopify product id) holding what HBA types: colour code, fabric, print or
  embroidery type, design width in cm, notes, and the **COGS in the five parts
  an order's target cost uses** (fabric, manufacturing, printing, accessories,
  packaging), in piastres.
- Its files (`prod_library_file`) are **design** files (any file: AI, PSD,
  PNG, PDF...), **size charts** (a photo or PDF) and **pattern** files (any
  file), stored like an order's files.
- What comes from Shopify is shown read-only and is never copied into the
  Library record: the title, status, photo, sizes and SKUs stay Shopify's.
- **COGS is money:** only `production.owner` reads or changes it, as with
  Payments (ADR 0086). Everybody who reads Production sees the rest; the
  details are changed by `production.owner`, files added by `production.edit`.
- A **new order for a Library product starts from it**: the server copies the
  colour code, fabric, print type and width onto the order when the request
  leaves them out, and the New order form fills its target cost per piece
  from the COGS for the owner to keep or change. After that the order's
  details are its own; changing the Library does not change an order.

## Consequences

- One place per style for what it takes to make it; repeat runs start filled.
- The COGS is a typed figure, not a measured one: an order's actual cost
  (its Cost card) can drift from it, and nothing reconciles the two.
- A product deleted in Shopify keeps its Library record only while its
  `product` row stays; the sync does not delete products today.
- Reading the Shopify cost per item would need the app to be granted
  `read_inventory`, which is the owner's call in Shopify, and a decision on
  which of the two figures wins.

## Alternatives considered

- **Reading COGS from Shopify.** Not possible without `read_inventory`; and
  Shopify holds one cost per variant, not the five parts.
- **Keeping the details only on orders** and showing the latest order's as
  the product's. Rejected: a style with no order yet has nowhere to keep
  them, and "latest order" silently changes what a product says.
- **Copying the Library onto an order whenever the Library changes.**
  Rejected: an order in progress must not change under the factory.
