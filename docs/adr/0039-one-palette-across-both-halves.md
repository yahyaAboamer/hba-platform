# 0039 — One palette, and one typeface, across both halves

**Status:** accepted; **its type mechanism is amended by
[0043](0043-type-as-the-exports-set-it.md)** — figures are tabular only where
the exports set them, and an agreed figure is no longer heavier
**Date:** 2026-09-09
**Supersedes:** [0038](0038-the-portal-wears-the-brand-the-tool-does-not.md) entirely, and
[0027](0027-numerals-change-face-when-a-figure-becomes-an-obligation.md)'s
two-typeface mechanism — not 0027's principle, which stands
**Related:** `docs/redesign/BASELINE_REPORT.md`, `docs/redesign/designs/`

## The situation

ADR 0038 was written five days ago and it was right about the platform as it
then stood. The affiliate portal had been redesigned; the maintainer's tool had
not. So the accent lived under `.affiliate`, `portal.css` carried a complete
second colour ramp beside `tokens.css`, and that isolation is what made it safe
to rebuild one half three weeks before payroll without touching the other.

The business has since had **both** halves drawn, and approved them. The two
exported references —

    docs/redesign/designs/Affiliate Portal v3.dc.html
    docs/redesign/designs/Admin Dashboard.dc.html

— declare byte-identical token blocks. Same neutrals, same amber, same red,
same green accent, same two themes. The admin export applies them under `.ad`,
the portal under `.pt`, and the values do not differ by a digit.

Two parallel ramps for one palette is two places to change a colour and one
place to forget.

## Decision

**One palette, defined once in `tokens.css`, for both halves.**

- The colour ramp, both themes, the type stack, the radius scale and the
  elevation model move to `tokens.css`. Light is written in full at `:root`;
  dark redefines the same names under `[data-theme="dark"]`. The selector is
  unanchored on purpose — the portal stamps `data-theme` on its own root and
  the maintainer's shell stamps it on `<html>`, and one block serves both.
- `portal-accent.css` becomes **`accent.css`** and defines its four tokens at
  the root rather than under `.affiliate`. It is still the only file allowed to
  name the accent, and `accent-isolation.test.ts` still fails the build
  otherwise. The mechanism did not change; what it covers did.
- `portal.css` stays scoped to `.affiliate` and keeps what is genuinely the
  portal's own: the denser spacing of a phone screen, the tab-bar clearance,
  and the furniture. **The isolation stays.** It is now isolation of layout
  rather than of palette, which is the part that was ever load-bearing.

### The accent is green, and green already meant something

HBA green: `#23A95C` for chrome on dark, `#7BE0A6` lifted for accented text,
`#14653A` for both roles on light.

`--settled` now points at that ramp instead of holding a green of its own. ADR
0027 reserved colour for money state and the portal's sheet argued that settled
"is the one meaning the accent must never be confused with" — correct **while
the accent was red**. The business then chose, as its brand, the colour that
already said *this resolved*. Keeping a second near-identical green beside it
would reproduce, in another hue, exactly the two-reds problem 0038 described.

### Two consequences that undo earlier workarounds

- **`--refused` is red again in the portal.** It had been amber only because
  the accent was red and two reds one step apart cannot both mean something.
  The accent is green; the reason is gone. Amber goes back to meaning
  *outstanding*, which is what `tokens.css` always called it.
- **Focus is the accent**, platform-wide, as both exports draw it
  (`outline: 2px solid var(--acc)`). It was indigo because red could not be put
  in an outline. Green can: 5.90:1 on a card, against the 4.5:1 text needs.

### One typeface, and why ADR 0027's mechanism goes

Both exports use a single face throughout with `tabular-nums`. ADR 0027 had set
an *agreed* figure in a mono face and a *provisional* one in prose, so the
typeface itself said whether a number was final.

I kept that at first and put it to the business rather than dropping a
documented guarantee quietly. They ended it, and the reason is better than the
rule:

> If we kept it, they wouldn't necessarily know that this font is for a month
> that is still open or a month that is fixed and closed.

That is the whole objection, and it is correct. A signal only works if the
reader has been told what it means. The people who built the platform could
read it; a model opening the portal from an email never could. It was a private
convention wearing the costume of an affordance — and the fallback, in the one
place it was explained, was a glossary entry describing the mechanism instead
of the fact.

**The principle in 0027 survives; only its mechanism goes.** An agreed figure is
still set apart from a working one, in one place in the code (`moneyClass`), on
every screen — by weight and colour now, with the words beside it doing the
actual saying: *still adding up*, *open*, *closed*. `tabular-nums` on `body`
keeps figures aligned in a column without a second family.

The glossary entry for **Provisional** was rewritten to match. It used to
promise the typeface distinction in as many words; it now says what the screen
actually shows.

## Consequences

- Every existing maintainer screen re-skins by inheriting the new token values.
  That is the point of the token layer, and it is why this batch is small.
- **Every maintainer screen can now be dark**, so any colour defined in only one
  theme is a live bug rather than a latent one. Two were found and fixed on the
  way: `.button--primary` hovered to a literal `#000` (now `--ink-strong`), and
  the pay-history editor's three arrangement tints were light-only (now given a
  dark block). There will be more; they surface a screen at a time.
- The maintainer's half does not *default* to dark yet. The token layer supports
  it; stamping and toggling it is shell work, in Phase 01B.
- **One font family ships**: Inter, latin, three weights. `@fontsource/ibm-plex-sans`
  went with the two-halves split and `@fontsource/ibm-plex-mono` with the
  typeface rule. 26 `font-family: var(--mono)` declarations across 20 files are
  gone, and no rule was left empty by removing them.
- ADR 0038 is superseded, not deleted. It records why the split existed, which
  is worth keeping — the isolation it bought is the reason this change is a
  token edit rather than a rewrite.
