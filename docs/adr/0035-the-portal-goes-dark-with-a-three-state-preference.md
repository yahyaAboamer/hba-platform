# 0035. The portal goes dark after sunset — warm lamplight, chosen with a three-state preference

**Status:** Accepted
**Date:** 2026-08-31

## Context

The portal's light palette was settled in ADR 0027 and re-voiced in warm tones
when the portal got its own surface (portal.css): paper rather than screen-white,
cool neutrals deliberately kept for the maintainer's month-end tool. Models who
use the portal after dark asked for the same care in a dark theme: the business
related that a bright white screen at night is the one part of the job nobody
misses by doing it tomorrow.

The admin side has no such request on the table. Its dense tables were designed
for laptop screens in working hours, and nobody has asked to reconcile payments
in the dark.

The platform already speaks in two palettes from one token set (tokens.css,
overridden per surface by portal.css's `.affiliate` block). A dark theme could
therefore be a third voice in the same mechanism — or it could fork into its own
CSS, which would rot.

## Decision

The model-facing surfaces go dark with a **"warm lamplight" palette** — the same
warm family as the daylight portal, read by lamplight rather than daylight:

| Token | Light | Dark |
| --- | --- | --- |
| `--paper` | #fbf8f4 | #16120e |
| `--surface` | #ffffff | #201a14 |
| `--ink` | #1a1714 | #f0e9df |
| `--quiet` | #6b635b | #b0a494 |
| `--rule` | #eae3da | #2e271f |
| `--owed` | #a65b14 | #e8a23d |
| `--settled` | #0f6b45 | #46c07e |
| `--refused` | #a83224 | #ef6f63 |
| `--owed-quiet` | #fbf1e6 | rgba(232, 162, 61, .14) |
| `--settled-quiet` | #edf6f1 | rgba(70, 192, 126, .14) |
| `--refused-quiet` | #fbefec | rgba(239, 111, 99, .14) |

The admin side stays light. Its "Midnight ledger" dark theme is named here so
nobody mistakes the omission for an oversight — it will be designed when it is
asked for, against its own constraints.

**Preference is three-state and defaults to Auto.** A model chooses Light, Dark,
or Auto on MyDetails. Auto — the default — follows the dark-or-light setting
already chosen on the device (`prefers-color-scheme`), so somebody who never
opens the picker still gets a screen that agrees with the rest of the phone. The
choice is stored in localStorage under `hba-theme`, and the theme is painted
onto `<html>` as `data-theme` by a script in index.html before the bundle
loads, so the first paint is already right: no white flash before the dark
arrives.

**Mechanism.** The dark palette is a variable override, not a second stylesheet:
one block in portal.css, scoped to the three model-facing roots (the portal's
`.affiliate` main, and the application form and invitation that sit outside it
 `.apply` and `.accept-invite`). Every component reads its colours from
variables, so the primitives in base.css follow the dark palette without a line
of dark-specific CSS in them. No light value is redefined anywhere; if
`data-theme` is "light" or missing, the computed styles are byte-identical to
what shipped before this ADR.

## Invariants preserved

- **Colour is money state and nothing else (ADR 0027).** The dark palette spends
  colour on exactly the same three meanings. Navigation, headings, panels and
  active states stay neutral; `--focus` keeps its one job and its hue.
- **Mono for agreed money, prose for working numbers.** Typefaces are untouched.
- **No shadows.** Borders carry structure in the dark too.
- **The portal keeps its 14px radius.**
- **Light theme byte-for-byte unchanged.** Every dark rule lives under
  `[data-theme="dark"]`.

## Consequences

- **Every future colour needs both themes.** A new token added to tokens.css
  without a dark counterpart will render the light value inside the dark
  palette — usually glaringly wrong, which is at least loud. The dark block is
  the checklist.
- **Two places hold the resolve rule.** The inline script in index.html must
  stay identical to `resolveTheme` in src/lib/theme.ts, because it runs before
  the bundle. theme.ts is the source of truth; the script is its shadow. A
  change to one without the other flashes.
- **Scoping is a list, not a forest.** Dark reaches the model's surfaces through
  three enumerated roots. A new model-facing page outside `.affiliate` must add
  its root to the dark block or stay light inside a dark browser — visible
  immediately, cheap to fix.
- **color-scheme is scoped per surface, not set on <html>.** The maintainer and
  a model may share a device and origin; a global dark `color-scheme` would
  darken native controls on the admin's light screens.
- **Light images keep a light ground in the dark** (the InstaPay guide, payment
  proofs). Screenshots of the real world are not recoloured; they are mounted,
  like a photograph.

## Alternatives considered

- **A second stylesheet (dark.css), swapped at load.** Rejected: two files that
  must agree about every component is a maintenance tax forever, and the
  variable mechanism already exists.
- **`prefers-color-scheme` media query only, no preference.** Rejected: a
  model who wants the light portal in the day but dark at night on the same
  device — or the reverse of the device's choice — has no way to say so. Three
  states is the smallest complete answer.
- **Dark for the admin side too, now.** Rejected: nobody asked. Shipping an
  undesigned dark theme for a dense month-end tool risks the exact complaint the
  light portal earned ("I don't know which is which"). Recorded as a named
  future decision instead.
- **Defaulting to Light with an opt-in to Dark.** Rejected as the default: Auto
  respects a choice the person already made about their device. An opt-in
  default silently ignores that choice.
