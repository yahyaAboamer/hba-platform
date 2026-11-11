---
name: screen-refinement
description: HBA's standard method for enhancing an existing screen, tab or module of the platform (admin or model portal) - its UX, wording, density, layout, phone behaviour, accessibility or visual polish. Use whenever the owner asks to refine, improve, enhance, polish, audit, simplify, declutter or redesign an existing screen or tab (Payments, Payroll, Wardrobe, Sales, Targets, Inbox, Team, Settings, the portal, and so on), or to "do what we did on Payments" for another screen. Not for building a brand-new feature or for a one-line copy fix.
---

# Screen refinement

The method used on the Payments tab (PRs #151-#154, ADRs 0074 and 0075),
written down so every screen gets the same treatment. The worked example,
with every finding, decision and screenshot reference, is
`docs/design-refinement/payments/JOURNAL.md`; its tools are in
`docs/design-refinement/payments/tools/`.

**What this method is for:** a screen that already works, made correct in
meaning, lighter to read, safe to act on, and good on a phone, without
changing any calculation, request, permission or safeguard unless the owner
asks for that separately.

## Ground rules (they override anything below)

- The owner's explicit words, then the approved export, then our ADRs, then
  any skill's advice. A departure from the export is proposed, recorded as an
  ADR with *what it costs*, and built only once the owner accepts it.
- Money: read `docs/RULES.md` and the server's own formulas before touching
  any figure. The client never sums money; it chooses which server figure goes
  under which label.
- Nothing is written to staging or production by a review. No committing
  before reporting results to the owner; merging and deploying are two more,
  separate permissions.
- Owner-facing reports in plain English, consequence first (memory:
  *explain technical things in plain English*). Never "programme".
- One journal per screen, kept as you go, not reconstructed at the end.

## The steps

Work them in order. Steps 1-6 are looking; nothing is changed until step 7.

### 1. Set up

- A branch per screen from `origin/main`: `claude/<screen>-refinement`.
- Start the journal from `references/journal-template.md` at
  `docs/design-refinement/<screen>/JOURNAL.md`.
- Ask the owner one scoping question early if a **shared** part is involved
  (a month picker, a table, a shell element): is it in scope? (Payments
  lesson: the owner counted the shared month picker as part of the tab.)

### 2. Walk it as a first-time user, before reading code

On staging, as the role that uses the screen (payer, content manager, model),
with no prior knowledge. Note every moment of doubt: what is this figure,
what happens if I press this, where do I go next, what can't be undone.
Do this blind; reading the code first makes you forgive the screen.

### 3. Map routes and every state

- Routes from the department's `department.tsx` (or the portal's router).
- Every state the code can render: empty, loading, error, each status, each
  edge (zero, negative, overpaid, credited, missing terms, changed
  destination, a long name, many rows).
- Compare with what real data holds. **The unseen states are the to-do
  list.** On Payments, staging had 2 models and most states were never seen.

### 4. Read the server's meaning

For every figure and every label on the screen, find the server field and
the formula that produces it (`app/modules/.../api/*.py`, `services/*.py`).
Write the formula into the journal. Two endpoints that describe one fact
(a row and a statement) must be traced to the same source.

**Then question every feature, not only how it looks** (the owner, on
Targets: *is confirming reasonable? are boxes anyone can press by mistake
reasonable?*). For each action and each editable field, write in the
journal:

- **What it changes**: money, a record, what someone else sees. Trace it
  to the formula, not the label (*Confirm* changed pay in one case only).
- **Whether it checks anything**: who can do it, and can the same person
  undo or satisfy it alone? A check one person passes by themselves is a
  step, not a safeguard.
- **What a slip does**: a stray tap, a wrong number, an old month edited,
  leaving with unsaved work. Is there a way to see it before it is written,
  and a way back after?
- **Whether it should exist at all.** Removing or merging a step is a
  finding like any other, and it goes to the owner (it changes a rule).

### 5. Build the state gallery (see `references/harness.md`)

Make every state visible at **390 and 1440**, in both themes, with the same
setup before and after so captures compare exactly.

- **Default:** the approved harness, `docs/repair/batch-2/visual/` - a
  throwaway local database seeded with the states. The real server computes
  the figures, so fixtures can't disagree with the formulas.
