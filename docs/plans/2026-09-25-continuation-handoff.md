# Where the work is — 25 September 2026 (batch J)

**Replaces `2026-09-24-continuation-handoff.md`**, which is kept with a banner
for its record of batches C-I. Nothing was deleted.

## The exact position

| | |
|---|---|
| **Branch** | `repair/batch-2` |
| **Current head** | run `git rev-parse --short HEAD` (a document cannot hold the hash of the commit that adds it) |
| **`origin/main`, `origin/production`** | not touched by this batch; read them with `git ls-remote --heads origin main production` before describing them |
| **Migration head** | `d4e7a2c90003` (staff preferences, batch J); before it `c3d51e7a0002` |
| **Backend** | the full runner at the end of batch J - see *Checks* below for the result |
| **Frontend** | 460 tests, 27 files; `npm run build` green |
| **Where this ran** | a cloud container, Linux, Postgres 16 on 5433 created for the session (`hba_platform_test`, designated disposable inside itself; `hba_browser` for the browser). `.venv/Scripts` is a symlink to `.venv/bin` so the documented commands work unchanged. |

## Standing restrictions, still in force

- **No merge. Separately, no deployment.** Two permissions; neither given.
- **Historical finalisation locked.** No production data read.
- **No destructive fixture against staging or production.**

## Batch J - what shipped (25 September)

The owner's scope: finish the approved list in bounded groups, Shopify
refresh first. Record, reference-to-code mapping and evidence for each item:
the *Batch J* sections of `docs/repair/batch-2/visual/CHECKLIST.md`;
pictures and measured values in `docs/repair/batch-2/visual/shots/batch-j/`
(`checks.txt`); the capture script is `batch-j.mjs`, and
`simulated_shopify.py` runs the app against a simulated shop.

| Item | What | Commit |
|---|---|---|
| 17 | *Refresh now* / *last successful refresh*: the reconciliation sweep brought forward; accepted is not refreshed; failure keeps the last success; one job however many clicks | `91e6700` |
| 9 | Admin Targets: the export's words, confirmation kept separately, the export's column widths, the guarantee label. **Defect fixed**: saving the grid un-confirmed every unchanged row | `3b68909` |
| 10 | Record payment: **premise corrected** - the export records on its own view too; subtitle and note aligned to `vRecord` | `9498285` |
| 14 | Contact and shipping as the export's form, contact details kept apart from her sign-in; Sizing 15px; start 12.5px | `5aef3c8` |
| 5, 6 | Portal Home chips as pills; the guarantee sentence behind the ⓘ | `2eec570` |
| 11 | Settings switches saved per account and obeyed (weekly reminder email; Home notices behind the hidden line); audit trail in sentences. Migration `d4e7a2c90003` | `0faae31` |
| 12 | Roster and Products rows as the export's buttons; Table/Cards toggle removed | `4b16c4d` |
| 13 | Admin Home chart in the export's frame, labels outside the plot | `6bfac12` |
| 15 | Terms editing: fonts verified (already right), dead CSS removed, footnote | `459a8ab` |
| 16 | Products: the order on each coverage row, the shipment record, message presets | `e6cffc5` |
| 19 | Reopening route and screen removed; history and corrections kept | `72d61b3`, `fc54292` |
| 30a | `SETTINGS_ENCRYPTION_KEY` runbook; a malformed key named as such | `29df94e` |
| 31a | Import comparison verdict three-way: limited access is **inconclusive** | the commit after `29df94e` |

## Remaining implementation (the one list, in its order)

- **3** Ranking names the other models (decision F in the list's own words).
- **8** (remainder) the roster's invitation row opens the invitation.
- **14** the export's *More actions* card on the profile (ours archives
  elsewhere) - not in item 14's wording; noted, not started.
- **15a** terms editing: choose an arrangement before a month (found in J).
- **19a** the worker blocks the web server while a job runs (found in J).
- Verification items 20-29 unchanged: *Attributed orders* layout, the
  export's blank order view, receipts, earnings line names on a guarantee,
  images, printing, staging exercises, real data, devices, old
  `payment-record` shots.

## Remaining verification

- **Full backend runner** - result in *Checks* below.
- **Release gates** (`CLAUDE.md`): reconciliation on an authorised restored
  copy; migration/rollback rehearsal for `b1f0a40c0001`, `c3d51e7a0002`,
  `d4e7a2c90003` with the key cases (`docs/runbooks/settings-encryption-key.md`).
- **Order-import completeness on real data** (31a): not run; needs the
  owner's go-ahead for production and a working route into Railway.
- **Staging**: nothing in batch J has been seen on staging.

## Found in batch J, not fixed (in the list)

- **19a** - the worker runs synchronous jobs in the web server's event loop,
  so no request is answered while a job runs (seen: the status request waited
  for a 5-second simulated sweep).
- **15a** - see above.
- The staff routes had no catch-all: any unknown address was a blank page.
  **Fixed** (`fc54292`).

## Decisions not to reopen (added in J)

- **Recording a payment is its own view**, as the export's `openRecord`
  pushes `record`. Item 10's *on the detail* came from a sweep pair that
  compared our form with the export's detail.
- **The email on a model's profile is her sign-in**, shown as *Signs in
  with*, never an input on the contact form.
- **An unchanged target row is not a re-recording**: its confirmation, *Last
  updated* and audit stand.
- **Appearance switches are per staff account, absent means on.**
- **An import comparison with limited access is inconclusive**, whatever it
  found.
- Earlier decisions (the 24 September handoff's list) all stand.

## What I got wrong, so the next session does not repeat it

- **Took a checklist premise as the export's.** Item 10 said the export
  records on the detail; its code pushes a separate view. Read the export's
  script, not an earlier reading of it, before building to an item.
- **Wrote a claim about behaviour before checking it**: that an old reopen
  bookmark would land on "the app's unknown-address handling". It rendered a
  blank page. Checked, then fixed.
- **Measured the export's chart labels as if they rendered.** They never do
  in the served prototype (`{{ }}` in SVG attributes); placement came from the
  markup.
- **Left a stale app process running after a backend change** and read its
  answers as the new code's; restart the app (`simulated_shopify.py`) after
  every backend edit before a browser check.
- **Grepped the built bundle** (`app/web`) by accident; exclude it.
