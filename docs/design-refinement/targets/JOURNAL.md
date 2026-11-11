# Targets refinement journal

**Started:** 10 November 2026 · **Branch:** `claude/targets-refinement` from `main` at `9d6c8e8`
**Scope:** Affiliates → Targets (`/affiliates/targets`, `frontend/src/departments/affiliates/Targets.tsx`), both modes, every month the picker offers.
**Not in scope:** the model portal's *My targets* (owner, 10 Nov: admin tab only). The shared month picker and `lib/targets.ts` change only if a fix needs them, and the portal is re-checked if they do.
**Evidence:** `D:/Desktop/HBA/HBA Engineering/evidence/targets-refinement-2026-11-10.zip` (outside the repository; 10.8 MB; SHA-256 begins `C99D176CAD578F45`): 40 before and 40 after captures (10 states × 390/1440 × dark/light), 6 before/after sheets, the capture and check scripts.

---

## 1. Skills used, and why
| Skill | Why | What it actually contributed |
|---|---|---|
| screen-refinement (project) | The owner's standard | The order of work, the tests in `references/tests.md` |
| Built-in browser | Blind first-time walk on staging, signed in by the owner | Findings T4, T8, T10 seen live before reading code |
| Playwright (headless, local) | State gallery on a throwaway DB | 40 before captures; density table |

## 2. Research
Not yet: principles are looked up at the decision step.

## 3. How the screen was explored

**Blind walk (staging, owner signed in).** Doubts, in order: what does *recorded weekly* mean; is a box a weekly figure or the month so far; what does *Confirm* do and why is it greyed; what is *Guarantee needs this record*; why can I type in December; on a phone, where are the stories box and the outcome (off the right edge); in September, why does Ali read *Target met · Confirmed · Nothing asked for yet* above two empty boxes *of 0*; why does Sara read *Below target* and then *Behind · 13 of 15* for a finished month.

