# Batch report — Phase 01B, navigation and shells

**Date:** 9 September 2026
**Branch:** `phase01a/design-tokens`, continuing from 01A
**Requested scope:** Wire authenticated navigation and responsive shells. Admin six tabs, model five tabs plus You. Preserve all required secondary routes, access and onboarding, consistent Back/month context and server permissions. Show real data where it exists; unfinished areas clearly identified and not released as functioning pages.

**Delivered behaviour:** Both halves now carry the approved navigation. The
maintainer's tool has six sections and a theme it remembers; the portal has the
approved five tabs with You behind the avatar. **Nothing was deleted to make
room** — every section that left a nav kept its route, its permissions and a
visible way in.

---

## Review

### What the owner should try

1. **Sign in.** The maintainer's tool is now **dark by default**, with a
   *Light theme* switch at the bottom of the sidebar. It remembers per device,
   under its own key — flipping the tool does not flip a model's phone.
2. **The six sections**: Home · Models · Products · Targets · Payments ·
   Settings. Overview is called Home now, Affiliates is called Models. Their
   URLs did not change.
3. **Find Orders and Payroll.** They are not in the sidebar any more. Orders is
   a link on Home beside the count it explains; Payroll is a link on Payments,
   above the figures. Both screens are exactly as they were.
4. **Open Products.** It says *Not built yet*, names Phase 03, and looks like a
   dashed notice rather than a page. That is on purpose.
5. **On a phone**, as a model: Home · Orders · Wardrobe · Targets · Ranking, and
   the avatar for You. Wardrobe, Targets and Ranking say the same thing Products
   does. **Payments moved into You** — first row, *"What you have been paid"*.
   Year and Grow are links at the bottom of Home.

### The one change you will notice immediately

**The maintainer's tool defaults to dark.** The approved admin export is
dark-first (`.ad` is dark; `.ad[data-t="light"]` is the override), so this
follows the design rather than reinterpreting it — but it is the two of you who
open this at month end, and a tool that changes colour overnight is worth
flagging rather than burying.

The switch is in the sidebar and it sticks. If you would rather it opened light
and offered dark, that is one word in `Layout.tsx` — say so and it changes.

### Approved-design deviations

**Two, both of the same kind: the design shows a destination that does not exist
yet, and I did not fake it.**

- **Payroll has no screen in the finished design.** Approval happens inside one
  model's payment view. Building that is 05B/06A, and doing it now would mean
  rewriting approval before the financial rules change under it in Phase 05. So
  Payroll keeps its screen and gains a link from Payments. The design's shape is
  the destination; this is the step that does not break payroll on the way.
- **Year and Grow have no tabs in the design** — the year's chart belongs on
  Home (M01) and the code is in the header chip. Folding them in is 07A. Until
  then both keep a link from Home, because deleting a working screen to match a
  drawing before its replacement exists is not a redesign.

Neither is a disagreement with the design. Both are sequencing.

---

## Engineering evidence

**Rules and IDs covered:** S01, S02, S03, S07 (deep links and paths preserved),
S05/D10 (the permission map, recorded as fact). **UI01, UI02 and UI51 are not
marked complete** — the shells they sit in are done, the per-screen loading,
empty, stale and error states are not, and those are what those rows are about.

### Files changed

| File | What |
|---|---|
| `components/Layout.tsx` | Six sections; Overview→Home, Affiliates→Models; theme toggle; the reasoning for what left the top level |
| `components/AffiliateLayout.tsx` | The approved five tabs; a note on where Month, Payments, Year and Grow went |
| `components/NotBuiltYet.tsx` + `.css` | **New.** The honest placeholder |
| `lib/theme.ts` | Two keys, one per half; `applyMaintainerTheme` stamps `<html>` |
| `App.tsx` | `/products` route |
| `screens/AffiliatePortal.tsx` | `/wardrobe`, `/targets`, `/ranking` routes |
| `screens/Overview.tsx` + `.css` | Renamed to Home; *See every attributed order* |
| `screens/Payments.tsx` + `.css` | *Agree a month before paying it* |
| `screens/MyMonth.tsx` | *Your year so far*, *Selling more* |
| `screens/MyDetails.tsx` | *What you have been paid*, first in the menu |
| `screens/Affiliates.tsx`, `Orders.tsx`, `Compensation.tsx`, `DataPanel.tsx`, `Settings.tsx` | Headings and copy say Models and *Attributed orders* |
| `styles/base.css` | **A link finally has a colour** — see below |
| `docs/redesign/ROUTE_AND_PERMISSION_MAP.md` | **New.** Every route, its way in, and who may open it |

