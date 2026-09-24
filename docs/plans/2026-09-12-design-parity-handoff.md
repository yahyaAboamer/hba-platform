# Where the work is — 12 September 2026

> **SUPERSEDED, 24 September 2026.** The current handoff is
> [`2026-09-24-continuation-handoff.md`](2026-09-24-continuation-handoff.md).
> Kept because the paragraph on how the redesign was mistakenly called
> complete is worth re-reading. **One thing in it is paused:**
>
> - *"`main` and `production` are level and stay that way — the owner asked
>   for production to match staging automatically, without being asked each
>   time."* That was right for the build phase. **It is suspended for the
>   audit repair**, by the owner's explicit and repeated instruction: no merge
>   and no deployment until he says so. `CLAUDE.md` holds the current version.
>
> The browser instructions here — sign in at staging, serve the exports on
> 8899, compare at 1280 and 1440 — are replaced for sweeps by the Playwright
> harness in `docs/repair/batch-2/visual/`. Serving the exports on 8899 and
> excluding the demo toolbar still hold.


Replaces `2026-09-11-design-parity-handoff.md`, which was written by the agent
that produced the correction package and describes a branch that is now merged.

## The position in one paragraph

The redesign is **not complete**, and the batch reports that said it was were
wrong in a specific way worth remembering: every one of them correctly said
*visual evidence: none*, and then concluded parity anyway from passing tests
and present features. Phases 00–09 work. They were built onto the old page
structure rather than rebuilt to the approved exports. This was settled by
rendering the export and live staging side by side, not by argument.

## What changed today

- **A browser session is available.** Yahya signs in himself at the staging
  URL and it persists. Serve the exports for comparison with
  `python -m http.server 8899` inside `docs/redesign/designs` — `file://` is
  blocked. Compare at 1280 and 1440, excluding the export's demo toolbar.
- **The correction branch was imported** from its bundle and merged.
- **C1 is largely done**: admin Home, the Models roster, Products, the profile
  hero and dated terms. Settings already matched. See
  `reports/10C1-design-parity-admin.md`.
- **D01–D12 are all closed.** Nothing is open.
- `main` and `production` are level and stay that way — the owner asked for
  production to match staging automatically, without being asked each time.

## What is left, in order

1. **The profile's per-section content** against the export — the last C1 item.
2. **The model portal.** It has *not been looked at by anyone*, and the
   imported branch changed `MyMonth`, `MyWardrobe`, `MyOrders` and
   `AffiliateLayout` without anybody seeing the result. Needs a model sign-in,
   which signs the admin session out — so ask, do not just do it.
3. **C2, the read contracts.** These hold the real release blockers:
   `my_year` returns `orders` and not `uses`; `my_month` still reads
   `commission_state` rather than delivery state (D03 was only implemented in
   `performance.py`); `blockers_for` calls `calculate_month`, which counts
   pending base only when `is_preview`; historical months return a null
   earnings figure; model-specific top sellers do not exist.
4. **C3–C5**: products and the wardrobe journey, payments and account views,
   then full acceptance.

## Two things that will waste your time if you do not know them

- **The suite will be killed for memory.** This machine has 7.9 GB with around
  1 GB free. Run it in **eight groups of ten files** — the recipe is in
  CLAUDE.md. Four groups of nineteen was still too much.
- **`test_every_capability_has_a_way_in` cannot see a nested generic.** It
  finds a route by matching `api.put<...>("/path")`, and the pattern stops at
  the first `>`. Name the type rather than loosening the guard.

## What I got wrong today, so it is not repeated

- Called the redesign code-complete on the strength of tests and features.
- Read `Product.sku`, which does not exist — a SKU belongs to a variant. It
  500'd the whole catalogue on staging, and **nothing in 1901 tests had ever
  called that route**. Testing the services is not testing the payload.
- Used `--accent-text` for every link and active item. The export uses the
  saturated green 39 times and the pale one 9, all nine on a tinted ground.
  The owner saw it before I measured it.
