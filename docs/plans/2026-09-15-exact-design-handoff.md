# Handoff — exact design implementation, 15 September 2026

The standard changed on 12 September (`HBA_Exact_Design_Implementation_Prompt.md`
at the repo root): every screen must match its **corresponding element** in
the approved exports — structure, copy, sizes, tones and interactions — not
merely use colours and sizes that appear somewhere in them. Tests passing and a
feature existing are not evidence of that.

**The live record of what is done is `docs/redesign/parity/SCREEN_MATRIX.md`.**
Read it before touching a screen. This file says how to continue.

State at handoff: `main` and `production` level at `60fe686`, staging and
production deployed, tree clean. **1934 backend, 315 frontend.**

## How to work a screen (the method that held)

1. **Read the export's markup for the view** — the matrix gives its line range.
   Every element carries its style inline, so the range *is* the specification.
2. **Read the export's data script too** (Admin from line 1646, Portal from
   line 800). Labels, filter names, state words and tones are bound there, not
   in the markup. Three screens were matched on markup alone and had the wrong
   filter names (Models was *All / Waiting / Active / Archived*; the export is
   *Active / Applications / Invitations / Inactive*).
3. Rebuild presentation to it; keep the real capabilities and safeguards.
4. Deploy, then **look at the rendered page on staging** and fix what the
   screenshot shows — every batch this week found something the source did
   not (header overlap, a flex `<td>` whose hairline stopped short, a zero
   figure fading to grey, a lone tile stretching across a row).
5. Update the matrix row with what was actually checked.

Measuring rendered elements with `javascript_tool` works well; screenshots
sometimes time out on a hidden tab — open a fresh tab and retry once.

## Shared primitives (do not re-invent per screen)

In `styles/base.css`: `.button` (outlined, 38px, transparent), `.button--primary`
(**accent outline + tint + accent text — the export has no filled button**),
`.button--row` (34px), `.button--quiet` (Copy), `.input` / `.input--search`
(240px), `.surface` (the rounded ground a table sits on), `.table` (10px 18px
row padding reproduced with 8px cell gaps), `.pill`, `.chip` / `.chip--on`,
`.seg` / `.seg-opt`. `.panel` has no border. `PaymentDetail.css` holds
`.pay-detail__card` and friends, reused by the profile, terms and correction
screens.

Accent tokens: `--accent` = the export's `--acc` (chrome, borders, selected
text); `--accent-lift` = the export's `--acctext` (accented text on dark).
`--accent-text` equals `--accent` and is a trap — prefer the two above.

## Traps found this week

- **One CSS bundle.** A class name defined in an admin sheet and a portal sheet
  styles both. `.orders__row` and `.year` collided; both were renamed. Before
  adding a class, grep the other half.
- **`display:flex` on a `<td>`** takes it out of the row box. Put the flex box
  on a span inside the cell.
- **Line-height on inputs.** The page's 1.5 makes a 38px input 42px. `.input`
  sets `line-height: normal`.
- **`Money` puts its class on the same span as `money`**, so
  `.x .money` never matches `<Money className="x">`; write `.money.x`.
- **`money--zero` fades a zero** — right in a table row, wrong on a summary
  card. Cards override with `color: inherit`.
- **ADR 0028 is not optional.** A full payout destination goes only through
  the audited `POST .../payout-destination/reveal` (gated on
  `payments.record`). An attempt to send it to the Payments list was caught by
  `test_reachability` when the reveal lost its caller, and reverted.
- **Pending orders are not counted by the live rule.** The portal export
  counts delivered *and* pending; that is 05A's preview. Portal copy must keep
  delivered-only meaning.
- `app/web` is gitignored — never `git add` it; the bundle is built on deploy.
- The test database is the docker-compose Postgres on **5433**. If pytest
  times out connecting, Docker Desktop has stopped
  (`D:\Docker\DockerDesktop\Docker Desktop.exe`, then
  `docker compose up -d postgres`). The native PostgreSQL 18 service on 5432
  is a different server with no `hba` role — never point tests at it.
- Run the suite in **fifteen groups of five files**; eight groups of ten were
  killed for memory again with Docker running.

## Done (see the matrix for evidence per row)

Admin: shell and sidebar badges, Home (with the missing sales chart), Models,
Products, Targets, Payments, Orders, Settings (rail, Team, Shopify and sync,
Appearance), and the secondary views — order detail, payment detail with
approval, record payment, receipt, correction, compensation terms, the model
profile's five sections, product detail and feature request. Portal: *Your
best sellers* and *All products sold*.

New backend routes this week, each with tests: `GET /api/orders/detail/{id}`,
`GET /api/payroll/{month}/statement/{id}`, `GET /api/affiliates/{id}/orders/{month}`,
`GET /api/affiliates/{id}/record`, `GET /api/me/best-sellers`; plus the
catalogue `scope`/`counts`, the roster `arrangement`, the orders `counted`
total and the staff invitation `created_at`.

## What is left, in order

1. **The portal, all of it** — Home, Orders, Wardrobe (beyond best sellers),
   Targets, Ranking, and You / How this adds up / Payments / Receipt / Payment
   details / Personal details / Height and weight / Notifications / Help.
   **Blocked on a model session for visual checks**: signing in as a model in
   the admin's browser signs the admin out. Ask Yahya for a second browser
   profile signed in as a test model.
2. Admin remainder: the invite view (`vInvite` — ours is a modal), the
   shipment view (`vShipment`, no route), the application review panel on a
   pending profile (export: *Submitted information* + *Setup before approval*
   + *Approve this application*), Settings Historical setup / Brand codes /
   Reference detail.
3. **Every row at 1280 and 1440 CSS px and in the light theme.** Every check so
   far was dark at 1536 px (the machine's DPI scaling makes a 1280 window
   1536 CSS px wide).
4. Decide the legacy routes in the matrix's section C (`/payroll`,
   `/payroll/:month/approve`, `/payroll/:month/reopen`, `/affiliates/:id/payments`,
   `/affiliates/:id/payout-destination`).

## Open questions for Yahya

- Products: the *Selling best through codes* panel is kept, below the
  catalogue. The export does not draw it. Keep or remove?
- The export's *Refresh now* (Settings) and bulk *Review months* (Historical
  setup) have no backend act; neither was faked. Build them, or accept the
  difference?
