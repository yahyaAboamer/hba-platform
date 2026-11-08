# Production's screens: what changed from the export

The screens came from the ChatGPT export of HBA Production OS (site version 22,
source commit `3c27096`, exported 2 November 2026), read in full first. ADR
0076 decision 3 allows only the edits that let them live inside HBA, and none
a person would see beyond the one ADR 0069 names: signing in is HBA's. Every
such edit is listed here. Anything not listed is the export's code as it was.

## The build

- **Own Vite build, no Next.js.** `vite.config.ts`, `index.html`,
  `tsconfig.json`, `postcss.config.mjs` and `src/main.tsx` are new. The
  export's Vinext, Next.js, Cloudflare, Wrangler, Drizzle and ESLint set-up
  is not brought in. Versions are the export's own lockfile's, pinned exactly.
- **Three Next.js modules are local stand-ins**: `next/image` (a plain
  `<img>`, as it was used unoptimised) and `next/navigation`'s `usePathname`
  (`src/shims/`). `next/link` was used once, for "Sign out of ChatGPT", which
  is removed.
- **Fonts**: the export's own Geist files, in `public/fonts`, declared in
  `src/fonts.css`, which also sets the two variables `next/font` used to set.
- Moved: `app/globals.css` → `src/globals.css`; `components/` and `lib/` →
  `src/`. Removed, unused by any screen: `lib/permissions.ts`.

## Addresses (ADR 0076 decision 3)

- Every request moved from `/api/…` to `/api/production/…` (18 places).
- The screens are served at `/production-app/…` inside HBA's frame at
  `/production/…`. `src/lib/base-path.ts` translates; in
  `components/hba-app.tsx` the history push, the back-button handler and the
  two logo addresses go through it, and the screen announces its address to
  the frame.

## Sign-in (ADR 0076 decision 4)

- `components/hba-app.tsx`: the "Sign in to edit" box and "Sign out of
  ChatGPT" are removed; the person menu shows the HBA account; a manager's
  label comes from the server (`roleLabel`).
- `components/pages/team-workspace.tsx`: "Owner: sign in with ChatGPT" is
  removed; "Sign out" signs out of HBA.
- `lib/qc-checklist.ts`: `TeamUser` has an optional `roleLabel`.
- `src/main.tsx` sends somebody without an HBA session or Production access
  to HBA's start page, and adds HBA's CSRF token to every write.

## Fixed content (ADR 0076 decision 3)

The lists in `lib/demo-data.ts` and eight sentences in the screens named
people. They now come from the database (`production_fixture`), loaded before
the first screen draws, so every screen shows exactly what it showed:

- `lib/demo-data.ts`: types kept; each list is an empty array filled by
  `applyFixtures`. A test keeps them empty in the code.
- `lib/fixtures.ts` (new): `fixtureText`, `fixtureList`.
- `components/hba-app.tsx`: the Team accounts lines; two supplier names in
  the new-order form's manufacturer list.
- `components/pages/dashboard.tsx`: one problem's detail line.
- `components/pages/operations.tsx`: the QC page's two detail lines and its
  sample note; the unused Users page's rows.
- `components/pages/control-data.tsx`: the samples form's default owner.
- `components/pages/team-workspace.tsx`: the QC page's eyebrow name.

## Phone width (owner's word, 7 November 2026)

Two screens were wider than a phone, on the old site too. Nothing else moves.

- `src/globals.css`: the dashboard's attention list sizes its columns with
  `minmax(0,1fr)`, so a long detail line is cut with "…" as its own rule
  already asked, instead of widening the row past the screen.
- `components/pages/production.tsx` and `src/globals.css`: the Production
  timeline's chart panel (`gantt-panel`) scrolls sideways inside itself when
  the screen is narrower than the chart, as the calendar already did on a
  phone, instead of widening the page.

## Staff record quality checks (ADR 0077, owner, 7 November 2026)

- `components/pages/team-workspace.tsx`: the QC checklist is editable when
  the server says `canCheckQc` (Production staff), as well as for "qc" and
  "admin".
- `lib/qc-checklist.ts`: `TeamUser` has an optional `canCheckQc`.

## Row menus, deleting, and the photo library (owner, 8 November 2026)

- `components/row-menu.tsx` (new): the ⋯ menu and the "Delete …?" confirm.
  The menu's list is drawn at the top of the page so no panel clips it, and
  follows its button as the page scrolls.
- `components/pages/production.tsx`: each order row's ⋯ (once only a picture)
  offers Open order, Edit order and Delete order; the order editor is one
  component (`OrderEditModal`) used by the row menu and the order page's Edit
  button. Rows are keyed by order. An order's page opened from its own link
  waits for the orders instead of drawing nothing.
- `components/drop-phases.tsx`: each phase card has a ⋯ with Rename and
  Delete. Deleting a phase moves its orders to Unassigned.
- `components/pages/control-data.tsx`: each sample row has Delete.
- `components/record-photos.tsx`: adding photos to an order or sample offers
  "Upload new" or "Choose existing", every photo already stored, searchable,
  added without uploading again.
- Deleted orders and samples are hidden, not erased (`deleted_at`).
