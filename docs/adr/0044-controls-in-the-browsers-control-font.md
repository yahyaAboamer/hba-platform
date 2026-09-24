# 0044 — Buttons in the browser's control font, as the approved page draws them

**Status:** accepted
**Date:** 2026-09-24
**Amends:** [0043](0043-type-as-the-exports-set-it.md) (what it left of controls)
**Related:** `docs/redesign/designs/Admin Dashboard.dc.html` (`.ad input,
.ad select, .ad textarea {font-family: var(--font-body)}`), the batch E
follow-up in `docs/repair/batch-2/visual/CHECKLIST.md`

## The situation

Batch E measured that the exports' buttons render in the browser's own
control font - Arial in the reviewing Chromium - and kept ours in Inter,
calling the export's font a missing reset. The owner's answer, 24 September:
*match the approved rendered HTML; an explanation for a difference does not
approve that difference.*

The rendered page is consistent about it. The admin export deliberately gives
fields and selects Inter (`.ad input, .ad select, .ad textarea`) and leaves
`button` to the browser. Of 150 buttons across both exports, 146 name no
family and draw in the control font at the browser's `line-height: normal`, at
400, and at 13.33px unless the button sets a size. The four that name one -
the portal's avatar and tabs, the admin sidebar, one product sheet - are Inter.

## Decision

- `button { font: revert }`: a button is handed back to the browser's
  stylesheet and renders as the export's does on the same device. A screen
  class that sets a size or weight still applies.
- Inputs and selects stay `font: inherit` (Inter), as the export sets them.
- Where the export draws a **button** and ours is a **link** - `.button`
  links, a payments row's name, the → links under a card, *How this adds up*,
  *Compensation history* - `:where(.control-font, a.button)` gives the link the
  same `font: -webkit-small-control` a button's own stylesheet uses. Measured
  identical in Chromium (142.44 × 16px for the same line either way).
- Rules that re-set `font: inherit` on a button the export draws in the
  control font are removed on the screens in scope: the portal's Orders
  filters and rows, its *← Back*, and the profile's section tabs.

## What this costs

- **The face of a button is the device's, not ours**: Arial on Windows
  Chromium, San Francisco on an iPhone, Roboto on Android - exactly as the
  approved page is. Two screenshots from two devices will not match each
  other, as the export's would not.
- A browser without `-webkit-small-control` (Firefox) draws `.control-font`
  links in `system-ui` rather than its button face.
- Buttons outside this batch's screens that still set `font: inherit` (the
  You screens, terms editing) stay in Inter until their screens are reviewed;
  they are listed in the checklist.

## Result, measured

Portal order rows 92px against 92px (95 before); month list rows 41 against
41; the Payments row name Arial 13.5px/400 against the same.
