# Building the state gallery

Goal: every state of the screen visible, at 390 and 1440, in dark and light,
captured by the same script before and after, with nothing written anywhere
real.

## Option A (default): a seeded disposable database

The approved harness in `docs/repair/batch-2/visual/` (read its README for
the run-up): a throwaway database on the Docker Postgres (port 5433), the
app run locally against it, Playwright headless with its own sessions.

- Seed one record per missing state with a small script beside
  `seed_browser.py` (name it `seed_<screen>.py`). Use the app's own services
  to create records where possible, so the server computes every figure.
- Mark seeded people *(test)* in their names.
- Drop the database afterwards.

Why default: the real server computes the figures, so a fixture can never
disagree with a formula (lessons 1-3).

## Option B: the staging-origin read-only harness

Use only when a state cannot be seeded locally, and only with the owner's
go-ahead and his own sign-in (CLAUDE.md: never reuse a person's staging
session for sweeps otherwise).

`tools/harness.tpl.js` is the generic skeleton:
- serves a local build (`frontend/dist` after `npm run build`, or `staging`
  for the deployed one) on the staging origin via `page.route`;
- passes GETs through to staging's real API;
- injects fictional records for missing states (`FIXTURES` and `patch()`);
- answers **every non-GET with 418**, so nothing can be written;
- runs each shot's optional action (open a dialog, fill a field);
- hides scrollbars; optional light theme set on `<html>` for the capture only.

Run: `bash tools/run.sh <web-dir|staging> <out-dir> '[[390,844],[1440,900]]' null dark`
from a folder where the `playwright-cli` session `hba` is open and signed in.
The Payments version (`docs/design-refinement/payments/tools/harness.tpl.js`)
is the complete worked example: fixtures, totals patching, 20 shots.

## Fixture rules (both options)

- One fixture per business fact; every endpoint's response derived from it.
- Fields from the server's formula, enums from the real enum module.
- Cover: empty, loading-failure (force a 500), each status, each edge
  (zero, negative, overpaid, credited, missing setup, changed destination,
  long names, many rows), each dialog open, each form error.

## Output

- Captures named `<shot>-<width>[-light].png`, kept outside the repository
  (scratchpad while working, then the evidence ZIP on D:).
- `tools/compose.py <root>` makes before/after sheets from `before/` and
  `after/`; edit its `SHEETS` list per screen.
