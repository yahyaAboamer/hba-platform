# 0038 — The portal wears the brand; the maintainer's tool does not

**Status:** accepted
**Date:** 2026-09-04
**Amends:** [0027](0027-numerals-change-face-when-a-figure-becomes-an-obligation.md) — for the affiliate portal only
**Related:** `docs/plans/2026-09-03-portal-redesign.md`

## The situation

ADR 0027 reserved colour for money state: *"an interface where everything is
coloured has no way left to say 'this one matters'."* That was written for a
month-end tool used by two people on a laptop, and it is still right there.

The affiliate portal is the other half. Twenty models open it on a phone,
arriving from an email, and it is the only surface of HBA they see between
photoshoots. A screen with no brand on it does not read as restrained; it reads
as somebody else's software.

The business chose **HBA red** as the accent, over the design system's own
blurple, having seen both side by side.

## Decision

**Inside `.affiliate`, the accent is HBA red and it may be spent on chrome.**
The active tab, borders, progress fills, the code button and links carry it.
Outside `.affiliate`, ADR 0027 is untouched: the maintainer's screens keep
their cool neutrals and spend colour only on money state.

Three rules make that safe.

**One. The whole decision is eight declarations in one file.**
`frontend/src/styles/portal-accent.css` holds `--accent`, `--accent-text`,
`--accent-soft` and `--accent-on`, for light and for dark, and nothing else.
Swapping the brand is editing that file. **No component may name a colour
directly**, and that is not a convention — `styles/__tests__/accent-isolation.test.ts`
reads whatever the accent file defines and fails the build if those values
appear anywhere else.

**Two. Red draws; it does not speak.** HBA red reaches only **3.17:1** against
the portal's dark card. That is enough for a border and never enough for text,
so a lighter step of the same ramp carries any figure meant to be read. The
brand colour and the readable colour are the same hue at two lightnesses, not
two colours.

**Three. Errors are amber.** `--refused` becomes `#8a5300` inside the portal.
Two reds one step apart on one screen cannot both mean something, and the brand
has the stronger claim. `tokens.css` already describes this hue as *"attention,
not alarm"*, and a void order was never red — it is struck through and faded.

What ADR 0027 protects is intact: **the typeface still says whether a figure is
an obligation.** Mono for agreed money, prose for a working number. That
distinction carries meaning and colour never did.

## Consequences

The portal's focus ring is the accent rather than `--focus`. On the
maintainer's screens the indigo is deliberately a colour used nowhere else; in
the portal the accent is already the only colour, so a third would be noise.

Amber errors are less alarming than red ones. That is the trade, and it is
acceptable because the portal's errors are almost all *"that did not save, try
again"* rather than anything destructive.

Anyone adding a component to the portal must reach for a token they may not
have met. The test tells them which one, by name, in its failure message.

## Alternatives considered

**Nocturne's blurple**, the design system's own accent, which clears every
contrast bar without lifting. Rejected by the business after seeing it beside
the red. The swap remains an eight-line edit if that changes.

**Red everywhere, including the maintainer's screens.** Rejected: those screens
reconcile twenty payments at month end, and ADR 0027's reasoning about colour
and attention is undiminished there.

**Keep errors red and restrict the accent to thin lines.** Rejected: it leaves
two reds on the same screen and asks the reader to tell them apart by width.
