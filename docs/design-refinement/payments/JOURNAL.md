# Payments refinement journal

**Started:** 6 November 2026 · **Branch:** `claude/payments-refinement` from `main` at `f16af31`
**Scope:** the admin Payments desk: the list, a model's month, recording a
transfer, a transfer's page, settling an overpayment, and a correction.
**Evidence:** 40 before and 40 after captures plus 8 comparison sheets in
`D:/Desktop/HBA/HBA Engineering/evidence/payments-refinement-2026-11-06.zip`
(outside the repository, as `docs/cleanup/archive-index.md` asks; SHA-256
begins `51216322a1e3bcce`). The harness that made them is in `tools/`.
**Not in scope:** the model's own portal Payments screen (`portal/MyPayments.tsx`).
It has a different reader and its own approved design, and gets its own pass.
Also out: the payout-details editor (`AffiliatePayout.tsx`), a profile tool
that only links here.

This journal is the raw material for a later, reusable design-refinement
skill. It records what was actually done and seen, in order, including what
went wrong. Section 9 separates what generalises from what is HBA's business.

---

## 1. Skills used, and why

| Skill | Why it was chosen | What it actually contributed |
|---|---|---|
| `playwright-cli` | The only way to see every state as a payer would, at real widths, without moving money | The read-only state harness (§3); before and after captures; keyboard and touch checks |
| `design-taste-frontend` (app-screen rules) | Its rules for working screens: no ornament, quiet borders, a clear hierarchy, numbers that add up | The "figures that add up" test that exposed the list's summary (F-L1), and restraint: no icons, gradients or new colours were added |
| `web-design-guidelines` (Vercel) | A checklist for forms, focus, errors and copy | Field-level errors tied with `aria-describedby`, marking optional fields, specific button labels, no disabled control without a reason |
| `ui-ux-pro-max` | Project-mandated for meaningful UI work | Used as a cross-check only; the approved exports and the owner's rules come first |
| Apple HIG (from memory, via the `apple-design` skill's principles) | Touch targets and the order of content on a phone | 44pt minimum targets; "lead with the answer" on small screens (carried over from PR #153) |
| ECC code review (`ecc:code-reviewer`) | Project routing: any change to money-adjacent UI gets a review | Run after implementation (§7) |

Not used: brainstorming/planning agents (the audit gave a concrete enough list),
and the design-taste `draw.mjs` deal, which is for new pages, not refining an
existing design system.

## 2. Research: sources, and what was taken or left

| Source | Principle | Verdict |
|---|---|---|
| GOV.UK Design System, *Warning text* and *Inset text* | Keep warnings for real consequences, or they stop working; inset text marks supplementary content and should be used sparingly | **Adopted.** It became a three-tier note system: *warning* (money could go to the wrong place, or too much went), *inset* (a fact that changes how to read a figure), and *muted* (help). Before this pass the desk used amber for all three. |
| Shopify Polaris, *Banner* | Warning and critical banners must say how to fix the problem and carry the action | **Adopted.** Each warning now ends in its act, for example *Settle the difference* as a button instead of a link inside a sentence. |
| Polaris and Stripe status filters | Filters named for the state a merchant acts on; payout pages lead with the amount and status and keep a history | **Adopted in part.** Filters with no rows are hidden. Labels stay the export's, except where a label was ambiguous (F-L4). |
| NN/g on confirmation dialogs (cited second-hand: the primary pages did not come back from search) | Confirm only irreversible acts, name the consequence, and label the button with the act, not *Yes* | **Adopted** for approval: *Yes, approve* became *Approve EGP 6,400*. **Rejected** for recording a transfer, which already has its own page and an idempotent key: a second confirmation there would be the dialog fatigue NN/g warns about. |
| NN/g on progressive disclosure | Show what most people need; reveal the rest on intent | **Adopted carefully.** Hidden: zero-count filters, a correction's *recoverable* row when it equals the open difference, the empty receipt placeholder. **Never hidden:** an amount, what approving does, the irreversibility, or a changed destination. |
| Stripe, payouts *Timeline* and trace ID | A transfer's page is about the transfer: when it happened, its reference, where it went | **Adopted:** the page is titled *Transfer* and dated *Sent on*, not *Recorded*. |

The search results for NN/g and Stripe were secondary summaries, and they are
cited as such. No principle was adopted on the strength of one secondary
source alone; each also had to fix something seen in §4.

## 3. How the module was explored

1. **Mapped the routes** from `department.tsx`: six screens under
   `/affiliates/payments`.
2. **Read the code once**, for state logic only, after the first-time-user
   audit had already been done blind (PR #151 session).
3. **Checked real data.** Staging has two models and three months: Sara
   settled, Ali blocked, Sara's November an estimate, September paid outside
   the platform. That leaves part paid, ready to send, overpaid, terms
   missing, credited, a correction and a changed destination **unseen**.
4. **Built a state harness** (`tools/harness.tpl.js`; the method
   is in §9):
   - It serves a local build on the staging origin through `page.route`, so
     the owner's real session and the real API are used.
   - It adds six fictional models, each named *(test)*, to October 2026's
     list, with matching statement, history and correction responses.
   - It answers every non-GET request with a 418, so nothing can be written.
   - It forces a 500 on the list (`&fail=1`) and drives the actions
     (approve-confirm, partial amount, future date, submit-to-error,
     choosing an option).
   - It captures 20 states × 2 widths (390 and 1440) for any build.
5. **Mistake:** the first fixture used the pay type `commission_only`, which
   does not exist (`commission` does), so the *before* shots show a raw key.
   The approved total was also not summed. Both were fixed before the *after*
   run, and the *before* run was repeated so the two compare like with like.
6. The signed-in window had closed between sessions; the owner signed in
   again. Lesson: check `playwright-cli list` **and** a 200 from an
   authenticated GET before planning a capture run.

## 4. What was found (evidence: `before/<shot>-<width>.png`)

Severity: **H** = a payer could act wrongly or lose trust in a figure; **M** = slows them or
makes them hesitate; **L** = polish.

### The list (`list-*`)
- **F-L1 H** The three totals do not add up: *Total required* 50,526,
  *Recorded* 27,826, *Remaining* 16,800, and 50,526 − 27,826 = 22,700.
  Total required mixes the estimate (6,400) with approved money, and the
  overpayment sits outside both. A payer who checks the arithmetic stops
  trusting the page.
- **F-L2 M** The second line under an amount is set at full weight
  (*EGP 14,326.00 recorded*), so two figures of equal weight sit on one row.
  For a part-paid row the useful fact, what is **left**, is not shown.
- **F-L3 M** *Unavailable* gives no reason, and the model's own page shows
  an estimate with a blocker (Ali: EGP 1,440, no target recorded).
- **F-L4 M** *Approved* (pill and filter) is ambiguous: part-paid and fully
  paid months are approved too. The state means "approved, nothing sent".
- **F-L5 L** Six filter chips show even when most count 0.
- **F-L6 M** A load error is a red line with no way to retry.
- **F-L7 L** An empty search with a filter on offers no way back.

### A model's month (`detail-*`)
- **F-D1 H** The **changed destination** warning (the moment a redirected
  payout costs money, §6.4.5) is orange text in the card, styled like any
  other note.
- **F-D2 M** Nothing says what to do next. The status row carries a pill and
  terms; the instruction is split between the approval card's *Approval
  freezes this calculation* and the form.
- **F-D3 M** Before approval the Transfers card says *Nothing recorded yet ·
  EGP 0.00 remaining* and then *No transfer has been recorded yet*. That is
  the same fact twice, and *EGP 0 remaining* reads as "nothing owed".
- **F-D4 M** Overpaid: *The difference stays visible rather than being
  adjusted away* is an internal rule, not an instruction. The act is a link
  at the end of the sentence.
- **F-D5 M** Blocked (missing target) is drawn in red, the error tier,
  for missing information. That is somebody's turn, not a fault (§11.3).
- **F-D6 L** Every transfer says *No receipt attached* in amber, though the
  receipt is optional, and its link says *Receipt →*, so the row reads
  *Receipt → … No receipt attached*.
- **F-D7 L** The credit note (*covered by an earlier overpayment*) uses the
  warning tier for a fact.
- **F-D8 L** The confirm button says *Yes, approve*: correct, but not the act.

### Recording a transfer (`record-*`)
- **F-R1 H** Errors are not tied to their fields: a future date shows its
  message under the receipt box, about 300px below the date. There is no
  `aria-invalid` or `aria-describedby`.
- **F-R2 M** The *Why is it different?* box appears below the receipt
  drop, far from the amount it explains. It never says the difference, or
  what will still be left to send.
- **F-R3 M** *Destination used* is a disabled select that cannot change,
  holding a masked `InstaPay · …T01`, while the page before showed the full
  number.
- **F-R4 L** Optional fields (reference, receipt) are not marked optional.
- **F-R5 L** The changed-destination warning on this form says "before
  sending anything", but this form comes **after** sending.

### A transfer's page (`receipt-*`)
- **F-T1 M** It is titled *Receipt* and says *No receipt attached* twice,
  once in the list and once as a 130px empty dashed box.
- **F-T2 M** *Recorded 3 November* is the date the transfer was **sent**
  (`occurred_at`), not when it was recorded.
- **F-T3 L** *Open the month's payment* repeats the back button.

### Settling an overpayment (`reconcile-*`)
- **F-S1 M** A different header from every other Payments page (breadcrumb
  text and a 2-line h1). Back and Save both go to the list, not to the model's
  month.
- **F-S2 M** The month is a free-text `2026-11` input; the correction
  screen uses a month picker for the same act.
- **F-S3 L** *programme* (owner's rule: never), and Cancel comes before the
  primary act, the reverse of the record form.
- **F-S4 M** The same decision is worded differently on two screens:
  *Count it against a later month* / *Absorb it* here, *Carry to a later
  payment* / *HBA absorbs it* on the correction.

### A correction (`correction-*`)
- **F-C1 L** *Difference still open* and *Recoverable* print the same
  figure twice in amber when they are equal.
- **F-C2 M** One of two money decisions is preselected (*Carry*), while the
  overpayment screen deliberately preselects neither (its own comment says
  why).
- **F-C3 L** The empty month field renders as `--------- ----` in Chrome.

## 5. Decisions, with the alternatives considered

| Finding | Chosen | Considered and rejected, and why |
|---|---|---|
| F-L1 totals | Cards *Total to send* (sum of the approved rows' *To receive*), *Recorded*, *Left to send*; the estimate and any overpayment on one quiet line under them | (a) Keep *Total required* and add a footnote: the arithmetic would still fail. (b) A fourth card for the estimate: it puts a forecast at the same visual rank as debt, which F14 forbids. (c) Sub-lines under each card: the owner had removed those before ("a row read in one glance became three paragraphs"). (d) **First attempt, wrong:** *Approved* = `approved_piastres` (obligations). It still did not add up once credits existed, so it was replaced the same day. (e) **Second attempt, wrongly labelled:** *Approved to pay*. The code review showed the server's row figure includes an overpayment, so the card is what was sent plus what is left, not what was approved. Renamed *Total to send*. |
| F-L4 *Approved* | *Ready to send* | *Approved, unpaid* is accurate but reads as a fault. *To pay* is too close to *Partly paid*. |
| F-L5 zero filters | Hidden, except *All* and the selected one | Disabling them keeps a stable row, but still asks to be read. |
| F-D1 changed destination | Warning tier, bold, first in the card, *Confirm them with Mona before you send anything* | A modal on opening the page: blocks reading, and becomes the thing people click away. |
| F-D2 next step | One sentence under the status, keyed to the stage; none where a warning already says it | A stepper (Approve → Send → Record): three steps that never change cost space on every page and say less than one sentence. |
| F-D5 blocked | Amber warning titled *Can't be approved yet* | Red: §11.3 blocks on missing information, never on a fault. |
| F-D8 confirm | *Approve EGP 6,400.00* | A modal dialog: the in-place question already traps nothing and returns focus (PR #152). |
| F-R2 partial amount | A live hint (*EGP 4,800 will still be left to send*); *Why is it less than EGP 9,800?* directly under the amount | Making the reason optional: it is a safeguard (§14). |
| F-R3 destination | Read-only *Sent to* line with the full number | Keep the disabled select: a disabled control invites a click that does nothing. |
| F-T1/F-T2 | Title *Transfer*, *Sent on*, no empty box, no duplicate button | Keep *Receipt* (the export's word): it contradicts itself on every transfer without a screenshot. |
| F-S4 / F-C2 | One vocabulary (*Take it off a later payment* / *HBA absorbs it*), nothing preselected on either screen | Preselecting the common choice: it is a judgement about a person (the overpayment screen's own comment). |

**Kept on purpose:** the rounding note under the total. It is an inline
explanation, not a tooltip, because it answers the first question a payer
asks when checking sales × rate. It is help-tier text, so it costs no
attention unless read.

## 6. Before and after (sheets in the evidence ZIP)

| Sheet | Before | After |
|---|---|---|
| 01, 02 desk | *Total required* 51,026 (estimate included) − 27,826 ≠ 16,800; *Unavailable*; second line in full weight; six chips | 44,626 = 27,826 + 16,800; *Not worked out yet · No target recorded*; quiet footnotes with *EGP 7,000 left*; chips only where rows exist |
| 03 ready to send | No next step; the changed destination as orange text | *Send EGP 9,800.00 to Mona's InstaPay, then record the transfer here.*; a warning block |
| 04 overpaid | An internal rule (*stays visible rather than being adjusted away*) ending in a link | *EGP 500 more was sent than approved* plus the act as a button |
| 05 blocked / approve | A red box; *Yes, approve* | An amber *Can't be approved yet*; *Approve EGP 6,400.00*, *You can't undo this* |
| 06 record | The date error 300px away; the reason below the receipt; a disabled select | Each message under its field; the reason under the amount; *EGP 4,800 will still be left to send*; *Sent to* as text; *(optional)* labels |
| 07 transfer | *Receipt* … *No receipt attached* ×2; *Recorded* | *Transfer*, *Sent on*, *Receipt: Not attached* |
| 08 settle / correct | A different header; free-text month; *programme*; two vocabularies; a preselected choice | The same header as the other pages, a month picker, one vocabulary, nothing preselected, *recoverable* shown only when it differs |

## 7. Verification

- **Unit tests:** `npm test`, 62 files and 1,171 tests passed. The new
  `PaymentsRefinement.test.tsx` holds 12 of the findings in place. Existing
  tests changed only where a label changed (*Unavailable*, *Yes, approve*,
  *cannot be undone*).
- **Build:** `npm run build` passed. It is the real type gate.
- **Browser** (local build on the staging origin, real API, writes refused),
  in an iPhone 13 emulated session at 360, 390 and 430:
  - no sideways scroll on any of the 10 routes;
  - every Payments control at least 44px, except the shared month picker at
    38px (out of scope, other screens use it);
  - approve: Enter opens the question with focus on *Approve EGP 6,400.00*,
    and Cancel returns focus to *Approve this month*;
  - a future date sets `aria-invalid` and points `aria-describedby` at its
    message;
  - a refused write shows its message on the form;
  - 0 console errors.
- **Code review** (`ecc:code-reviewer`): it found no change to any request,
  endpoint or write-gating condition. It raised four points:
  - the card label (the medium one, see §5 F-L1(e));
  - an empty date was let through after `noValidate`; it is now blocked in
    the submit guard and on the button;
  - the empty-amount hint was wrong;
  - Cancel was live during a save on the overpayment form.
  All four were fixed and the tests re-run.
- **Not verified:** the change is not deployed, so nothing has been checked on
  the live staging build yet. The light theme was not captured, and nor were
  a real screen reader or a real phone.

## 8. Mistakes and lessons

1. **A fixture that disagrees with the server hides real bugs.**
   - The overpaid fixture used `required_piastres` = the obligation. The
     server uses sent + left.
   - That made the first summary design look correct. It took a reviewer
     reading `payments.py` to catch it.
   - Lesson: derive fixture fields from the server's own formula, and read
     the formula before designing any figure that sums them.
2. **A wrong pay-type key** (`commission_only`) put a raw identifier in the
   *before* shots. Lesson: build fixtures from the real enums
   (`PAY_TYPE`), not from memory.
3. **Shell heredocs broke on curly apostrophes** (`’`) in this Git Bash,
   three times (`unexpected EOF`), including while writing this section.
   Lesson: write multi-line text and edit scripts with the file tool; do not
   pipe them through a heredoc.
4. **Desktop scrollbars ate 15px of a "390px" capture.** It was fixed in the
   harness by hiding the scrollbar. Real touch checks still need a
   device-emulated session.
5. **The signed-in window closed between sessions.** Lesson: check an
   authenticated GET before any capture run.
6. **Labels are tested.** Three existing tests asserted copy. That is good:
   they forced each wording change to be deliberate and recorded.

## 9. Reusable method versus Payments-specific rules

**Reusable (candidate skill steps):**
1. Map routes, then list every state the code can render. Compare that list
   with what real data actually holds, and treat the gap as the to-do list.
2. Build a read-only state harness:
   - serve the local build on the real origin;
   - pass GETs through and fake the missing states with fixtures that follow
     the server's own formulas;
   - refuse every write;
   - drive the interactions;
   - capture at 390 and 1440.
   The same harness captures *before* and *after*, so they compare exactly.
3. Write findings with an ID, a severity and the screenshot that shows each.
   Decide only after the list is complete.
4. Run the **"figures add up" test** on every screen with more than one
   amount.
5. Sort every message into **warning / note / help** and give each tier one
   look. Then check that a warning names its act and carries it.
6. For each screen, write **the one sentence of what happens next**. If you
   cannot, the screen has no clear next act.
7. Name buttons with the act and its object (*Approve EGP 6,400*). Never use
   *Yes*.
8. Put errors under their field, with `aria-invalid` and `aria-describedby`.
   A disabled button says why, beside itself.
9. Hide what is empty (zero filters, empty placeholders, duplicate rows).
   Never hide an amount, a consequence or an irreversible act.
10. Run a phone sweep with a script: sideways scroll, targets under 44px,
    console errors.
11. Get an independent code review focused on "did any request or guard
    change", and fix before capturing the final *after*.
12. Record each divergence from an approved design as an ADR, with *what it
    costs*.

**HBA Payments-specific (do not generalise):**
- Approval is irreversible; later differences are corrections (05B/05C).
- An estimate is never a debt (F14).
- *Recording* never sends money (§14).
- A recent destination change is the high-risk moment (§6.4.5).
- Full destinations are shown only to payers (ADR 0042).
- Pay is rounded to whole pounds once (ADR 0004).
- Owner's words: never *programme*.
- The export wins unless an ADR is accepted.

## 10. Open items

- ~~ADR 0075 (and 0074) wait for the owner's acceptance.~~ Both accepted on 6 November and live (PRs #153, #154).
- ~~After a merge to `main`, re-run `tools/run.sh staging …` against the
  deployed build.~~ Checked live on staging and production on 6 November instead (§11).
- The model portal's Payments screen (`portal/MyPayments.tsx`) deserves its
  own pass with the same method.
- ~~The shared month picker is 38px tall on phones.~~ Fixed in round 2 (F2-9).
- New in round 2: the desk keeps the chosen month in page state, not in the
  address. After a reload, or *Back* from a model's month, it returns to the
  working month. Not changed here, because other screens share the pattern.
- The model profile (`AffiliateDetail.tsx`) still uses the old state words
  (*Approved*, *More sent than due*).
- Recapture the overpaid states once C: has space again (see §11, review).

---

## 11. Round 2 (same day): the owner's review of round 1

### Why it happened

The owner read round 1 and did not accept it as finished, and asked for:

- the financial meaning checked before anything else, starting with one
  contradiction: Hana Samir's overpaid month showed *EGP 8,500 approved* in
  its card and *an approved EGP 8,000* in its warning;
- the original goal revisited: the screens still felt text-heavy and dense,
  not merely badly worded;
- a final visual polish;
- checks beyond tests: touch, keyboard, both themes and the shared month
  picker.

### Financial review: what the server actually says

These are read from the code, not assumed:

- An approved statement's `total_piastres` is the snapshot's
  `approved_obligation_piastres` (`api/payroll.py`, the `statement` route,
  `payout_piastres=snapshot.approved_obligation_piastres`). A balance's
  `obligation_piastres` is the same snapshot field (`services/payments.py`).
  On the server, the card and the warning can never disagree.
- A row's `required_piastres` on an approved month is
  `paid + max(balance, 0)` (`api/payments.py`, `_render_balance`). On an
  overpaid month that is **what was sent**, not what is due.
- `totals.recorded_piastres` is every row's `paid` (overpayments included).
  `totals.still_owed_piastres` sums only positive balances.
  `totals.approved_piastres` sums obligations.

### Findings (round 2)

| ID | Severity | Where | What | Evidence |
|----|----------|-------|------|----------|
| F2-1 | High (financial) | Overpaid detail, desk, harness | **The 8,500 / 8,000 contradiction came from the harness, not the server.** The fixture built the statement total from `required_piastres` (8,500 for Hana), while the server builds it from the obligation (8,000). That repeats lesson 8.1, which round 1 had written down. The real defects next to it: (a) the desk's *To receive* column showed EGP 8,500 for Hana, because an overpaid row's `required_piastres` is what was sent. That is a true server figure under a false label. (b) The overpaid warning quoted the approved figure a second time, from a second field, which made it a second place for the two to disagree. | `after/detail-overpaid-390.png`, `after/list-1440.png` |
| F2-2 | High (financial) | Desk summary | **"Total to send" counted money already sent as still to send.** It was sent + left, which adds up, but the label reads as future money. On an overpaid month it also exceeded the approved pay. Round 1's "figures add up" test passed it; the meaning test did not. | `after/list-390.png` |
| F2-3 | Medium | Desk summary note | *More was sent than approved for Hana* gave no amount. | same |
| F2-4 | Medium (density) | Desk rows | A destination and a *Copy* button sat on every row, eight Copy buttons in all, though only two rows send anything. A fully paid row's *EGP 14,326.00 recorded* repeated its headline beside a *Fully paid* pill. | `after/list-390.png` |
| F2-5 | Low | Desk rows | *EGP 2,000.00 deducted* on a credit-covered month: the money was not taken away; an earlier credit covered it. | same |
| F2-6 | Medium (density) | A model's month | A ready-to-send month said EGP 9,800 four times: the next-step sentence, the card, *Nothing recorded yet · EGP 9,800 to send*, and *Approved … · EGP 9,800*. At approval, two explanations said the same thing (top sentence and Approval card). The pay type showed twice (*Commission* under the pill, *Commission at 10%* in the breakdown). Before approval, a whole Transfers card existed to say it could not be used. | `after/detail-send-390.png`, `after/detail-confirm-390.png` |
| F2-7 | Medium (risk) | A model's month | *Open InstaPay* showed before approval and on paid or overpaid months, which invites a transfer that should not happen. That is exactly how an overpayment like Hana's starts. | `after/detail-overpaid-390.png` |
| F2-8 | Low (polish) | Approve button | The amount inside the button kept the page's money colour, so the button read in two colours. | `after/detail-confirm-390.png` |
| F2-9 | Medium (a11y) | Shared month picker | 38px on phones (under 44), and 13.5px text makes iOS Safari zoom on tap. Round 1 left it as out of scope; the owner named it. | `tools/checks.js` output |
| F2-10 | Low (copy) | Record, settle | Explanations of how things work where a fact would do: *This records a transfer you have already made in your bank or InstaPay…*; *The transfer date is in the future. Record a transfer once it has been sent, with the date it was sent*; two paragraphs of *What happened*; option descriptions that restated their titles. | `after/record-partial-390.png`, `after/reconcile-chosen-390.png` |

### Decisions, with the alternatives considered

1. **The summary is two cash figures: *Left to send* (first) and
   *Recorded*.** Alternatives weighed:
   - *Keep three cards and rename the first* ("Month total", "Sent + left").
     Every name still implies one meaning (budget, or future money), and on
     an overpaid month the figure exceeds approved pay, so it needs a
     footnote. Rejected.
   - *Use the server's `approved_piastres` as the first card.* It is a
     different kind of figure. Credits and overpayments make approved −
     recorded ≠ left, so the round-1 distrust comes back. Rejected.
   - *Compute an "approved, still to send" client-side.* It breaks the rule
     that every figure is the server's. Rejected.

   Chosen: two figures with no implied arithmetic between them, both the
   server's totals unchanged. The estimate and any overpayment are one quiet
   line each, now with amounts.
2. **An overpaid row shows what she is due (the obligation), with *EGP 500.00
   too much sent* under it.** It is still a server figure, the one the
   column's label promises.
3. **The overpaid warning states only the excess and the decision.** The
   approved and sent figures live in the card above and the Transfers card,
   one source each.
4. **Copy and the destination line appear only on rows whose next act is a
   transfer** (approved, balance > 0). On a phone the destination line is
   hidden on other rows. On desktop the column keeps the text without Copy,
   because a table column with gaps reads as missing data.
5. **Each amount once on a model's month.** The Approval card says *Approved
   on 2 November 2026* without the amount. Transfers says *Nothing recorded
   yet.* The approval stage has no top sentence, because the Approval card
   holds the act and its consequence. The pay type is said only when it is
   missing. The empty pre-approval Transfers card is not drawn.
6. ***Open InstaPay* only while money is to be sent** (a `showLink` prop on
   the shared `DestinationDetails`). **Reversed by the owner** before the
   commit: the button is back on every state, as the export draws it. F2-7
   stays recorded as a finding the owner weighed and declined.
7. **The month picker becomes 44px / 16px on phones**, on every screen that
   uses it. The desktop sizes are the export's and are unchanged. A shared
   change, kept small and limited to phones on purpose.
8. **Copy cuts, with critical content kept.** Kept in full:
   - every consequence (*You can't undo this*, *Nothing is sent from here*,
     *Hana will see this*);
   - every warning;
   - every amount.

   Cut:
   - how-it-works sentences;
   - restatements of a field's own label;
   - repeated names.

   Rejected: collapsing the pay breakdown behind *Show how it's worked out*.
   At approval the breakdown is the thing being checked, and elsewhere it is
   three short lines. Hiding it saves little height and hides financial
   reasoning.

### Changes (files)

- `Payments.tsx`, `Payments.css`:
  - two cards;
  - `SummaryNotes` with amounts;
  - `amountShown`: obligation on overpaid rows;
  - `secondLine`: the over line first, *from credit*, no line on paid rows;
  - `sendsMoney()` gating Copy and the phone destination line;
  - a two-column phone summary.
- `PaymentDetail.tsx`, `PaymentDetail.css`:
  - next sentence only at the send stage;
  - terms only when missing;
  - *Rounded to the nearest whole pound.*;
  - warning without the second approved figure;
  - correction link *The figure changed after … was approved. Decide what
    happens →*;
  - approval date without the amount;
  - shorter approval copy;
  - no pre-approval Transfers card;
  - progress bar only once something is recorded;
  - one-colour approve button.
- `PaymentRecord.tsx`: shorter lead, warning, hints and date error.
- `PaymentReconcile.tsx`: one paragraph and short options; *Up to EGP X*;
  *Hana will see this.*
- `components/MonthPicker.css`: the phone block.
- Tests:
  - five new regression tests in `PaymentsRefinement.test.tsx`:
    - the two cash figures, exactly as the server sends them;
    - nothing sent counted as to send;
    - the overpaid row at its obligation;
    - Copy only on sending rows;
    - no repeat on a paid row;
  - two tightened: the overpaid warning names no second approved figure;
    there is no Transfers card before approval;
  - three existing assertions updated to the new copy.
- `tools/harness.tpl.js`:
  - the statement total built the server's way (`owes(r)`);
  - a light-theme option;
- `tools/run.sh`: a fifth `dark|light` argument.
- `tools/words.js`: new, counts words per screen.
- `tools/checks.js`: month picker and keyboard tab order added.

### Before and after, measured (`tools/words.js`, 390px, words in `main` / page height px)

| Screen | Round 1 | Round 2 |
|--------|---------|---------|
| Desk list | 223 / 1741 | 194 / 1517 |
| Month, awaiting approval | 110 / 1178 | 68 / 877 |
| Month, ready to send | 106 / 1236 | 92 / 1175 |
| Month, part paid | 119 / 1366 | 105 / 1322 |
| Month, overpaid | 122 / 1405 | 102 / 1279 |
| Month, covered by credit | 95 / 1077 | 79 / 956 |
| Record a transfer | 95 / 1066 | 76 / 1044 |
| Settle the difference | 136 / 981 | 96 / 887 |
| A transfer | 35 / 844 | 35 / 844 |
| A correction | 85 / 869 | 85 / 869 |

Both columns use the corrected fixture, so the round-1 figures are not the
ones in `after/`. Sheets `r2-01…r2-08` compare `after/` (round 1, captured
with the faulty fixture, so its overpaid card reads 8,500) against `final/`.

### Verification (round 2)

- `npm test`: 62 files, 1,176 tests passed; `npm run build` passed (after
  the review fixes below).
- **Phone sweep** (`checks.js`, 360 / 390 / 430, ten routes):
  - no sideways scroll anywhere;
  - no control under 44px: the month picker is now 44px; the record form's
    1px input is the hidden file input behind its 44px drop target;
  - 0 console errors.
- **Keyboard:**
  - Tab from the search box goes to the first row's name, its act, then the
    next row, each with a visible focus ring;
  - *Approve this month* opens the question with focus on *Approve EGP
    6,400.00*, and Cancel returns focus;
  - the month picker changes the month with the arrow keys alone;
  - a future date sets `aria-invalid` and points at its message.
- **Touch** (a separate iPhone 13 emulated session, `maxTouchPoints` 1, real
  `tap()` events):
  - a filter chip;
  - *Record payment* from a row;
  - Approve, then Cancel, with focus returned;
  - the month picker at 44px / 16px, choosing September by touch.

  The session was closed and its data deleted, and the copied sign-in state
  file was deleted immediately after loading.
- **Themes:** all 20 states captured in dark and light at 390 and 1440 (80
  captures). The light theme was set on `<html>` for the capture only;
  nothing was saved to the account.
- **Writes:** every non-GET still answered 418 by the harness, and the form
  said so.
- **Not tested:**
  - a real phone (emulation is not a device);
  - VoiceOver or TalkBack;
  - a live deploy (nothing is deployed);
  - the month picker on the seven other screens that share it (the change is
    CSS only and limited to phones, but those screens were not captured);
  - Safari's actual zoom behaviour (16px is the documented threshold; not
    observed on iOS).

### Mistakes and lessons (round 2)

1. **The same fixture mistake twice.** Lesson 8.1 said *derive fixture
   fields from the server's formula*. It was applied to the row and not to
   the statement, a second endpoint describing the same month.
   - **Lesson:** when two endpoints describe one fact, write the fixture for
     the fact once and derive both responses from it.
   - **And:** a contradiction seen in a screenshot is a harness suspect
     before it is a product bug. Read the server first.
2. **"Adds up" is necessary, not sufficient.** Round 1 fixed the arithmetic
   and kept a label whose tense was wrong. A figure needs two tests:
   - does it add up;
   - does its label stay true in every state, especially overpaid, credited
     and zero.
3. **Density is mostly repetition, not long sentences.** The biggest cuts
   came from saying an amount once, not from shorter wording. Count each
   amount's appearances per screen.
4. **A button can be a financial risk.** *Open InstaPay* on an overpaid
   month is a design that helps cause the problem the page warns about.
   Check every act against the state it appears in.
5. **"Out of scope" for a shared component needs the owner's say.** Round 1
   left the 38px picker alone because other screens use it. The owner
   counted it as part of the module. Next time, ask early, or make a small
   phone-only change and record it.
6. **A CSS override lost on specificity:**
   - `.payments__table td.payments__destination--idle` lost to
     `.table.payments__table td`, which sits later with equal weight;
   - the phone list fell apart (visible only in the screenshot; every test
     passed);
   - **Lesson:** after any CSS that hides grid children, look at the
     capture.

### Independent review (round 2) and what it changed

An ECC code reviewer read the diff and the server code. It found no critical
or high problems and approved. Two medium findings were real and are fixed:

- **"too much sent" was false after a partial settle or a credit landing.**
  - The figure is the open excess, `min(obligation − paid − credited +
    adjusted, 0)`, not what was sent. Example: sent 8,500 on 8,000, then 300
    absorbed. The row would say "EGP 200 too much sent" while the bank shows
    500 over.
  - It now reads *EGP 200.00 to settle* on the row and *… overpaid, still to
    settle* in the warning.
  - A regression test covers the partly settled case.
  - This is lesson 13 (the label test) failing on my own round-2 wording.
- **A reopened month with transfers against its earlier approval** said
  *Transfers can be recorded once the month is approved* above the transfers
  it listed. It now says *Recorded against an earlier approval. Approve the
  new figure before sending more.*
- **Low, taken:** `submit()` now also refuses a missing reason.
- **Low, not taken:** the record form's over-amount line is a hint, not a
  boxed warning. The reviewer found the text intact. Noted.
- **Low, out of scope:** `AffiliateDetail.tsx` still says *Approved* and *More
  sent than due* for these states. Added to open items.

These last fixes were verified by tests and the build (1,176 tests). They
were **not** recaptured in the browser: the C: drive, which holds the
capture scratch folder and the browser profile, reached 0 MB free during the
review. The round-2 captures (`final/`, sheets `r2-*`) therefore show the
earlier wording *too much sent* / *more was sent than approved*. They are in
`D:/Desktop/HBA/HBA Engineering/evidence/payments-refinement-round2-2026-11-06.zip`
(SHA-256 begins `8243704CD422B4B8`).

### After approval: the owner's last two edits

1. **Open InstaPay back everywhere.** The owner approved the round but asked
   for the button back. Decision 6 is reversed; lesson 4 (the act-in-state
   test) stands as a method, and its finding was the owner's to weigh.
2. **The pasted InstaPay message.** Production data showed most models'
   *payment link* holding InstaPay's share sentence around the link, so
   *Open InstaPay* opened nothing. The owner's rule: the model pastes
   whatever InstaPay gives, and the platform keeps only the link.
   - Server: `extract_instapay_link` runs first in
     `normalise_instapay_address`. That one function serves the application,
     the model's own edits and staff edits.
   - The lookbehind keeps an `ipn.eg` inside another site's link from being
     taken for one.
   - Saved records are not rewritten. The payment card's link and copied
     value pass through `instapay_link_or_none`, so models who already pasted
     text get a working button without a data migration.
   - The browser check (`instapayProblem`) extracts the same way, or the form
     would refuse the message before the server could clean it.

### Additions to the reusable method (for section 9)

13. **The label test**: for each figure, read its label aloud in every state
    the row can be in. Any state where it is false is a finding.
14. **The repetition count**: per screen, count how many times each amount
    and each fact appears. More than once needs a reason.
15. **The act-in-state test**: for every button, list the states it shows
    in, and ask whether pressing it there could cause harm.
16. **Fixtures from facts**: one fixture per business fact, with every
    endpoint's response derived from it.
17. **Measure density** with a word and height count per screen before and
    after, not by eye.
