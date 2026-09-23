# The visual and interaction review

Every admin screen at **1280 and 1440**, every model screen at **390**, each one
captured twice - the approved export and the running application - and compared.

## Why there is a whole harness here

The first attempt drove the browser through the Chrome extension, which drives
**the Chrome window somebody is using**. It worked and it was honest about what
it produced, but three things made it unusable for a sweep this size:

- the window is restored between operations, so a capture verified at 1280 is
  followed by one at 1600 and only the filename says otherwise;
- clicking resets it again, so every interaction invalidates the width;
- **Chrome will not make a window narrower than about 500px**, so 390 - the
  width the entire model-facing half of the product is designed for - could not
  be reached at all.

Playwright launches its own headless Chromium. No window is opened, restored or
resized; the user's Chrome is never touched; and the viewport is exactly the
number in the config. 390 is just a number.

## Running it

Postgres up, then:

```bash
# 1. a throwaway database with the export's own cast in it
docker exec hba-platform-postgres-1 psql -U hba -d postgres \
  -c "DROP DATABASE IF EXISTS hba_browser;" -c "CREATE DATABASE hba_browser OWNER hba;"
DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_browser' \
  APP_ENV=development GO_LIVE_MONTH=2026-06 \
  .venv/Scripts/python.exe -m alembic upgrade head
DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_browser' \
  APP_ENV=development GO_LIVE_MONTH=2026-06 \
  .venv/Scripts/python.exe docs/repair/batch-2/visual/seed_browser.py

# 2. the application, on the built frontend
cd frontend && npm run build && cd ..
DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_browser' \
  APP_ENV=development GO_LIVE_MONTH=2026-06 SESSION_SECRET='browser-review-only' \
  .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8123

# 3. the approved exports (file:// is blocked, so they are served)
cd docs/redesign/designs && python -m http.server 8899 --bind 127.0.0.1

# 4. playwright, from outside the repo - see review.mjs for why 1.58.0 exactly
npm install --prefix "$SCRATCH/pw" playwright-core@1.58.0
cd docs/repair/batch-2/visual
PLAYWRIGHT="$SCRATCH/pw/node_modules/playwright-core/index.js" node review.mjs
node compare.mjs
PLAYWRIGHT="$SCRATCH/pw/node_modules/playwright-core/index.js" node actions.mjs
```

`review.mjs` **resumes**: a step whose two screenshots already exist is skipped
unless `FORCE=1`. Delete the pair for a screen you have changed and run again.
This machine's memory watchdog killed the run twice; resuming is what made that
cost one step instead of the sweep.

## What is in `shots/`

`shots/export/<screen>-<width>.png` and `shots/app/<screen>-<width>.png`, a
matched pair per line of the checklist, plus a `.json` digest beside each.

**The filename is the width it was actually taken at.** The export's frame is
asserted to be exactly that wide before the shutter, and the app's viewport is
set to it, so the two pictures cover the same area.

**The export's review toolbar is not in the picture.** The prototype draws
itself inside a fixed frame - `.ad` at 1280x900 or 1440x900, `.pt` at 390x844 -
with its width switch and scenario buttons *outside* that frame. Screenshotting
the frame element excludes them by construction rather than by cropping.

## The digests, and why they do the real work

Two screenshots side by side catch a broken layout and nothing else. A tab
renamed from *Applications* to *Pending*, a heading that lost its unit, a
button the design has and the app does not: all invisible at a glance, all
exactly what this review is for.

So each capture also writes what the page *says* - every visible line via
`innerText`, every control label, every money string, the typeface and colour -
and `compare.mjs` diffs them, filtering out the differences that come from the
data rather than from the design.

## The one thing that cannot match

**The export is set in November 2026; the platform runs on the real clock.**
Every model's start month is shifted so she stands the same distance from the
working month as her counterpart in the export, but the month *labels* differ.
A pair reading "September" against "November" is that, and nothing else.
