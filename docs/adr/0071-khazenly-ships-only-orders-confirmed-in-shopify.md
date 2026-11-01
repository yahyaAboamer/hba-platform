# 0071. Khazenly ships only orders confirmed in Shopify, and the platform builds the file that tells it so

**Status:** Accepted
**Date:** 2026-11-01

## Context

Since 29 October 2026 HBA's stock and order fulfilment sit with Khazenly, an
Egyptian third-party warehouse. All stock is at the Shopify location
"Khazenly"; they pick, pack and hand orders to their couriers. Bosta and
E-stebdal are still read by Operations (ADR 0057), but Khazenly now ships.

Khazenly's system is connected to our Shopify. Every order placed in Shopify
appears on their dashboard set to *On Hold* with the reason *Pending
Confirmation*, and they ship nothing on hold. We asked for that so that only
orders the customer confirmed are shipped: the WhatsApp confirmation (ADR
0059) tags each order in Shopify, and the team tags the rest by hand (ADR
0063).

So someone has to tell Khazenly which orders are confirmed. Their dashboard
takes one order at a time, or an Excel file listing Khazenly sales order
numbers with *True* or *False*. Building that file by hand means looking up
each order's tags in Shopify. On 30 October it was built by hand: 152 orders
on hold, 105 confirmed under the rule of the day, and Khazenly's page
accepted the layout. That evening order #31874 was tagged *Confirmed* but
had been cancelled to be edited, and Khazenly still listed it on hold — had
it gone into the file, a cancelled order would have shipped.

Khazenly has no API we can use. A person downloads the *Dashboard – Active
Orders* export from them and uploads the bulk-confirm file back.

## Decision

1. **Operations gets a Khazenly tab** (`/operations/khazenly`), for whoever
   holds `order_ops.view` — the operations manager and the admin, as for the
   rest of Operations. One action: upload Khazenly's *Active Orders* export
   (`.xlsx`); the platform matches each order to Shopify and returns
   Khazenly's own bulk-confirm template filled in with the confirmed ones,
   each `True`, plus a summary. It writes nothing to Shopify or to Khazenly.

2. **The rule (owner, 30 October; not to be reopened).** An order goes into
   the file only if its Shopify tags include *Confirmed* — `Confirmed ✅`
   and `Confirmed✅` both, compared with `operations.services.shopify.
   tag_key` and `CONFIRMED`. Paid orders carry *Confirmed✅* and *Paid*
   automatically, so the same rule covers them.
   - **The compression rule is dropped here.** Orders tagged `compression`
     used to need *Call Confirmed📞* as well; for Khazenly, *Confirmed* is
     enough. The Shopify tab's S6 card still counts compression orders
     without a call; that card is unchanged by this decision.
   - Every other state stays out: *WA Sent 📤*, *No WhatsApp 📵*, *Edit ✏️*,
     *Cancelled ❌*, *Awaiting payment 💳*, or no confirmation tag at all.
   - **Left out, not `False`.** The file holds only `True` rows. An order
     that is not confirmed stays on hold at Khazenly, which is where it
     already is.

3. **Safety exclusions (recommended to the owner with the request).** A
   *Confirmed* order is still left out, and named under its own reason in
   the summary, when:
   - it is also tagged *Cancelled ❌*;
   - Shopify shows it already shipped, wholly or in part
     (`FULFILLED`, `PARTIALLY_FULFILLED` or `RESTOCKED`);
   - it is not among Shopify's open, unshipped orders at all — cancelled,
     closed or shipped. This is the #31874 case. The platform's table holds
     only open, unshipped orders, so these three cannot be told apart; the
     summary says "Not open in Shopify".