**No API, service, model or migration was touched.** Still no schema change, no
money code, no permission change. `permissions.py` was read, not edited.

### One bug found by looking

`base.css` had **no rule for `a` at all**, so every plain link took the
browser's blue. Survivable on the old near-white ground; wrong on both approved
ones, and the single colour on the page that no token could reach. Links now
take `--accent-text` — the text step, because on dark the chrome step is not the
legible one — which is what both exports do (`a{color:#23A95C}`).

It only became visible because 01B added the first plain links to Home and
Payments. That is the second theme bug this phase, and both were found by
opening a screen rather than by grepping.

### The reachability question, deliberately

Moving two sections out of a sidebar is precisely the failure
`test_reachability.py` exists for — *"inviting a model had no control anywhere;
the whole flow existed and could not be started"*. So every moved destination
got a link in the same commit, and the map records where each one is. The suite
agrees: **1589 passed.**

**UI52 (the reopen page and endpoint) was deliberately left alone.** My Phase 00
report suggested retiring it in 01B; the package assigns it to **05B/09**, and
the package is right — it is a financial capability, not a navigation item, and
removing it belongs with the approval work that replaces it. It stays routed and
admin-only until then.

### Commands, results, environment

| Check | Result |
|---|---|
| `cd frontend && npm test` | **106 passed**, exit 0 — up from 104 because the accent guard walks the two new files |
| `cd frontend && npm run build` | exit 0 |
| `pytest -q --color=no` against `hba_platform_test` | **1589 passed**, 201.53s, **exit 0** |

Green before and after, so no pre-existing failures to separate from
regressions. Environment as recorded in `BASELINE_REPORT.md` §10.

### Visual comparison

Performed against the running app with synthetic seed data, at 1440 and at 430:

| State | Result |
|---|---|
| Maintainer Home, dark (default) | ✅ Six sections, green active tab, *See every attributed order* |
| Maintainer Products, dark | ✅ Dashed notice, amber *NOT BUILT YET*, names Phase 03 |
| Maintainer Payments, light, after toggling | ✅ Toggle sticks; *Agree a month before paying it* present and green |
| Sign-in after toggling | ✅ Follows the maintainer's theme — the reason it is stamped on `<html>` and not on the layout |
| Portal Home, 430px | ✅ Home · Orders · Wardrobe · Targets · Ranking, Home active |
| Portal Wardrobe, 430px | ✅ Placeholder reads correctly; no month bar, which is right — it is not month-scoped |
| Portal You | ✅ *What you have been paid* first in the menu |

No real, customer or production data. No credentials or PII in this report.

---

## Continuation

### Limitations

- **Per-screen states are untouched.** Loading, empty, stale and error still
  vary screen by screen; UI51 is a sweep, not a batch, and it belongs with the
  screens as they are rebuilt.
- **Nothing was rebuilt to the design's layout.** 01B moved and labelled; the
  screens behind the tabs are still the ones that were there this morning.
- **No responsive work beyond what existed.** The sidebar already collapses
  below 1024px and the portal is already phone-first. Neither was redesigned.
- **The maintainer's dark default is new and unreviewed on a real machine.**
  It follows the export; it has been seen only on this one.

### Decisions recorded

- The permission map is now written down (`ROUTE_AND_PERMISSION_MAP.md`),
  including the factual half of **D10**: *Marketing* → `content_manager`,
  *Finance* has no equivalent, and whether anyone needs `payments.record`
  without full admin is still the owner's to answer.
- Paths were **not** renamed with their labels. `/affiliates` reads *Models*.

### Next

**Phase 02A** — `docs/redesign/prompts/02_MODELS_AND_SETUP.md`, first batch:
invitations, applications and the directory. Note before starting it that
**02C's terms editor already exists** (shipped in `63c64c3`, before this
package arrived), so 02 is smaller than the roadmap assumes — the baseline
report §5 has the row-by-row detail.

### Live changes

**None.** Nothing deployed, no production branch moved, no financial data
touched. The branch is pushed; it is not merged.