- **Only if a state can't be seeded:** the staging-origin read-only harness
  (`tools/harness.tpl.js` here), and only with the owner's go-ahead and his
  own sign-in: GETs pass through, missing states are injected, **every write
  answers 418**. CLAUDE.md forbids reusing a person's staging session for
  sweeps otherwise.
- Fixtures: one fixture per business fact; every endpoint's response
  derived from it, using the server's formula and the real enums.

Capture the *before* set now. Keep it outside the repository.

### 6. Write findings, then decide

Run every test in `references/tests.md` against every state. Each finding
gets an ID, a severity (financial / risk / a11y / density / copy / polish),
where, what, and its screenshot. **No decisions until the list is complete.**

Then decide each one with the alternatives considered and why they lost.
Look the principle up in `references/design-sources.md`; a principle is
adopted only when it also fixes something actually seen. Consult the
installed design skills as cross-checks (see *Skills* below).

**Stop and report to the owner** when a decision changes what the approved
export shows, touches money meaning, or removes something people use.

### 7. Build

- Change only the screen in scope. Keep the existing tokens; add no icons,
  gradients or colours.
- A regression test for every finding that can regress (labels, which
  buttons show in which state, totals that must match the server, focus).
- Existing tests that assert copy change only with the copy, deliberately.

### 8. Verify (all of it, and say what was not)

1. `cd frontend && npm test`, then `npm run build` (the real type gate).
   Backend touched: `bash docs/repair/batch-1/run-suite.sh` on the
   disposable DB.
2. Capture the *after* set with the same gallery; compose before/after
   sheets (`tools/compose.py`); **look at them**. Tests passed while the
   Payments phone list fell apart from one CSS specificity loss.
3. Phone sweep at 360 / 390 / 430 (`tools/checks.js`): no sideways scroll,
   no control under 44px, no input text under 16px, 0 console errors.
4. Keyboard: tab order, visible focus ring, dialogs focus their act and
   return focus on Cancel, errors set `aria-invalid` + `aria-describedby`.
5. Touch: a separate device-emulated session with real `tap()` events.
6. Both themes, every state.
7. Density measured (`tools/words.js`): words and page height per screen,
   before and after, in the journal.
8. Independent review: `ecc:code-reviewer` (plus `ecc:react-reviewer` for
   heavy React changes), asked first "did any request, permission or guard
   change?". Fix, re-test, re-capture.
9. Record honestly what was **not** verified: a real phone, VoiceOver or
   TalkBack, other screens that share a changed component.

### 9. Record and report

- ADR for each divergence from the export (`docs/adr/`, index in its
  README), with *what it costs* and *not changed*.
- Journal: findings, decisions, measurements, verification, mistakes,
  open items, and new method lessons (add those back to this skill).
- Evidence ZIP to `D:\Desktop\HBA\HBA Engineering\evidence\<screen>-refinement-<date>.zip`,
  never in the repo; note its SHA-256 in the journal.
- Report to the owner in plain English, with the before/after sheets. Wait.

### 10. Ship (each on the owner's word)

Commit and PR → CI → merge → deploy staging → deploy production
(see the current handoff's *Deploy* notes) → a live, read-only browser check
on both, the owner signing in himself → update the handoff.

## Skills, and what each is for here

| Skill | Use it for |
|---|---|
| `playwright-cli` | The gallery, captures, phone/keyboard/touch sweeps, live checks |
| `ui-ux-pro-max` (vendored) | Cross-check on hierarchy, forms, states, a11y. Recommendations only |
| `design-taste-frontend` (app-screen rules, `references/app-screens.md`) | Restraint; numbers that add up; no ornament. Not its `draw.mjs` deal |
| `web-design-guidelines` (Vercel) | Forms, focus, errors, labels, copy checklist |
| `apple-design` | Touch targets, answer-first order on a phone |
| `ecc:code-reviewer` | The independent review (step 8) |
| `humanizer` | Optional: a last pass on long owner-facing reports |

Do not run every skill mechanically; use the ones the screen needs.

## References

- `references/tests.md` - the tests every screen gets, with how to run them.
- `references/design-sources.md` - the outside sources and what was taken.
- `references/lessons.md` - mistakes already made once; don't repeat them.
- `references/harness.md` - building the state gallery.
- `references/journal-template.md` - the journal's sections.
- `tools/` - generic copies of the Payments tools; edit their CONFIG block.