**Routes.** One: `/affiliates/targets?month=` (also embedded on a model's page, `embedded`, not in scope). Old `/targets` redirects.

**States the code can render** (`Targets.tsx`): two modes; per row: no record, recorded zero, met, in progress, below target, before her start, backfilled outcome (pre-platform), confirmed / not confirmed, checkbox to confirm; pace: not started, nothing asked for, none this week, behind, on pace; bar: dirty count + Discard, saved line, Whole year, Confirm, Save; take-back panel closed/open; error banner; empty list.
Staging holds 2 models, so most of these were never seen there. The gallery seeds them: `seed_browser.py` (the export's 22) plus `docs/repair/batch-2/visual/seed_targets.py` (on-pace-but-missed, recorded zero, stale record, no requirement, guarantee with no requirement, before her start with a long name).

**Server meaning** (`app/modules/affiliates/api/targets.py`, `services/targets.py`, `services/pace.py`, `models/targets.py`):
- `achieved` = `MonthlyTarget.is_achieved`: `None` if counts not both recorded; else `actual_videos ≥ required_videos AND actual_stories ≥ required_stories` (every requirement). Pre-platform months: the stored outcome (ADR 0036), no counts.
- `pace` (D08, admin-only): `required = videos + stories`; `expected_by_now = min(ceil(required × week / 4), required)`; `done = actual_videos + actual_stories`; `on_track` if `done ≥ expected_by_now`. **Adds the two kinds together**; a finished month is measured at its last day (week 4).
- `verified`: a second person confirms the *numbers* (not the outcome); releases a guaranteed minimum. Refused on an approved month and on an unrecorded one.
- Save (`PUT`): whole grid or nothing, revision check against concurrent edits; refuses approved months (`assert_recordable`), backfilled months, months before her start. **No refusal for a month that has not started.**
- Client save (`Targets.tsx:218`): a row whose two *requirement* boxes are empty is skipped entirely.
- Roster (`grid_roster`): everyone except declined applications — pending applications and inactive models included.

## 4. Findings (evidence: `before/<shot>-<width>.png`)

| ID | Severity | Where | What | Evidence |
|---|---|---|---|---|
| T1 | risk | Recorded column, pace line | **"On pace" beside "Below target".** Pace adds videos and stories; the target needs each. Laila, Oct: 8 of 6 videos, 10 of 12 stories → *Below target · On pace · 18 of 18*. Can also say *On pace* all month to a model who will miss | `oct-achieved-1440` |
| T2 | copy | pace line | *On pace · 12 of 6* reads as 12 done of 6 asked; it is videos+stories done against the line due by this week | `nov-achieved-1440` |
| T3 | density | pace line, finished months | Pace still shown once the month is over, repeating the outcome (*Below target* / *Behind · 13 of 15*). Three status lines a row: 84px rows against the export's 56px | `oct-achieved-1440` |
| T4 | copy / risk | months before go-live | Backfilled outcome rows read *Target met · Confirmed · Nothing asked for yet* above editable empty boxes *of 0*; typing there is refused at save. Every other row is amber *No record yet* in a month nothing is owed for | `may-historical-1440`, staging Sept |
| T5 | risk | month picker | Pre-go-live months (`lockFor` = historical) open with no word that they are | `may-historical-1440` |
| T6 | risk | approved months | Boxes stay editable; the refusal comes only on save, as one banner for the whole grid. The grid does not know a month is agreed | `oct-achieved-1440` (6 approved) |
| T7 | risk (data lost) | Record achieved, no requirement | Counts typed for a model with no requirement are **silently dropped**: row skipped, *0 rows saved*, boxes empty again. Same for emptying both requirement boxes: nothing is cleared and the old values return | code `Targets.tsx:218`; to reproduce in build |
| T8 | risk | future months | Achieved counts can be typed and saved for December, which has not started | `dec-achieved-1440`, staging |
| T9 | density / meaning | roster | Pending applications (Habiba, Karim) listed with empty boxes, *No terms set*, amber *No record yet* | `nov-achieved-1440` |
| T10 | phone | whole table | At 390 the table is clipped: stories, outcome and date are off the right edge, reached only by scrolling inside the table | `nov-achieved-390`, staging |
| T11 | a11y / forms | save errors | A bad box is reported in one banner at the top; the box is not marked (the export draws it red), no `aria-invalid`. *Both or neither* only comes back from the server | `nov-bad-save-1440` |
| T12 | copy | empty list | A search with no match says *Nobody on the programme this month.* — false, and "programme". Export: *No model matches that search.* | `nov-search-none-1440` |
| T13 | risk (never hidden) | Whole year | Its consequence is not on screen: it rewrites every month of the calendar year including past ones, can turn a met month into a missed one, and skips agreed months. The tick sits in the top bar, out of view while editing lower rows | `nov-whole-year-1440` |
| T14 | risk / copy | Confirm | Not said what confirming does (releases a guaranteed minimum). *Confirm* is greyed with no reason. Checkboxes appear in *Set requirements* too | `nov-required-1440` |
| T15 | copy | save message | *One row saved.* / *12 rows saved.* Export: *Achieved counts recorded for November 2026* / *Requirements saved for …* | code |
| T16 | copy | subtitle | *recorded weekly* — unclear whether a box is a week or the month so far | staging |
| T17 | look | light theme | *No record yet* / *—* amber is faint in light; to measure contrast | `nov-whole-year-1440-light` |
| T18 | polish | take-back | *Take a confirmation back* is a lone panel holding one button under the table | `nov-achieved-390` |

Repetition count (a met, confirmed row): *Target met*, *Confirmed*, *On pace · n of m* — three lines for one month; the counts are also in the boxes beside them.

## 5. Decisions (owner, 10 November 2026: "Yes, all four"; pace rule re-asked)

- **T1-T3. Pace stays on the total, in any mix** (the owner's own rule, recorded in `tests/test_performance.py`; re-asked on 10 Nov when building showed that *per kind* would reverse it, and he kept it). Pace now shows **only in the running month, in *Record achieved*, and not on a row already met**, as *Week 2 · on pace* / *Week 2 · 3 short* / *Not updated in week 2*. A finished month shows its outcome alone, so *Below target · On pace* cannot appear. Alternative (per kind) dropped: it reversed an owner rule to fix a contradiction that hiding pace on finished months already removes.
- **T4-T8. A box only where a save keeps it** (ADR 0080). Agreed rows: figures as text, *Agreed in payroll* (new read-only `agreed` on the grid rows). Before the platform: the whole month read-only, said once in a note; no *of 0*. A month not started: no achieved boxes, a note with *Set requirements*, quiet *Not started* in place of amber *No record yet*. No requirement: *Set requirements first* (a button that switches mode) in place of the boxes. No server guard changed.
- **T9.** Bare applications (pending, no terms ever) left off `grid_roster`, so off Today's *targets not set* too (RULES.md updated). A pending model with terms stays — new affiliates start pending until their code is verified, so *all pending* would have hidden models being onboarded.
- **T10.** Phone card layout at ≤ 640px (ADR 0080): name, outcome, *Videos* and *Stories* side by side; date left off.
- **T11.** Box marked as the export marks it, reason under it, `aria-invalid` + `aria-describedby`, both-or-neither and *Type 0 for nothing asked* checked before sending, focus moved to the first marked box.
- **T12, T15.** *No model matches that search.*; *Requirements saved for …* / *Achieved counts recorded for …*; year-wide detail in a separate note.
- **T13.** Note under the bar when *Whole year* is ticked; save reads *Save for all of 2026*.
- **T14.** *(Superseded by §10: confirming removed.)* Ticks and *Confirm* only in *Record achieved*, never on agreed rows. *Confirm numbers* / *Confirm 2 models' numbers*; beside it why it is greyed, or which guaranteed minimum it releases; greyed while edits are unsaved (*Save first*), since confirming confirms what is on record, not what is on screen — found while building.
- **T16.** Subtitle *November 2026 · the month so far, updated weekly* in the running month; the month alone otherwise.
- **T17.** Measured in light: every tone 5.3:1 or better. No change.
- **T18.** *(Superseded by §10.)* *Take a confirmation back* is a quiet button; the panel opens only when used.

## 6. Before and after

Sheets: `evidence/targets-work/sheets/01-06`.

| Screen (390, dark) | Words before | Height before | Words after | Height after |
|---|---|---|---|---|
| November, achieved | 462 | 2315 | 353 | 3598 |
| October, achieved | 479 | 2386 | 343 | 3425 |
| December | 325 | 1828 | 286 | 3087 |
| May (pre-platform) | 355 | 1999 | 299 | 3107 |

The phone page is taller because nothing is hidden off the right edge any more: before, the stories box, outcome and date of every row were outside the screen. Words fell by about a quarter.

## 7. Verification
- Frontend: `npm test` 1240 passed; `npm run build` clean. New `TargetsRefinement.test.tsx` (18 tests): one per finding, three more for the review's findings.
- Backend: whole suite (`run-suite.sh`, own `OUT_DIR`/`REV`, disposable `hba_targets_test`): **129 of 129 files passed, 0 failed**. Before that, `tests/test_targets_api.py` 37 passed (2 new: bare application off the grid; `agreed`), `tests/test_today.py` 30, `tests/test_targets.py` 44, on a separate disposable DB (`hba_targets_test`) because another session was using `hba_platform_test`.
- Phone sweep 360 / 390 / 430 on November, October, December, May: no sideways scroll, no control under 44px, no input under 16px, 0 console errors.
- Touch (Pixel 7 emulation, real `tap()`): a tick enables *Confirm 1 model's numbers*; *Set requirements first* switches mode.
- Keyboard: search → mode → each row's name, videos, stories in order; focus ring on each.
- Both themes captured; light contrast measured.
- **Independent review** (`ecc:code-reviewer`, asked first whether any request, permission, guard or calculation changed): **none changed**; the two server changes are the read-only `agreed` field and the roster. It found three bugs in the new code, all fixed with a regression test:
  - **R1 (financial).** Validation checked only the mode on screen, but a save sends both pairs: a box mistyped under *Set requirements* (`8x`) was sent as **0** after switching to *Record achieved*, overwriting a stored requirement. Now all four boxes are checked whatever the mode.
  - **R2.** Requirements typed for a model with none, then a switch to *Record achieved*: the row locked, the save sent nothing, and the figures vanished (the T7 failure again, by another route). The rows a save sends no longer depend on the mode; Save stays available in a not-started month.
  - **R3.** A bad box on a row hidden by the search: *Fix the marked boxes* with nothing marked. A refused save now names the model and the problem, switches to that box's mode, clears the search, and focuses the box.
  - Noted (not a bug): a half-typed new requirement, or emptying both requirement boxes, now asks for a number where it used to save 0 or silently do nothing.
- **Not verified:** a real phone; VoiceOver / TalkBack; staging (nothing deployed); the model page and Today screens beyond their tests.

## 8. Mistakes and lessons
1. The capture script built its output folder from a URL path, so the space in *HBA Engineering* became `%20` and the first run wrote nowhere useful. Use `fileURLToPath`.
2. **A recommendation can reverse an owner rule nobody quoted.** Pace per kind was proposed and approved before the code showed the owner's own *any mix* rule. Read the tests for the rule's history before proposing a change to it.
3. **"Pending" is not "applicant".** New affiliates start pending until a code is verified; hiding all pending would have hidden models being onboarded. Check the status lifecycle before filtering by status.
4. **Lesson 9 again (CSS weight).** Phone rules written as `.targets__grid td.x` lost to the shared `.table.targets__grid td.x` reset; the date showed and the outcome stacked. Tests passed; the capture showed it.
5. **Another session shares the test database.** Two pytest runs on `hba_platform_test` deadlocked on TRUNCATE. Use a separate disposable DB, as CLAUDE.md says.
6. The worktree has no `.venv`: `run-suite.sh` needs `PYTHON=` pointing at the main checkout's. Its log defaults to `/tmp` and is keyed by commit, so a run on an unchanged `HEAD` counts other sessions' results: set `OUT_DIR` and `REV`.
7. **Validate what the save sends, not what the screen shows.** A two-mode screen hid a box from validation that the save still sent (R1). The reviewer caught it; the tests had only exercised one mode at a time.

## 9. Open items
- Ship on the owner's word: commit, PR, merge, deploy (each separately).
- Leaving with unsaved figures by a link inside the app (a model's name) still drops them; the browser asks only for a closed tab or reload, and the month picker refuses. The router has no navigation block (`BrowserRouter`).

## 10. Second pass: does each feature earn its place? (owner, 11 November 2026)

The owner asked for one more try, *with reasoning on the features and functions*: *is confirming the target reasonable? is having the target as boxes that anyone can press by mistake reasonable?* The first pass had polished both without asking either.

**F1. Confirming checked nothing it claimed to.**
- It changed pay in one case only: a `base_guarantee` model who met her target (`calculate.py`: a met, unconfirmed month blocked payroll; a miss approved without it). The tick appeared on every recorded row.
- The content manager and the affiliate manager each hold record *and* confirm (`permissions.py`), so the person who typed the counts could confirm them a second later. The code recorded this as an accepted exposure.
- It could be pressed mid-month; the next weekly count wiped it.
- It guarded one direction: a typo that made a month look met waited for a check; a typo that made it look missed cost the guarantee unchecked.

Options put: confirm only where it releases money, after the month ends; or require a different person; or keep. **Owner: remove it.** *When we record what the model has done, it is already confirmed.* ADR 0081; RULES.md updated.

Built:
- Server: guarantee applies when met; `targets_achieved_but_not_verified` gone; setup gap `target_not_verified` → `target_not_recorded` (nothing recorded); `/verify`, `/unverify`, `targets.verify` removed. `verified_by`/`verified_at` and their constraint stay, unread (no migration); clearing counts still clears an old confirmation so the constraint holds.
- Screen: ticks, *Confirm*, *Not confirmed* and the take-back panel removed.
- Model portal: *Waiting to be confirmed*, *met — to confirm*, *being checked* and *HBA must confirm* removed; a met guarantee month reads *Met, so your guaranteed minimum applies.* Team access: *Set and record content targets*.
- Consequence for open months: a met guarantee month waiting on a confirmation pays its minimum on its next calculation and stops blocking payroll. Agreed months are frozen in their snapshots.

**F2. Every box was live, and a slip was written with everything else.** The owner left the choice to engineering. With the check gone, a typed count releases money by itself, so:
- **Save lists the changes first** (lifecycle dialog): *Save 2 changes to October 2026?*, each model, each box old → new, and any turn of the record with its effect (*Target met → Below target · her guaranteed minimum no longer applies*). *Keep editing* / Escape go back with the boxes as typed. A box typed back to its value (`07` for `7`) is not a change.
- **Switching month over unsaved figures is refused**, with the count and *Save or discard them first*; closing or reloading the tab asks first (`beforeunload`).
- Rejected: read-only until *Edit* (a click on every weekly entry, and no help against a wrong number once editing).

**Verification (second pass).**
- Frontend: `npm test` 1240 passed (the confirm tests replaced by five for ADR 0081: no confirm step, the change list and its turn, *Keep editing*, `beforeunload`, `changesFor`); `npm run build` clean.
- Backend: whole suite on a disposable DB (`hba_targets_test`): 128 of 129 files passed; the one failure (`test_bonuses.py`, a test still passing `verified=True` to a helper) fixed and re-run, 23 passed. The seven files touched by the fingerprint fix re-run after it: 290 passed.
- Browser (local app, throwaway `hba_browser_targets`, captures in `evidence/targets-work/after-0081/`): no tick, *Confirm* or confirmation word on October at 390 / 1440, dark and light. Lowering a met guarantee's videos lists *Videos achieved 4 → 0* and *Target met → Below target · her guaranteed minimum no longer applies*; focus lands on *Keep editing*; Escape returns to the page with the box as typed and focus on *Save changes*. Switching month over an unsaved figure is refused (*1 unsaved change on October 2026. Save or discard it first.*) and the picker snaps back. Saving writes it and the row reads *Below target*. No sideways scroll at 390. Console: one 401 per session, the sign-in page's check before signing in.
- **Independent review** (`ecc:code-reviewer`): no wrong guarantee path found; one real fault and four small ones, all fixed:
  - **R4 (money-adjacent).** Removing `target_verified` from the fingerprint hash would have made **every agreed month** read *changed since approval*, with nothing behind it moved. Agreed months now also match the pre-0081 fingerprint (`agreed_source_unchanged`, used by the payroll view and corrections); a test rebuilds the old hash by hand.
  - One portal sentence still said *when it was confirmed*; a dead `verified` field in the home payload; the dialog re-focused on parent re-renders and did not return focus to *Save changes* on close; `seed_browser.py` still called `verify`.
- **Not verified:** a real phone; VoiceOver / TalkBack; staging. Leaving by an in-app link with unsaved figures (open item above).
