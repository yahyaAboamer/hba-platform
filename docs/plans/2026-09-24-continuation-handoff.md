# Where the work is — 24 September 2026

**Replaces `2026-09-16-exact-design-handoff.md`** and every handoff before it.
Those are kept, with a banner at the top saying what in them is no longer
true. Nothing was deleted.

## The exact position

| | |
|---|---|
| **Branch** | `repair/batch-2` |
| **Commit** | `f83b4fc` — *Every screen at both widths, and 390 at last* |
| **Pushed** | yes, `origin/repair/batch-2` at the same commit |
| **Tree** | clean apart from `.claude/settings.json`, which is the owner's plugin config and deliberately not committed |
| **`main`** | `6a13958`, untouched by the repair |
| **`production`** | `025d8a8`, 122 commits behind `main` — expected while the deployment rule is paused |
| **Backend** | 2,039 tests, 79 files, all passing; reconciles with `--collect-only` |
| **Frontend** | 363 tests, 16 files; `npm run build` green |
| **Migration head** | `b1f0a40c0001` |

## Standing restrictions, still in force

- **No merge, no deployment.**
- **Historical finalisation locked** behind `HISTORICAL_FINALISATION_UNLOCKED`.
  The *review* is open and is how the gaps get found.
- **No destructive fixture against staging or production.**

## What is done

**Batch 1 — the financial rules.** F1 repeated-credit release accounting, F2
source/destination cash accounting, F3 one money gate in front of every writer
of a model's money, F4 operation-key identity through `_replay_of`. ADRs 0041
and 0042 record the two rule changes. Report:
`docs/repair/2026-09-19-batch-1-financial-rules.md`.

**Batch 2 — data contracts, A09, A12, and the visual review.** The bulk
historical review and a finalisation safe to repeat and refused by default;
component tests that actually exercise failed requests; and, on 23 September,
the complete visual and interaction sweep. Report:
`docs/repair/2026-09-20-batch-2-data-contracts.md`, ending in the A03 section.

**The sweep itself:** 69 matched pairs in `docs/repair/batch-2/visual/shots/`,
every admin screen at 1280 and 1440 and every model screen at 390, a JSON
digest beside each, and eight interaction checks passing. The reading of it,
row by row, is `docs/repair/batch-2/visual/CHECKLIST.md`.

## What is waiting on Yahya

1. **Five historical facts**, unchanged:
   `docs/repair/HISTORICAL-INFORMATION-NEEDED.md`. Finalisation cannot be
   unlocked without them, and confirming the order import is complete is the
   one that cannot be worked out from the data.
2. **Thirteen design decisions** from the sweep, one sentence each at the end
   of `CHECKLIST.md`. None of them is a bug; each is a place where the app and
   the approved export differ and somebody has to say which wins.

## The next bounded task, proposed

**Finish the three screens the sweep could not exercise, by growing the seed —
and nothing else.**

`Model · Wardrobe`, `Products · Active requests` and `Settings · Shopify and
sync` each render their empty state correctly, and the export's version of each
is full of fixture rows. Comparing them today compares seed data, so the
checklist says *not exercised* rather than claiming a match.

The task: add shipments, one feature request and a recorded Shopify connection
to `docs/repair/batch-2/visual/seed_browser.py`; re-capture those three screens
at both widths; update the three checklist rows to matched, corrected or still
differs. **No application behaviour changes.** It is bounded, it closes the
only gap in the sweep that is ours to close, and it can be reviewed in one
sitting.

Not proposed yet, and why: the thirteen decisions need Yahya first; the two
release gates need a restored copy of real data and a rehearsal window; and
`vShipment` (the one export view never built) is a feature, not a repair.

## Decisions not to reopen

- **Pending orders count.** `PENDING_INCLUSIVE` is the live policy, written
  into every snapshot approval agrees (`app/services/commission/calculate.py`
  names it *"the live counting rule"*; `payroll._payload` sets
  `body["policy"]`). **Two documents said the opposite and sat in the tree
  together for eight days**: the 16 September handoff's *"pending orders are
  not counted by the live rule"*, and `CLAUDE.md`'s *"05A is a read-only rules
  preview … the normal calculation and approval still need verified
  pending-inclusive activation."* Both described 05A's preview and were left
  behind when the code path moved. Both are removed; ADR 0040 is the rule.
- **The payer sees the whole destination** — ADR 0042, amending 0028, on the
  owner's explicit instruction. Masking still governs every *record*.
- **An agreed month is never unmade** (05B); a difference after approval is a
  correction (05C).
- **The month control is a grid**, not the export's dropdown. The owner asked
  for the grid.
- **The reviewing browser is Playwright**, headless, in its own process. Not
  the Chrome extension, and not the window-resizing script.

## What I got wrong, so the next session does not repeat it

- **Ran a second pytest against the test database while the suite was
  running**, twice. Both times it produced failures that looked exactly like
  regressions — `test_affiliates_api` reported six failures and passed alone
  minutes later. Use a second database (`hba_probe`) or wait.
- **Polled immediately after starting a background `sleep`**, which measures
  nothing, and concluded the suite had stalled when it was fine.
- **Wrote a digest that joined text nodes with a space**, which reported two
  differences that did not exist (`1 – 12 of 19` against `1–12 of 19`). It
  uses `innerText` now.
- **Collapsed two cases into one** when fixing the desk's empty-destination
  sentence: `destination_line` is null both when there is no destination and
  when the reader may not see one, and the first fix would have told marketing
  that a model with perfectly good details had none. Three tests hold the
  three cases apart now.
- **Invented rationale in code comments** — a claim about why the design uses
  `EGP` that was mine, not the design's. Trimmed to what is true.
