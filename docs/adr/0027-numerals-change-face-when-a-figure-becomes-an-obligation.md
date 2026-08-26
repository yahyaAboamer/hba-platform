# 0027. Numerals change face when a figure becomes an obligation

**Status:** Accepted
**Date:** 2026-08-26

## Context

§12.1 pins the visual direction: *"Reference point: Stripe Dashboard — financial-first,
precise numerals, unambiguous money states, calm density, trustworthy rather than
decorative."* §12.3 fixes the navigation. §12.5 fixes the responsive rules and adds one
absolute: **money never wraps or truncates at any width.**

So the layout is largely decided. What is not decided is how the interface carries the
distinction the entire backend was built around, and which the old dashboard got wrong:

> A **calculation** can change. An **obligation** cannot.

Seven phases of work exist to keep those apart. `payroll_snapshot` freezes one. §11.1
separates calculation state from settlement so a single column cannot conflate them — the
defect that produced *"Approved · Partially paid"*. Phase 6 makes approval the moment one
becomes the other.

An interface that renders both as *"E£2,000"* in the same grey throws that away at the last
step.

## Decision

**The typeface of a figure says whether it is real.**

| The figure | Set in | Reads as |
|---|---|---|
| Provisional — calculated, not approved | IBM Plex **Sans**, tabular figures, quiet grey | a working number |
| Agreed — frozen in an approved snapshot | IBM Plex **Mono**, ink, medium | a commitment |
| Blocked — cannot be approved | Sans, with the blocker on the same line | a number that is not owed yet |

A face change is categorical where a colour or weight change is a matter of degree. Somebody
scanning twenty rows at month end is asking a yes-or-no question — *can I pay this?* — and
the answer arrives before they have read the digits.

**Colour is reserved entirely for money state.** Outstanding, settled, refused. Navigation,
headings, active states and panels carry none of it. An interface where everything is
coloured has no way left to say *this one matters*.

The single exception is the focus ring, which uses an indigo that appears nowhere else —
focus is the one thing that must never blend into its surroundings.

**No shadows, no card elevation, no rounded panels.** Hairline rules and space. §12.1 asks
for trustworthy rather than decorative, and a drop shadow is decoration that has learned to
look like structure.

## Consequences

The distinction is legible without being explained, which matters because it is the one
thing a person using this at month end must not get wrong. The alternative — a legend, or a
tooltip — puts the explanation somewhere nobody reads it.

**Two faces from one superfamily**, self-hosted rather than fetched from a font CDN. Plex
Sans and Plex Mono were drawn together, so mixing them in a single row reads as intentional
rather than as a fallback. Self-hosting keeps a month-end tool working without a third-party
request, which is the same reasoning that kept Redis and object storage out.

**It constrains later screens**, deliberately. The affiliate portal (Phase 9) is phone-first
and a warmer thing; it may look different. It may not disagree about which numbers are real.

## Alternatives considered

**Colour-code the states.** The obvious answer, and it spends the one signal that should be
saved for money outstanding. It also fails for anybody who cannot distinguish the hues, on a
distinction that decides payment.

**A badge on every row.** Twenty badges in a column is twenty things to read. The point is to
answer the question *before* reading.

**Grey out provisional figures.** Weight and opacity read as *less important*, not as *not
yet agreed*. A provisional figure is not less important — at month end it is the one being
worked on.

**Follow Stripe more literally.** §12.1 names it as a reference point, not a template. Stripe
is showing you a business; this is showing one person twenty obligations and refusing some of
them. The refusals are the part worth designing around.
