# 0076. How Production moves in

**Status:** Accepted — owner, 7 November 2026 (Batch 4.1 plan approved; technical choices delegated to the lead engineer).
**Date:** 2026-11-07
**Amends:** ADR 0069 decisions 2, 3, 4 and 8. Everything else in ADR 0069 stands.

## Context

The owner exported Production's source, data and files from ChatGPT on
2 November 2026 (site version 22). Reading it in full showed four things ADR
0069 had assumed differently on 25 October:

1. **Its data is not one document.** It is a SQLite database of about forty
   tables, thirteen with rows. `/api/state` assembles its answer from them,
   computing values and inventing three stages per order.
2. **There is no revision check.** `revision` is the time of the newest
   activity entry. The screens poll every five seconds and on focus, and say
   "A teammate's change was synced" when it moves. Saves send no revision, so
   two people saving at once means the later save wins.
3. **It answers seven addresses, not five**: also order photos and sample
   photos.
4. **About half its screens show content written into the code**, some of it
   people's names, and the repository is public.

On 7 November the owner set three requirements: Production's screens, functions
and experience stay exactly as they are; Production's people sign in with the
platform's own sign-in; the backend may be rebuilt freely.

## Decision

1. **Tables, not a document.** Production's data lives in `production_` tables
   in HBA's Postgres (ADR 0066): orders, products, suppliers and their
   categories, phases, tasks, samples, QC checks, activity, documents, order
   stages and stage updates, and the fixed content. Only tables the screens
   read or write are made; the empty ones nobody writes are not. Settings rows
   the old app used as tables (drop phases, which phase an order is in, the
   tracker model) become columns and a table of their own.
2. **The platform answers every request the screens make, the same way.**
   Same fields, same words, same refusals, same quirks the screens rely on
   (an order edit rewrites every field; an order's code may be written with or
   without `HBA-PO-`; a task is confirmed by its latest confirm or reopen).
   The revision stays the newest activity time, and the later save still
   wins: real conflict protection would need the screens to send a revision,
   which would change them. Every change also writes an `audit_event` in the
   Production department (ADR 0008, ADR 0067 decision 7). The ten one-time
   data fixes the old server ran on every read are not ported; the exported
   data already holds their result.
3. **The screens come in with the smallest edits that let them live here,
   and none that a person would see**, kept in `production-ui/` with its own
   Vite build (exact versions, its own lockfile, no Next.js, Vinext,
   Cloudflare or Drizzle):
   - their addresses move under `/production/…` and their requests under
     `/api/production/…`, because `/payments`, `/settings` and `/users`
     already belong to HBA;
   - three Next.js modules (`link`, `image`, `navigation`) are small local
     stand-ins; the Geist fonts are the exported files, served locally;
   - **the fixed content comes from the database, not the code**: the lists
     and the few sentences that name people are imported into
     `production_fixture` and loaded before the first screen draws, so every
     screen shows what it shows today and no name is committed;
   - ChatGPT's sign-in parts go (decision 4).
   Each edit is listed in `production-ui/CHANGES.md`.
4. **Sign-in is HBA's.** Production's own accounts, passwords and sessions are
   not imported and its sign-in code is not ported. Opening `/production`
   without an HBA session goes to HBA's sign-in; without Production access, to
   HBA's start page. Production's "Team account" page shows the HBA account
   and signs out of HBA. The "Sign in to edit" box goes, as the approved frame
   draws.
5. **Production's access, in Team and access** (ADR 0067). The ladder fits
   except QC, which the old app kept apart from editing orders. Production
   alone offers a fifth level:
   - **Viewer** — reads everything.
   - **QC** — reads everything and records QC checks and documents.
   - **Staff** — orders, phases, tasks, samples, photos and documents.
   - **Manager** — Staff and QC, plus suppliers and the supplier portal.
   - **The owner** — all of it, and approving a supplier payment.
   Today's two accounts map to Staff and QC; the owner stays the owner. The
   other departments' rows are unchanged.
6. **The frame is an HBA page holding Production in a same-origin frame.**
   `/production/…` is HBA's page: the 64-pixel strip of the approved mockup,
   and Production filling the rest from `/production-app/…`. The two
   documents share no styles, which is what ADR 0069 decision 2 asks for, and
   the address bar follows Production's own navigation. ADR 0069 rejected
   showing the *ChatGPT* site in a frame because its data, sign-in and
   hosting stayed outside the platform; none of that applies to a page the
   platform serves itself.
7. **Money.** The order editor's target cost keeps working and is stored as
   integer piastres (ADR 0002); the screens see pounds as before. Approving a
   supplier payment stays the owner's alone and is audited; nothing creates
   supplier invoices yet, so it has nothing to approve. Joining Production's
   costs to Finance, and the Cairo month, wait for their own decision, as
   ADR 0069 decision 8 says.
8. **Supplier accounts are Batch 4.1b.** The supplier portal today is one
   fixed order that only the owner submits; it keeps exactly that until
   suppliers get accounts that reach only their own work.
9. **Activity history comes across without IP addresses or browsers.**

## Consequences

- One more Vite build in the image and in CI, pinned like HBA's (ADR 0016).
- The data import is a one-off script run against a private export kept
  outside the repository; it is rerun from a fresh export at switch-over and
  reconciled count by count.
- Production's screens and HBA's frame are two documents. Ctrl K inside
  Production searches Production; HBA's search is the strip's button.
- A person holding both QC and Staff work is given Manager.
