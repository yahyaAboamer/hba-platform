# 0039 — One palette across both halves

**Status:** accepted
**Date:** 2026-09-09
**Supersedes:** [0038](0038-the-portal-wears-the-brand-the-tool-does-not.md)
**Amends:** [0027](0027-numerals-change-face-when-a-figure-becomes-an-obligation.md) — colour, not typeface
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

### What does not change

**ADR 0027's typeface rule stands.** An agreed figure wears the mono face and a
provisional one does not. The exports use a single face with `tabular-nums`
throughout, and this is the one place the implementation deliberately does not
follow them — the distinction is a *meaning*, the glossary explains it to models
in those words, and a provisional figure that looks exactly like a settled one
is the specific confusion that costs somebody money. Flagged in the Phase 01A
batch report for the business to accept or reject on a real screen rather than
changed quietly.

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
- `@fontsource/ibm-plex-sans` is removed. Inter carries prose on both halves,
  and Plex Mono stays for the one thing it still says.
- ADR 0038 is superseded, not deleted. It records why the split existed, which
  is worth keeping — the isolation it bought is the reason this change is a
  token edit rather than a rewrite.
