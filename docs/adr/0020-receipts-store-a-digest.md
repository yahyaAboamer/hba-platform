# 0020. Event receipts store a digest, not the payload

**Status:** Accepted
**Date:** 2026-08-23

## Context

`integration_event` is the immutable receipt of everything an external system
sent us. Append-only, enforced by database trigger (ADR 0008) — `UPDATE`,
`DELETE` and `TRUNCATE` are all refused, to us as much as to anyone.

The obvious design stores the full webhook body as JSONB. Writing
`docs/limits.md` forced the arithmetic:

> ~30,000 orders a year × ~3 webhook events each × a few KB each
> ≈ **270 MB a year**, in a table nothing can delete from.

Free-tier Postgres offers 500 MB to 1 GB. Between year two and year three,
writes start failing with a disk-full error. Webhooks return 500, Shopify
retries and eventually stops, and **orders quietly stop arriving**. Nothing
names the cause.

The append-only guarantee turns a storage decision into a permanent one. That is
the trap: normally you store generously and prune later, and here there is no
later.

## Decision

The receipt stores **SHA-256 of the canonical payload**, plus `entity_id` — the
order the event is about. Not the payload.

The receipt's job is to prove an event arrived and to deduplicate redeliveries.
Both need an identity, not a copy.

**Reprocessing does not need the stored body.** Shopify is the source of truth
and the order can be re-fetched by id at any time. Keeping our own copy would be
caching the authoritative system in a table we cannot prune.

The digest is kept rather than dropped entirely because it earns its 64 bytes:
it is the only way to notice that a sender reused an event id for **different
content**. That is reported as `event_content_changed` rather than passing in
silence.

## Consequences

Roughly 270 MB a year becomes roughly 10 MB. The table stops being a liability.

**A webhook body is not recoverable after the fact.** A handler that needs
something from the payload must take it while processing; the receipt will not
hold it afterwards. This is the real cost, and it is accepted because the same
data is one API call away.

Diagnosis of "why did this order get the wrong value" uses `order_index` and
Shopify, not the receipt. The receipt answers a narrower question — *did it
arrive, when, and was it the same thing twice* — which is what it was for.

## Alternatives considered

**Store the full payload and prune it later.** Impossible by construction: the
table refuses `DELETE`. Pruning would require disabling the append-only trigger,
which is the guarantee the table exists to provide.

**Store the full payload with a scheduled archive to object storage.** A moving
part that must keep running for years, added to solve a problem better solved by
not creating it. The archival path stays documented in `docs/limits.md` as the
escape hatch if the ceiling is ever met anyway.

**Store a truncated prefix of the payload.** Bounded, and useless — the first
2 KB of Shopify JSON is metadata, and the truncation point would land somewhere
different on every schema change.
