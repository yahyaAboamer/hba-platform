# Batch report — Phase 01A, shared design tokens

**Date:** 9 September 2026
**Branch:** `phase01a/design-tokens`, based on `main` @ `63c64c3` (now also `origin/main`)
**Requested scope:** Port the approved design tokens and shared components — dark/light colours, type, spacing, tables/cards, fields, status chips, modal/sheet, buttons, brief empty/error/loading patterns. Preserve style isolation, replace red deliberately, retain money formatting.

**Delivered behaviour:** Both halves of the platform now render in the approved
HBA green palette, in **both themes**, from **one** token layer. Every existing
screen re-skinned by inheriting it — no screen markup was rewritten, which is
what kept this batch small.

---

## Review

### What the owner should try

Run the app locally (commands in `BASELINE_REPORT.md` §10) and look at:

1. **Any maintainer screen** — Overview, Affiliates, a model's pay history. The
   ground is now `#EFF1EE` with white cards at an 8px radius, in Inter. It was
   `#FBFBFC`, 3px, IBM Plex Sans.
2. **The same screens in dark** — new, and the thing most worth a real look.
   There is no toggle yet (that is 01B); to see it, open devtools and put
   `data-theme="dark"` on `<html>`, or run in the console:
   `document.documentElement.setAttribute('data-theme','dark')`.
3. **The portal on a phone** — green where it was red: the code chip, the month
   progress bar, the active tab, links.
4. **The pay-history editor in dark** — its three arrangement tints were
   light-only and would have been unreadable; they now have their own dark
   values.

### Screens I looked at

| State | Result |
|---|---|
| Portal, dark, 420px | ✅ Approved palette. Green chip, bar, active tab on `#08090A` |
| Maintainer, light, 1920px (Overview, pay history) | ✅ Re-skinned; green "covered", red "Clear", amber owed figure |
| Maintainer, **dark**, 1920px (Overview, pay history) | ✅ Nothing unreadable; blockers, owed amber and the primary button all correct |
| Portal, light | ⚠️ **Not seen rendered** — see limitations |

### Approved-design deviations, and why

**One, and it is deliberate: the mono face stays for agreed money.**

Both exports use a single typeface throughout with `font-variant-numeric:
tabular-nums`, and no mono anywhere. The implementation keeps ADR 0027's rule
that an *agreed* figure wears a different face from a *provisional* one.

That is not stylistic stubbornness. It is a meaning the platform already
explains to models in the glossary, in these words — *"shown in a different
typeface from an agreed figure on purpose, so the two are never mistaken for
each other"* — and a provisional figure that looks exactly like a settled one is
the specific confusion that costs somebody money.

**This is yours to overrule.** If you would rather have the single face the
design draws, say so and it is a two-line change in `tokens.css`; the glossary
entry then has to change with it. I did not want to drop a documented guarantee
quietly on the way to a colour change.

Two smaller judgements, recorded in ADR 0039 rather than asked about, because
they follow from the approved design rather than changing it:

- **`--settled` is now the accent green** instead of a green of its own. The
  design has no separate "resolved" colour; you chose, as the brand, the colour
  that already meant resolved. A second near-identical green beside it would
  reproduce the two-reds problem in another hue.
- **Portal errors go back to red.** They were amber only because the accent was
  red and two reds one step apart cannot both mean something. The accent is
  green now, so the reason is gone and amber goes back to meaning *outstanding*.

### Confirmation needed before the next batch

**None.** 01B is not blocked. The mono question above can be answered whenever
you have looked at a screen — it does not hold anything up.

---

## Engineering evidence

**Rules and IDs covered:** S04 (approved theme, both themes), S06 (the
loading/empty/error primitives exist as distinct things), and the token
foundation under UI01/UI51. **No screen row is marked complete** in
`SCREEN_AND_ACTION_MAP.csv` — 01A delivers the layer those rows are built on,
not the rows themselves, and marking them would be the kind of paper progress
the roadmap warns about. 01B is where UI01/UI02/UI51 actually move.

### Files changed

| File | What |
|---|---|
| `frontend/src/styles/tokens.css` | Rewritten. Approved ramp for both halves; light at `:root`, dark at `[data-theme="dark"]`. Radius scale 4/8/14, Inter, `--elev`, `--scrim`, new `--ink-strong`. |
| `frontend/src/styles/portal-accent.css` → **`accent.css`** | Renamed and re-scoped from `.affiliate` to the root. Green. Still eight declarations. |
| `frontend/src/styles/portal.css` | Lost its duplicate colour ramp, dark block, type stack and radius scale (−88 lines). Keeps the portal's denser spacing, tab clearance and furniture. |
| `frontend/src/styles/base.css` | Added `.card` / `.card--rows` / `.card__row`, `.overlay` / `.modal` / `.sheet`, `.loading` / `.skeleton`. Fixed the `#000` button hover. |
| `frontend/src/screens/Compensation.css` | Dark values for the three arrangement tints. |
| `frontend/src/screens/Affiliates.css` | Modal scrim `rgb(20 24 31 / 45%)` → `var(--scrim)`. |
| `frontend/src/styles/__tests__/accent-isolation.test.ts` | Path, names and prose follow the rename. Shape unchanged. |
| `frontend/src/main.tsx` | Inter for both halves; `@fontsource/ibm-plex-sans` imports dropped, Plex Mono kept. |
| `frontend/package.json`, `package-lock.json` | `@fontsource/ibm-plex-sans` removed. |
| `docs/adr/0039-…md` (new), `0038`, `docs/adr/README.md` | 0039 accepted; 0038 marked superseded; index updated. |
| `CLAUDE.md` | "The two halves" and the accent rule now describe one palette and `accent.css`. |

