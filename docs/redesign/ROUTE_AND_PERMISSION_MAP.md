# Route and permission map

Written in Phase 01B, from the code rather than from the design. It answers two
questions the redesign keeps raising and neither export can settle: **where did
that screen go**, and **who is allowed to open it**.

Read with `docs/redesign/SCREEN_AND_ACTION_MAP.csv` (what each screen must do)
and `app/core/permissions.py` (the authority for the second column).

---

## Who exists

Four roles, and there is no "Marketing" or "Finance" among them. The prototype's
labels are use cases, not accounts — rule S05.

| Role | Holds |
|---|---|
| `admin` | Everything, and **the only role with `payments.record` or `payroll.reopen`** |
| `affiliate_manager` | `affiliates.view/manage`, `compensation.manage`, all three `targets.*`, `payroll.approve`, `invitations.send`, `audit.view` |
| `content_manager` | `affiliates.view/manage`, `compensation.manage`, all three `targets.*`, `audit.view` |
| `affiliate` | **Nothing.** A model reaches her own portal by owning the record, not by holding a permission |

Two things worth naming because they look like oversights and are not:

- **`content_manager` both verifies targets and sets compensation.** Verification
  is what releases a base guarantee, so there is no second pair of eyes between
  judging a target met and the money that follows. `permissions.py` records that
  the business accepted this knowingly. Approving payroll and recording payments
  are still elsewhere, so the obligation and its settlement stay separate acts.
- **The prototype's *Finance* has no equivalent.** Recording a payment is
  admin-only. Whether anyone should hold `payments.record` without full admin is
  **D10**, and it is the owner's to answer — not something to infer from a label
  on a mockup.

Permissions are enforced in the service and the API, never by a hidden button.

---

## The maintainer's half

Six sections, from rule S02. **The paths did not change** — `/affiliates` still
reads *Models* rather than moving to `/models`, because the label is what the
business says and the path is what two people have bookmarked (S07 asks for deep
links that keep working).

| Section | Path | Screen | Needs |
|---|---|---|---|
| Home | `/` | `Overview` | a session |
| Models | `/affiliates` | `Affiliates` | `affiliates.view` |
| Products | `/products` | **`NotBuiltYet`** — Phase 03A/03C | a session |
| Targets | `/targets` | `Targets` | `targets.*` to edit |
| Payments | `/payments` | `Payments` | `payments.record` to record |
| Settings | `/settings` | `Settings` | `settings.manage`, `audit.view` |

### Secondary destinations, and the way in to each

S02 is explicit that these keep every necessary operation without adding
top-level clutter. **Every one has a link; none is reachable only by typing a
URL.**

| Path | Screen | Reached from | Note |
|---|---|---|---|
| `/orders` | `Attributed orders` | **Home**, beside the count it explains | Left the sidebar in 01B. The design does the same and uses the same title. |
| `/payroll` | `Payroll` | **Payments**, above the figures | Left the sidebar in 01B. In the finished design there is no payroll screen at all — approval happens inside one model's payment (05B/06A). Until then this is a link, not a rebuild. |
| `/payroll/:month/approve` | `PayrollApprove` | Payroll | `payroll.approve` |
| `/payroll/:month/reopen` | `PayrollReopen` | Payroll | `payroll.reopen`. **Retired workflow — UI52.** Removal is 05B/09, not this batch: it is a financial capability, and the CSV assigns it there. It is deliberately still routed and still admin-only until then. |
| `/affiliates/:id` | `AffiliateDetail` | Models, and from anywhere a model is named | The one shared profile (A03) |
| `/affiliates/:id/compensation` | `Compensation` (pay history) | The profile | `compensation.manage` |
| `/affiliates/:id/payments` | `AffiliatePayments` | The profile, Payments | |
| `/affiliates/:id/payout-destination` | `AffiliatePayout` | The profile | Full reveal is separately audited |
| `/payments/:month/:affiliateId` | `PaymentRecord` | Payments | `payments.record` |
| `/payments/:month/:affiliateId/reconcile` | `PaymentReconcile` | Payments | `payments.record` |
| `/glossary` | `Glossary` | The sidebar footer, and any defined term | Reference, not a workflow step |

Outside the layout entirely, with no session: `/sign-in`, `/accept-invitation`,
`/reset-password`, and first-run bootstrap when the platform has no account at
all.

---

## The model's half

Five tabs, from rule S03, with **You behind the avatar** rather than in the bar.

| Tab | Path | Screen |
|---|---|---|
| Home | `/` | `MyMonth` |
| Orders | `/orders` | `MyOrders` |
| Wardrobe | `/wardrobe` | **`NotBuiltYet`** — Phase 03C |
| Targets | `/targets` | **`NotBuiltYet`** — Phase 04B |
| Ranking | `/ranking` | **`NotBuiltYet`** — Phase 07B |

### Off the bar, still routed, still reachable

| Path | Screen | Reached from |
|---|---|---|
| `/you` | `MyDetails` | The avatar in the header |
| `/payments` | `MyPayments` | **You** — *"What you have been paid"*, first in the menu |
| `/year` | `MyYear` | **Home** — *"Your year so far"* |
| `/grow` | `MyGrow` | **Home** — *"Selling more"* |
| `/policy/:id` | `MyPolicy` | A figure's explanation |
| `/glossary` | `Glossary` | You |

The design folds the year's chart into Home (M01) and the code into the header
chip, which is where Grow's only real content already sits. **That folding is
Phase 07A.** Deleting a working screen to match a drawing before its replacement
exists is not a redesign, so both keep a link until 07A takes them.

A model holds no staff permission, so every maintainer route refuses her — and
she never sees one. `App.tsx` splits on **what the session is**, not on what it
may do: a sidebar full of things that refuse you teaches you the tool is broken.

---

## What "not built yet" means here

Three model tabs and one maintainer section have no backend. They are in the
navigation because it was approved as a whole and a tab bar that grows a slot
every few weeks moves everything under somebody's thumb each time.

They render `NotBuiltYet`, which is **deliberately not an empty state**. §S06
lists loading, empty, unavailable, stale and not-built as five different facts,
and the one thing they must never do is look alike — *"No products yet"* on a
screen with no backend is a lie with a plausible shape, and somebody would wait.
So it is drawn as a dashed notice, flagged in amber, and names the phase that
builds it. It fetches nothing, so it cannot report a state it has not checked.

---

## Keeping this true

`tests/test_reachability.py` fails when a served route has no way in from the
interface, and lists the deliberate exceptions by name with a reason. It is a
ratchet: the list only gets shorter, and adding to it is the moment somebody
asks whether a screen is missing. **The links added in 01B — Home → Orders,
Payments → Payroll, You → Payments, Home → Year and Grow — exist because moving
a section out of a nav without giving it a door is exactly the failure that test
was written after.**
