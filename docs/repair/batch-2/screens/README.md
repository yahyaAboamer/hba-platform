# Parity captures — Batch 2 review, 20 September 2026

Each `*-app-*.jpg` is the platform; each `*-export-*.jpg` is the approved HTML
for the same screen and state. **The number in the filename is the viewport
width the capture was actually taken at**, verified by reading `innerWidth` in
the page at capture time — not the width that was asked for.

## Why some are 1600 rather than 1280

The automation drives a Chrome window that is also the one in use on this
machine. `set-viewport.ps1` does set a real viewport — 1280 and 1440 were both
achieved and verified — but the window is restored to its previous size
between operations, so a capture taken a moment later can land at 1600.

Rather than relabel those, they are named for the width they were taken at.
Only the files marked `1280` were confirmed at 1280 by reading `innerWidth` in
the same batch as the screenshot.

## The export's own width

The approved export renders its app inside a container with its own
`LAPTOP WIDTH 1280 / 1440` toggle, so the export captures are at the width its
toggle is set to regardless of the browser window. That is the designer's own
control and is the right reference.

## Superseded, and kept anyway

**The complete sweep is in [`../visual/`](../visual/), captured 23 September in
a browser of its own.** Playwright launches its own headless Chromium, which
Chrome's window manager never hears about: nothing is opened, restored or
resized, the user's window is untouched, and the viewport is exactly the number
in the config - including 390, which window sizing could not reach at all
because Chrome will not make a window narrower than about 500px.

These six files are kept because they are honest evidence of what the
window-driven approach produced, and because the note above about filenames
carrying the *actual* width is the kind of thing worth being able to point at.
`../set-viewport.ps1` still works and is still the right tool if somebody needs
a real window at a real width; it is no longer the tool for a sweep.
