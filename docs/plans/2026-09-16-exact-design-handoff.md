# Handoff — exact design implementation, 16 September 2026

> **SUPERSEDED, 24 September 2026.** The current handoff is
> [`2026-09-24-continuation-handoff.md`](2026-09-24-continuation-handoff.md).
> Kept because it records how the design work was actually done, which still
> holds. **Four things in it are no longer true:**
>
> - *"Pending orders are not counted by the live rule."* They are.
>   `PENDING_INCLUSIVE` is the live policy and every approval writes it into
>   its snapshot. ADR 0040.
> - *"ADR 0028: a full payout destination goes only through the audited
>   reveal."* Amended by **ADR 0042** on the owner's explicit instruction: the
>   payer sees the whole destination, on the row, on the detail card and on
>   the model's profile. Masking still governs every record.
> - **Blockers 1 and 2 are cleared.** The portal has been seen rendered and
>   the width pass is done — a headless Playwright browser makes its own
>   sessions and sets its own viewport, so neither signing the admin out nor
>   resizing a window is involved. See `CLAUDE.md`, *Looking at screens*.
> - *"Run the suite in fifteen groups of five files."* Superseded by
>   `docs/repair/batch-1/run-suite.sh`, one file per process and resumable.
>
> The counts quoted below (1936 backend, 321 frontend) are the counts of that
> day. They are 2,039 and 363 now.


The standard is `HBA_Exact_Design_Implementation_Prompt.md` at the repo root:
every screen must match its **corresponding element** in the approved
exports — structure, copy, sizes, tones and interactions — not merely use
colours and sizes that appear somewhere in them. Tests passing and a feature
existing are not evidence of that.

**The live record of what is done is `docs/redesign/parity/SCREEN_MATRIX.md`.**
Read it before touching a screen. This file says how to continue.

State at handoff: `main` and `production` level, tree clean, staging and
production deployed. **1936 backend, 321 frontend.**

## How to work a screen (the method that held)

1. **Read the export's markup for the view** — the matrix gives its line range.
   Every element carries its style inline, so the range *is* the specification.
2. **Read the export's data script too** (Admin from line 1646, Portal from
   line 800). Labels, filter names, state words and tones are bound there, not
   in the markup.
3. Rebuild presentation to it; keep the real capabilities and safeguards.
4. Deploy, then **look at the rendered page** and fix what the screenshot
   shows.
5. Update the matrix row with what was actually checked.

## What shipped today

**The portal, all five tabs and every secondary view**: Home (the export's
four states, the chart readout, the payment card), Orders (commission leads,
wrapping filter chips, state pills), Wardrobe (three states in their own
tones), Targets → *Content record*, Ranking (position card and board),
You → a page of rows each opening one thing, *How this adds up* (total inside
the card that sums it), Payment history (*approved, not yet recorded* first;
a transfer titled by the month it paid), Help as cards, and the shell —
header ruled off, 40px avatar, a Back that returns where she came from.

**Admin**: inviting a model is a screen (`/affiliates/invite`) with the
applications and outstanding invitations beside it — the modal is deleted; a
pending application shows *Submitted information* beside *Setup before
approval*; Settings' *Historical setup* has the export's four columns and
names the months nobody can pay for.

New backend: `arrangement` and `since` on `GET /api/me`;
`earliest_terms_month` on the roster. Both tested.

## Blocked, and what would unblock it

1. **No portal screen has been seen rendered.** Signing in as a model in this
   browser signs the admin out of the session the maintainer screens were
   verified in. Needed: a second browser profile signed in as a test model, or
   word that signing the admin out here is fine.
2. **The 1280 / 1440 width pass.** `resize_window` is ignored while the Chrome
   window is maximized — `innerWidth` stayed 1707 through every attempt, and
   only an un-maximized window resized (to 931). Needed: the window restored
   (not maximized) before the next session's width checks. Everything verified
   so far was dark at 1536–1707 CSS px.
3. **Light theme** is verified on **Targets** and the **invite page** only.
   Home and Payments were attempted twice and were still showing *Loading…*
   after five seconds against staging — worth timing on its own before
   concluding anything about them — and the Models capture died in a
   `Page.captureScreenshot` timeout. Screenshot capture on this tab fails
   roughly one time in five; retry once, then move on rather than looping.

## What is left, in order

1. The width and light-theme passes, once (2) is unblocked.
2. Portal visual verification, once (1) is unblocked — and exercising a save:
   payout details, measurements, notification switches.
3. `vShipment` (B5): a one-shipment view; no route exists and the wardrobe
   payload is per model, so it needs either a lookup in that payload or a
   small endpoint. The only export view not built.
4. Exercising the admin writes on staging: a Targets save, record payment, a
   correction, terms apply.
5. Legacy routes in the matrix's section C (`/payroll*`,
   `/affiliates/:id/payments`, `/affiliates/:id/payout-destination`).

## Traps (each cost time this week)

- **One CSS bundle.** A class defined in an admin sheet and a portal sheet
  styles both. `.orders__*` and the shared target bars are scoped under
  `.affiliate` now; `.targets__note` belonged to the maintainer's screen all
  along. Grep the other half before adding a class.
- **The reachability guard reads paths literally.**
  `api.post(\`…/${id}/${what}\`)` scans as `/{}/{}`, which nothing serves, and
  the build fails. Write both paths out.
- **`display:flex` on a `<td>`** takes it out of the row box; put the flex on
  a span inside.
- **`Money` puts its class on the same span as `money`** — write `.money.x`,
  never `.x .money`.
- **ADR 0028**: a full payout destination goes only through the audited
  reveal, gated on `payments.record`.
- **Pending orders are not counted by the live rule.** The portal export
  counts delivered *and* pending; that is 05A's preview. Portal copy keeps
  delivered-only meaning.
- `app/web` is gitignored; never `git add` it. A `git rm`'d path must not be
  named again in `git add` — the commit fails.
- Test database: docker-compose Postgres on **5433**. The native PG18 on 5432
  is a different server. Run the suite in **fifteen groups of five files**;
  build the group list in a fresh directory, and never chain the runner behind
  an `rm` that can fail — a stale directory named `g` silently swallowed a
  whole run today.

## Open questions for Yahya

- Products: the *Selling best through codes* panel is kept below the
  catalogue. The export does not draw it. Keep or remove?
- The export's *Refresh now* (Settings) and bulk *Review months from January*
  (Historical setup) have no backend act; neither was faked. Build them, or
  accept the difference?
- The portal export names every model on the ranking board, with code and
  avatar. Ours names only her. Confirm that stays.
