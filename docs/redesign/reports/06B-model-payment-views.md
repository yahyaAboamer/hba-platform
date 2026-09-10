# Batch report — Phase 06B, model payment views and destination changes

Date: 11 September 2026.

Branch and base/current commit: `phase06b/model-payment-views`, based on `main`
@ `3428af4` — 06A is merged and deployed to staging.

Requested scope: **06B only.** Model payment history and proof; the link from a
selected payment to the calculation behind it; frozen destination and statement
context; multiple and partial transfers, and truthful no-record old months.
Payout draft, cancel and password validation; the exact submitted link.

Delivered behaviour: **a receipt now survives her changing where she is paid,
and explains itself.** Most of this batch already existed and was verified
rather than rebuilt — saying which is which is most of the report.

---

## Review

### What was already right

The model's payments screen was in good shape. It is deliberately separate from
her earnings — *what I have earned* and *what has arrived* have different
answers for most of a month, and merging them is how somebody concludes they
were paid twice. Partial transfers, the settlement states, the write-off
reconciliation line, proof behind a press, the pre-platform months sentence
(ADR 0036) and 05C's credit wording were all correct and untouched.

**The payout change flow was already complete**, and better than the batch
prompt assumes. It re-authenticates with the same function that checks a
password at sign-in, so the two cannot disagree; it is a two-step draft so the
password is asked for at the point of commitment rather than before she knows
what she is committing to; a failure keeps the draft and clears only the
password, so the next attempt is deliberate rather than one click on a stale
form; and the response is masked even though the caller just typed the raw
value. Nothing there needed changing. **AC55 is verified, not implemented.**

### The two gaps, and they were the same gap

**A receipt borrowed the current destination.** §6.4.4 freezes a masked
destination on the transaction at the moment it was paid, and the payload has
carried it all along — **nothing rendered it.** The screen shows where her money
goes *today* at the top, so the day she changes her InstaPay address, every old
receipt silently reads as though it went to the new one. That is AC40's exact
scenario, and the data to answer it was already there.

**A transfer did not say why it came to that.** A receipt answers *what
arrived*; the month answers *why that much*. Without a link between them she has
to remember which month a transfer covered and go and find it in a picker at
the top of a different screen.

Both are now on the row. The link is named by month — *Why July 2026 came to
E£2,400.00* — rather than a generic *View calculation*, because **one transfer
can settle two months** and the generic label would be ambiguous about which one
it opens.

### A link that goes nowhere is worse than no link

The portal did not read a month from the address, so the link needed the other
half. It reads one now, with two deliberate limits:

**Only a month she can actually see.** The list comes from the server; anything
else in the query string is ignored rather than loaded, so a stale or mistyped
link opens her working month instead of an empty screen she cannot explain.

**Read once into state, not driving the picker.** Moving between months is the
most-used control in the portal, and putting a history entry behind every tap
would turn the phone's back button into a walk through every month she looked
at.

### What the owner should try

1. **Portal → Payments → any transfer.** It now says what it was sent to.
2. **Change where you are paid, then reopen an old transfer.** It still names
   the old destination. The panel at the top shows the new one. Those two being
   different is the point.
3. **Tap *Why July came to…*** on a transfer. It opens that month's earnings.
4. **A transfer that settled two months** shows one link each.

### Approved-design deviations and reason

**None.** Both additions are lines on a row the design already has.

### Confirmation needed before the next dependent decision

**None for this batch.**

---

## Engineering evidence

### Files changed

| File | Change |
|---|---|
| `frontend/src/screens/MyPayments.tsx` | The frozen destination on a receipt; a per-month link to the calculation; `PaymentRow` exported so it can be tested |
| `frontend/src/screens/MyPayments.css` | Two quiet lines, stacked so two months do not run together on a phone |
| `frontend/src/screens/AffiliatePortal.tsx` | Opens a month named in the address, when it is one she can see |
| `frontend/src/screens/__tests__/MyPayments.test.tsx` | **New.** 4 |

**No backend change, no migration, no API change.** Head unchanged at
`1c4b06a5f8d2`. Every field rendered was already in the payload; this batch is
what reads it.

### Authorisation, idempotency and money

**No new route, no new permission, nothing written.** The proof endpoint's
existing rule is untouched: a screenshot is served only to the model it belongs
to. No figure is computed in the browser — the amounts on a receipt are the
server's own strings.

**The destination shown is the masked snapshot**, never the raw value, in both
places it appears.

### Existing failures distinguished from regressions

**No regressions.** `test_portal_api.py` and `test_reachability.py` — the two
files a portal change could break — pass at 88. The frontend is 252, up 6 from
06A's 246: 4 new here and 2 from the accent guard picking up the new file.

### No real credentials or personal data in evidence

The test's InstaPay address is invented and follows the shape already used in
the repo's fixtures. No password appears anywhere in this batch; the flow that
checks one was read and left alone.

### Exact commands, actual results and environment

Windows, Git Bash, local PostgreSQL on 5433, migration head `1c4b06a5f8d2`.
One pytest process at a time, database named explicitly.

| Check | Actual result |
|---|---|
| `tests/test_portal_api.py` + `tests/test_reachability.py` | **88 passed in 109.73s**, exit 0 |
| `cd frontend && npm test` | **252 passed**, exit 0 |
| `cd frontend && npx tsc --noEmit` | exit 0 |
| `cd frontend && npm run build` | exit 0 |
| Full backend suite in one process | **Not run — see below** |

**The full suite was not run for this batch.** The machine has been at or below
0.5 GB free of 7.9 GB all session and killed three full-suite attempts
yesterday. This batch changes **no backend code at all**, so the two files a
portal change could plausibly break were run instead and named above. Somebody
with memory to spare should still run it once before this merges.

### Visual comparison — not performed

Automation cannot sign in. The two new lines on a receipt and the month link
have not been seen. This is now the seventh consecutive batch in that position.

---

## Continuation

### Remaining limitations

- **The month link goes to her earnings screen, not to a scrolled position on
  it.** Landing on the right month is the part that matters; deep-linking to
  the figure within it is not built.
- **A transfer settling two months shows two links**, which is correct and is
  also two lines on a phone. Fine at two; it would not be at six, and a
  transfer covering six months is not something HBA does.
- **`?month=` is read once on load.** Following a second link from within the
  portal without a reload would not move the picker. Every route that links
  this way is a full navigation today, so it does not arise.

### Decisions recorded

**None new.**

### STATUS.md and coverage rows updated

`docs/redesign/ACCEPTANCE_CHECKS.csv` — **AC40, AC41 and AC55 to Pass**, AC55
marked as verified rather than implemented. `docs/redesign/STATUS.md`.

### Exact next batch and prompt

**Phase 07A — performance screens.** `docs/redesign/prompts/07_PERFORMANCE.md`.

D03 (what a displayed code-use count means, and how Ranking treats ties) and
D08 (what counts as low weekly performance) are both open and both belong to
07. Read them before building either screen.

### Live deployment or data changes

**None in this batch.** 06A was merged and pushed to `main` earlier today at
the owner's instruction and is on staging; `production` remains at `9cbfcdb`.
