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