**No API, service, model or migration was touched.** No schema change, no
backfill, no money code, no authorization change. Nothing in this batch can
alter a figure.

### Two real bugs fixed on the way

Both were latent while the maintainer's half could only be light, and become
live the moment it can be dark:

1. `base.css` hovered `.button--primary` to a literal `#000` — correct on a
   light ground, and it inverts a near-white button to black on a dark one. Now
   `var(--ink-strong)`. `portal.css` had been working around this locally; that
   workaround would not have covered the maintainer's screens.
2. The pay-history editor's `--commission-bg` / `--salary-bg` / `--guarantee-bg`
   were light-only tints. Given dark values, measured at 7.84:1, 8.05:1 and
   8.23:1 against `--surface`.

I expect more of these, one screen at a time, as 01B and later batches open
each screen in dark. They are found by looking, not by grepping.

### Contrast, measured rather than assumed

Every value in `accent.css` and `tokens.css` was checked against the grounds it
actually sits on before being written down. The accent file carries the table.
Headline: the constraint that forced *two reds* is gone — green reads at 5.90:1
on a dark card where red managed 3.17:1 — so the two-step accent survives
because the design uses it, not because contrast compels it.

### Commands, results, environment

| Check | Result |
|---|---|
| `cd frontend && npm test` | **104 passed**, exit 0 |
| `cd frontend && npm run build` | exit 0, 10.17s. CSS **73.62 kB → 67.69 kB** (the duplicate ramp is gone) |
| `pytest -q --color=no` against `hba_platform_test` | **1589 passed**, 327.59s, **exit 0** |
| `npm uninstall @fontsource/ibm-plex-sans` | exit 0; Plex Sans woff files no longer emitted |

Environment: Windows, `.venv/Scripts/python.exe` 3.14.5, Node v24.16.0, Docker
Postgres 17 on `127.0.0.1:5433`. Backend ran as a single pytest process against
the disposable `hba_platform_test`, identity checked first. Baseline before
this batch was the same 1589 / 104, so **there are no pre-existing failures to
distinguish from regressions — both suites were green before and after.**

The 80-test accent-isolation guard passes against the *new* values, which is
the check that matters: it now fails the build on a hard-coded green, and it
adapted to the rename and re-scope without changing shape, because it reads the
values out of the file rather than knowing them.

### Visual comparison

Performed, against `docs/redesign/designs/` served locally, for three of the
four theme/half combinations listed above. Synthetic seed data only
(`scripts/seed_demo.py`); **no real, customer or production data, and no
credentials or PII in this report.** The `owner@example.com` /
`a-long-enough-password` pair is the fixture the repository ships.

---

## Continuation

### Limitations

- **The portal's light theme was not seen rendered.** Model sign-in would not
  submit through browser automation — the form never posted (`POST
  /api/auth/login` appears once in the whole server log, for the maintainer
  account), so this is an automation input problem, not an application one.
  Rather than keep retrying, I verified the cascade deterministically: a
  `.affiliate` element resolves to `--paper #eff1ee`, `--surface #ffffff`,
  `--ink #101214`, `--accent #14653a`, `--space-4 12px`, `--radius 8px`, Inter —
  exactly the approved light values, with the portal's denser spacing intact,
  and every token defined. **That is a computed-style check, not a look at a
  screen.** Worth one glance on a phone in 01B.
- **The maintainer's half does not default to dark**, and has no toggle. The
  token layer supports it; stamping and remembering it is shell work in 01B.
- Screens still use their existing layouts. 01A changed what colours and faces
  *mean*, not where anything sits.

### Decisions recorded

- **ADR 0039** — one palette across both halves; accent leaves `.affiliate`;
  supersedes 0038, amends 0027 for colour but not typeface.
- The mono deviation above is **open for the owner**, and does not block.

### Updated

`STATUS.md`, `CLAUDE.md`, `docs/adr/README.md`. `SCREEN_AND_ACTION_MAP.csv` rows
deliberately not moved — see above.

### Next

**Phase 01B** — `docs/redesign/prompts/01_UI_FOUNDATIONS.md`, second batch:
admin six tabs and model five tabs plus You, the route and permission map, and
the theme stamped and toggled on the maintainer's shell. Retiring `UI52` (the
reopen page and endpoint) belongs in that batch, in the same commit as its
`test_reachability.py` exemption update.

### Live changes

**None.** Nothing deployed, nothing pushed beyond the `main` push you
authorised, no production branch moved, no financial data touched.
