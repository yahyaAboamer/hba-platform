# Phase 9 — The affiliate portal: what they have earned, and what they have been paid

**Spec:** `docs/specs/2026-08-22-hba-platform-v1-design.md` §11.1, §11.4, §14, §15,
§16, §19 (non-functional), §12.5
**ADRs:** 0014 (historical months), 0017 (proof is shown to the affiliate),
0025 (delivery is final), 0027 (numerals change face when a figure becomes an
obligation), 0029 (a late order is paid at its own month's rate)
**Depends on:** Phase 8 (they have an account) and Phase 6 (a figure can be agreed)
**Delivers:** the last build phase. After this, a model can answer every
question they have about their own money without asking anybody.

---

## What this phase is for

Phase 8 got them in. This is what they came for.

Everything the platform knows about their money already exists and has been
exercised for months on the maintainer's screens. **Nothing in this phase
computes anything new.** It reads what Phases 4 through 7 already decided and
puts it in front of the one person whose money it is.

That makes this phase easy to build and the hardest one to get right, because
the risk moves. An admin screen that reads awkwardly costs somebody five
minutes. **A model screen that reads wrongly costs the platform its
credibility with the people it exists to pay** — and it is the only screen in
the system whose reader will check the arithmetic by hand, from their own
records, and be certain they are right.

### The distinction this phase rests on

§11.1 again, and this is where it finally matters to the person it protects.

| | What it means to them |
|---|---|
| **A month still open** | A working number. It will move — orders are still arriving. |
| **A month agreed** | What they are owed. It cannot move. |

ADR 0027 already encodes exactly this and was built for the admin screens:
provisional figures in the prose face, agreed figures in mono. **It matters
more here.** The maintainer knows which months are closed; they do not, and
they are the one who will screenshot a number in the third week of the month and
ask why it changed.

Every figure in this phase carries that distinction or it does not ship.

---

## What they must never see

§19's non-functional line: *model-facing data never exposes customer PII.*

Checked rather than asserted: `order_index` and `attributed_order` carry **no
customer name, email, address, or phone** — §10.2's two-tier design keeps the
thin row deliberately thin, and full financial detail was never stored either.
The rule is therefore structural rather than a filter somebody has to remember,
and the tests in this phase assert it stays that way.

Also never theirs:

- **Anybody else's anything.** `current_affiliate` is the gate, and no route in
  this phase takes an affiliate id.
- **The house account.** Not a model, has no portal, and its figures are HBA's.
- **Internal blocker names.** `targets_achieved_but_not_verified` means nothing
  to them, and worse: it reads as *they* failed something when it means somebody
  at HBA has not confirmed their numbers yet. **Blockers that are HBA's own work
  are never phrased as their problem** — this is the copy decision the phase
  turns on.

---

## The three questions this phase answers

Stated as they would ask them, because that is the test of whether the screen
worked.

**"How much am I getting this month?"** — the figure, and whether it is
settled. If it is still moving, it says so.

**"Where does that number come from?"** — the orders behind it. They can count
them against their own record of what they sold.

**"Where is my money?"** — what has been paid, when, and the screenshot proving
it (§14, ADR 0017).

---

## The two things their arithmetic will disagree with

Both are correct behaviour and both look like errors from their side. Each needs
saying on the screen, not in a policy document they will not read.

**A late order was paid in a different month.** §11.4 and ADR 0029. They sold it
in August; August closed before it was delivered; it was paid in September at
August's rate. `attributed_order.settled_in_snapshot_id` exists precisely so
this can be answered — its own comment says *"the answer to a question a model
will otherwise ask every month"*. Phase 9 is where that is finally cashed in.

**A month before go-live shows sales and no commission.** ADR 0014. Those
months were settled outside the platform and their rates live in the old system
and somebody's memory. An empty commission figure with no explanation reads as
*"HBA did not pay me for March"*, which is the opposite of true.

---

## Task list

| # | Task | Delivers |
|---|---|---|
| 1 | Their month | The figure, framed by whether it is agreed |
| 2 | Their orders | What makes that figure up, PII-free by construction |
| 3 | Carry-forward, explained | Why August's order is in September's payment |
| 4 | Their targets | What was asked, what was recorded, what it changes |
| 5 | Their payments | What has arrived, and when |
| 6 | Their receipts | The proof screenshot, served only to them |
| 7 | The portal shell | Month navigation, phone-first |

**Batches:**

- **Batch A — tasks 1, 2, 3, 7.** The money and what makes it up. The whole
  point of the phase, and the part where getting the framing wrong is
  expensive.
- **Batch B — tasks 4, 5, 6.** Targets, payments, and proof.

---

## Task 1: Their month

**Files:** `app/api/affiliate_self.py`; `frontend/src/screens/MyMonth.tsx`; tests

`GET /api/me/earnings/{month}`, gated on ownership.

The calculation is `calculate_month`, unchanged — the same function the payroll
screen has used since Phase 4. **Nothing recomputes for them**, because a second
implementation of what they are owed is a second answer waiting to disagree with
the first.

What changes is the framing:

- **Agreed months read from the snapshot**, never the recalculation. The trap
  Phase 6's payroll screen already fell into and was fixed for: `calculate_month`
  keeps moving after approval, so a settled month must show
  `approved_obligation_piastres` or it will quietly contradict what they were
  paid.
- **Open months are marked as still moving**, in words as well as in the
  typeface.
- **Blockers are translated, and only the ones that are theirs.** *"Nobody has
  recorded what you published yet"* is theirs to chase. *"Your targets are waiting
  to be confirmed"* is not — it is HBA's, and the wording says so.

## Task 2: Their orders

**Files:** `app/api/affiliate_self.py`; `frontend/src/screens/MyOrders.tsx`; tests

The orders behind the figure: order number, the date, what it was worth to them,
and whether it counts yet.

**Three states, in their words.** `earned` is *counted*, `pending` is *still on
its way*, `void` is *did not arrive*. The last one matters most: §9.4 pays on
delivery, and a model who sees an order vanish without explanation assumes a
mistake. It stays visible and says what happened.

**Pending orders are shown, never hidden.** Already the rule the engine
follows, for the reason `commission_state.py` gives: hiding an undelivered
order makes their month look smaller than it is and produces exactly the question
this platform exists to stop their having to ask.

A test asserts the response carries no field that could hold a customer's name
or address — structural today, and the test is what keeps it structural.

## Task 3: Carry-forward, explained

**Files:** `app/api/affiliate_self.py`; their month and orders screens; tests

An order they sold in August, delivered in September, paid in September at
August's rate.

Two sides, and they need both or their arithmetic will not close:

- On **August**, the order shows as sold there and says it was paid later.
- On **September**, it shows as carried in, saying which month it came from and
  which rate applied.

`settled_in_snapshot_id` resolves to the month that paid it, exactly as the
Orders screen already does for the maintainer.

## Task 4: Their targets

**Files:** `app/api/affiliate_self.py`; `frontend/src/screens/MyTargets.tsx`; tests

What was asked of them, what was recorded, and — the part that matters —
**whether it changes their pay at all.**

§15: targets are informational for commission and fixed-plus-commission, and
decide money only on a guaranteed minimum. The admin grid already draws that
line and this screen draws the same one. A model on commission seeing a target
they missed should not think they have lost money, because they have not.

**Nothing here is editable.** §6.5. They see what was recorded; recording is
Sara's.

## Task 5: Their payments

**Files:** `app/api/affiliate_self.py`; `frontend/src/screens/MyPayments.tsx`; tests

`payments_for` and `adjustments_for`, both of which exist.

Every payment: what arrived, when, and which month it settled. §11.5 requires
adjustments to be visible to them — *a credit they cannot see is a credit they
cannot check* — so a credit carried into a later month and a write-off both
appear, with the reason that was written at the time.

**Their own payout destination is masked, as it already is.** They supplied it; it
tells them nothing they do not know, and a screen printing a full account
number is one worth photographing over their shoulder.

## Task 6: Their receipts

**Files:** `app/api/affiliate_self.py`; tests

§14 and ADR 0017: the confirmation screenshot is shown to them, because visible
proof removes an entire category of *"did you send it?"* messages. The business
accepted the recorded risk that a transfer screenshot may expose HBA's own
banking details to ~20 people; the mitigations already applied are EXIF
stripping, compression, a size cap, and serving only to the owner.

`readable_by` already enforces the last of those and its docstring already
names this route: *"the affiliate's own route arrives in Phase 9 and calls the
same `readable_by`, so the two cannot drift apart on the rule."* This phase
calls it, and does not reimplement it.

## Task 7: The portal shell

**Files:** `frontend/src/components/AffiliateLayout.tsx`; month navigation

§12.5: **the affiliate portal is phone-first.** Bottom tab bar rather than the
maintainer's sidebar.

Month navigation is theirs, not the maintainer's `MonthPicker` — that component
marks months historical, approved and future for somebody deciding whether to
run payroll. They need to move between their own months, and months before they
joined should not be offered at all.

---

## What this phase deliberately does not do

**No emails or receipts by mail.** §16 routes those through a
`notification_outbox` that does not exist. Phase 10.

**No policy viewer.** §16 wants versioned, plain-language rules with an ⓘ
control, so a model viewing July sees July's rules. Phase 10 — and this phase
is what makes it worth having, because every screen here raises a question the
policy text is supposed to answer.

**No FAQ or dictionary.** Raised earlier by the business, for models *and* for
the team: *carried forward*, *pending*, *void*, *guaranteed minimum* are all
terms this phase puts in front of people. Phase 10, §16, and this phase is why
it is needed rather than merely nice.

**No CSV export.** §19 mentions formula neutralisation on export; nothing in
V1B exports anything.

---

## What "done" looks like

They sign in on their phone. This month says what they have sold, what it is worth
so far, and that it is still moving because orders are still arriving. Last
month says what they were paid, in a face that tells them it is settled, with the
orders behind it and a screenshot of the transfer.

One of those orders says it was sold in the month before and paid in this one,
at that month's rate. They count the orders against their own list, and the
number matches.

They do not have to ask anybody anything.
