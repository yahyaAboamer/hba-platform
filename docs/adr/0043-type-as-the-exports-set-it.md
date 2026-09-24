# 0043 — Type as the exports set it: proportional figures, one weight

**Status:** accepted; **controls amended by
[0044](0044-controls-in-the-browsers-control-font.md)** — buttons draw in the
browser's control font, as the approved page does
**Date:** 2026-09-24
**Amends:** [0039](0039-one-palette-across-both-halves.md) (its type mechanism),
and with it what remained of [0027](0027-numerals-change-face-when-a-figure-becomes-an-obligation.md)
**Related:** `docs/redesign/designs/Admin Dashboard.dc.html`,
`docs/redesign/designs/Affiliate Portal v3.dc.html`, the design system's
`_ds/nocturne-…/styles.css`; batch E in `docs/repair/batch-2/visual/CHECKLIST.md`

## The situation

The owner saw the application's type differ from the approved HTML. The first
suspect was the font, and it is not the font: the application self-hosts the
same Inter the exports load from Google Fonts, and measured in the same
headless Chromium the two draw a test line at 438.49px at 400, 443.12px at
500 and 447.7px at 600 - identical to the hundredth of a pixel. Nothing falls
back.

What differs is what the application asked the font to do, in four places:

1. **Line height.** The design system sets `body{line-height:1.55}` and every
   line in both exports inherits it. Ours was 1.5.
2. **Figures.** ADR 0039 put `font-variant-numeric: tabular-nums` on `body`, so
   every digit on every screen was tabular. The exports set it on figures only
   - money, counts, ranks - and leave codes, dates and prose proportional.
   The difference is not subtle: `EGP 12,345.67` is 7.6px wider tabular, and a
   `1` is 60% wider, so a code like *HBA15* grows by the width of each one.
3. **Headings.** Inside the applications the exports use exactly one heading
   element: the admin page title, an `h4` under the design system's heading
   rule (500, line-height 1.12, -0.015em). Every other title - *Your year*,
   *Contact and shipping* - is a plain element in `var(--font-heading)`, which
   is only the family; it renders at 400 on the body's 1.55. Ours were
   `h1`-`h3` at 600, 1.25 and -0.01em, and a dozen screen rules had copied
   `var(--font-heading)` as *weight 500*.
4. **The agreed figure's weight.** 0039 kept 0027's principle - an agreed
   figure set apart from a working one - by weight: `.money--agreed` at 500.
   The exports draw every figure at 400.

## Decision

The exports decide (the owner, 20 September: *"Earlier internal decisions do
not override my explicit requirements."*).

- `body` line-height 1.55; no tabular figures on `body`. `.money` and the
  column classes that already set `tabular-nums` keep it, which is where the
  exports set it.
- `h1`-`h3` take the text's weight, rhythm and tracking. The admin page title
  (`.layout__main > .page__head h1`) takes the heading rule at 18px.
- The screen rules that set 500 or 600 on text the exports draw at 400 are
  400: the portal's Home title, figure, metrics and chart, the active tab,
  the Orders filter, and the Ranking, Targets, Wardrobe and panel titles.
- `.money--agreed` is the text's weight and tracking.
- Inter ships at the four weights the exports load, 400 to 700, so a
  `<strong>` - which the admin export does use in prose - is drawn from the
  700 face rather than the 600.

## What this costs

- **An agreed figure no longer looks different from a working one.** That was
  the last visual trace of 0027. What says it now is what already carried it
  for the models: the words beside the figure - *Estimated*, *Approved*,
  *in progress*, *still adding up* - and the state pill. 0039 already said the
  words were doing the actual saying; this removes the redundancy.
- **Digits outside the figure classes no longer line up in a column.** A date
  or a code in a table cell is proportional. Where a column of numbers matters
  it already sets `tabular-nums` itself; a new one must too.
- One more font file, fetched only when a 700 glyph is drawn.

## What stays

0039's palette, the one family, and 0027's principle that an agreed figure is
distinguished from a working one - by what the screen says, which is the part
of it a reader was ever able to use.