4. **The Shopify side comes from `ops_shopify_order`, and only while it is
   fresh.** That table holds every open, unshipped order with its tags and
   number, replaced every 5 minutes by the poller (ADR 0057), so nothing
   calls Shopify while the page waits. Numbers are matched with any leading
   `#` and spaces removed on both sides (`#31840` in Shopify, `31840` in
   Khazenly's *Merchant Order Number*). **If Shopify's freshness is anything
   but *fresh* — stale, failed, never read, not connected — no file is
   built**, and the screen says why. A partial or empty confirmation is never
   produced silently.

5. **A live read is proposed, not built.** The table can be up to 10 minutes
   old. That cuts two ways:
   - an order confirmed in the last few minutes is left out. Harmless: it
     stays on hold and goes in the next upload;
   - an order confirmed and then cancelled or edited in the last few
     minutes could go in. That is the #31874 risk again, narrowed to a
     window of minutes.

   The fix for the second, if the owner wants it, is one Shopify read just
   before the file is built, of only the orders going into it (one query per
   250 orders, by id): tags, cancelled, closed and fulfilment status, with the
   same rule applied again. It would make building the file depend on
   Shopify answering at that moment, which ADR 0057 avoided for pages. Left
   for the owner's decision.

6. **Reading Khazenly's export.** The header row is found by its text — the
   cells *Sales Order: Sales Order Number* and *Merchant Order Number* — not
   by its row or column, because Khazenly's filter lines above it change.
   Only those two columns are read; the recipient's name and amounts are
   never read. A row is an order when its sales order number starts with
   `KH-`. Blank rows and the *Subtotal / Total / Count* footer rows are
   skipped rather than ending the read: the export groups by account and
   status, and a grouped export puts footer rows between groups, so stopping
   at the first one could drop the groups after it. In their place:
   **Khazenly's own grand total (the last *Count* row) must equal the number
   of orders read, or nothing is built.** The file is refused, in words,
   when it is not an `.xlsx`, is over 5 MB (or unpacks to over 50 MB), lacks
   either header, has no order rows, or lists a sales order number or
   merchant order number twice.

7. **Writing Khazenly's template.** The blank template Khazenly gave us,
   which holds no customer data, is kept in the repository
   (`app/modules/operations/services/khazenly_bulk_confirm_template.xlsx`).
   Its *Orders* sheet gets one row per confirmed order from row 2: column A
   the Khazenly sales order number (`KH-HBA-…`, not the Shopify number),
   column B the text `True`, in the column's text format (`@`). The file is
   named `khazenly-bulk-confirm-YYYY-MM-DD-HHMM.xlsx` in Cairo time. When
   nothing is confirmed there is no file to offer, and the screen says so.

   Only two parts of the workbook are rewritten: the *Orders* sheet and the
   list of strings it points to. Every other part — the *User Guide* sheet,
   its picture, the styles — is copied byte for byte. That is a deliberate
   step past "fill it with openpyxl": opening and re-saving a workbook with
   openpyxl rewrites every part, and its own documentation warns that what it
   does not model is lost. openpyxl is still how the export is read.

8. **Nothing about the customer is kept.** The upload is read in memory and
   dropped. The summary names orders only by Shopify and Khazenly numbers,
   as the WhatsApp tab does. The audit trail records who built a file and
   when, how many orders were read and how many were confirmed
   (`order_ops.khazenly_file_built`).

## Consequences

- Confirming orders at Khazenly becomes: export, upload here, upload the
  result there. The person still does both Khazenly steps by hand.
- The file is only as current as the last Shopify read (decision 5). The
  screen shows the time the tags were read.
- An order tagged *Confirmed* that Shopify shows partly shipped is left
  out. If Khazenly is ever meant to ship the rest of a partly shipped order,
  that is a person's decision on Khazenly's dashboard.
- A grouped or reshaped export from Khazenly is read as long as the two
  headers and the grand *Count* are there. If Khazenly drops the *Count*
  rows, the file is still read, without that cross-check.
- Two new dependencies: `openpyxl` to read the export, and `defusedxml`,
  which openpyxl uses when present so that a hostile spreadsheet cannot
  expand into gigabytes of XML.
- If Khazenly changes its template, the copy in the repository has to be
  replaced by hand, and the tests that check its sheets will say so.
- Khazenly's *On Hold* state is not mirrored anywhere; the platform knows
  only what each uploaded export says.

## Alternatives considered

- **Listing unconfirmed orders as `False`.** Their page accepts it, but it
  tells Khazenly nothing it does not already do with an order on hold, and
  a wrong `False` is one more thing to undo. The owner chose `True` only.
- **Keeping the compression rule.** Dropped by the owner: *Confirmed* is
  the answer, however it was reached.
- **Reading Shopify live while the page waits.** ADR 0057 chose its tables
  so that a slow Shopify never holds a screen; decision 5 proposes the one
  narrow live read that would remove the remaining risk.
- **Storing the upload so the file could be downloaded later.** It holds
  customer names. The file comes back in the same answer as the summary,
  and nothing is stored.
- **Filling the template with openpyxl.** Rewrites the *User Guide* and its
  picture on every save (decision 7).
- **Stopping at the first footer or blank row.** As the request described
  it; replaced by skipping them and checking Khazenly's own count
  (decision 6), because a grouped export would otherwise lose orders without
  a word.
