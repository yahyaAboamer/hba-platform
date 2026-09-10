# Batch report — D03 and D08 implemented: ranking, uses, and weekly pace

Date: 11 September 2026.

Branch and base/current commit: `phase07/d03-d08-ranking-and-pace`, based on
`phase06b/model-payment-views` @ `ace8c36`.

**This is not 07A, and the batch name says so.** The owner answered D03 and D08
and asked for them to be built. Those two decisions land in **07B** — *sales-
ranked peers with permitted uses only*, and content progress — not in 07A,
which is *Model Home and Orders*. I said "next is 07A" when asking the
questions and that was wrong; the work is labelled for what it is rather than
filed under the batch I had named. **07A remains entirely unstarted**, and part
of 07B does too: the owner Home, top sellers and product analytics are not
here.

Requested scope: implement D03 (what a code use counts, and how Ranking orders
and breaks ties) and D08 (what counts as falling behind, week by week).

Delivered behaviour: the last `NotBuiltYet` in the portal is gone, and the
maintainer's Targets grid says who is off the pace.

---

## Review

### D03 — a use is a delivery outcome, not a financial one

> If it was delivered, we count it. If the status was failed delivery, it
> doesn't count. If it's anything in between, it's counted as pending and
> accounted in the uses until it's either delivered, then it permanently
> counts, or failed, so we remove it from the counts.

**The obvious field is the wrong one, and that is the whole risk in this
rule.** `commission_state` folds three different endings into a single `void`:
cancelled before shipping, fully refunded, and failed delivery. Reading it —
which is what a reasonable person reaches for — would silently drop
cancellations and refunds out of the count. A refund is a financial event; it
says nothing about whether her code was used and the parcel arrived.

So uses read `delivery_state` and exclude exactly one value. A delivered order
that was later refunded is still a use, and there is a test that says so by
name.

One SQL trap worth recording: `!= 'failed'` is neither true nor false against
`NULL`, so the obvious comparison would drop precisely the orders the rule says
to keep — an order Shopify has not resolved yet is *anything in between*. The
query uses `IS DISTINCT FROM`.

### D03 — the board

Ordered by **sales**. Uses break a tie. A tie on both shares a place and the
next one skips: the owner's own example, *two as first, then there is no
second, and we jump on the third*. `1, 1, 2` would say three models occupy two
places.

M02 is honoured strictly: **peer values are uses**, never another model's
sales, commission or salary — and nobody else is named. A rank, a use count,
and her own row is the only one carrying a name. A leaderboard that names
everybody turns twenty colleagues into a public table.

The screen states that places come from sales, because the column somebody
reads is not the column the order is made from. Without that sentence the board
looks broken to anyone who reads down it and finds a smaller number above a
bigger one — and M02 warns specifically against implying that matching
somebody's uses would match her rank.

### D08 — a quarter of the targets a week

Videos and stories **added together first, then divided**, rounded up. Both of
the owner's figures are asserted directly: five targets is two by week one;
sixteen is four a week in any mix.

Weeks anchor to **the day the month begins**, not Monday. August 2026 starts on
a Saturday, so its weeks run Saturday to Friday — and its fourth week ends on
the 28th with three days still to go. **Those days belong to week four**,
because the owner chose the final checkpoint to be the end of the month. A
model who finishes on the 31st was never behind.

### The two things it refuses to call "behind"

**Stale counts.** The platform keeps one cumulative pair of actuals a month and
no weekly history, so a figure last recorded in week one cannot answer a
question about week three — comparing them would report *how recently somebody
typed*, not how she is doing. It says "Nothing recorded in week 3" instead, and
still carries the last figure it knew so the screen is not blank beside the
words.

**No target.** There is nothing to be behind on.

Both are §11.3's distinction, which the platform enforces everywhere else:
*unrecorded* and *missed* are different facts and only one of them is about
her.

### HBA only, and what that costs

Asked directly, the owner chose to keep this internal. It is a column on the
maintainer's Targets grid and appears **nowhere in the portal in any wording**.

The consequence, recorded so it reads as a decision rather than an oversight:
**a model cannot catch up on a warning she never sees.** It is a prompt for the
month-end conversation, not a substitute for having it.

### What the owner should try

1. **Portal → Ranking.** Your place, your sales and uses, then the board. Only
   your own row is named.
2. **Two models level on sales and uses** both show the same place, and the
   next place skips.
3. **Targets (maintainer) → the new right-hand column.** On pace, behind, or
   nothing recorded this week.
4. **Record a model's counts, then look again next week without re-recording.**
   It says nothing was recorded rather than calling her behind.

### Approved-design deviations and reason

**One.** The board shows *Another model* rather than a name. M02 requires peer
values to be uses only; it does not say whether peers are named, and naming
them is a disclosure nobody consented to. Say the word and it is one line.

### Confirmation needed before the next dependent decision

**None.** D01, D02, D09 and D10 remain open and none of them blocks 07A.

---

## Engineering evidence

### Files changed

| File | Change |
|---|---|
| `app/services/performance.py` | **New.** Uses from `delivery_state`, one query for the whole board, and the shared-rank rule |
| `app/services/pace.py` | **New.** The weekly line, its anchoring, and the two refusals |
| `app/services/targets.py` | `record_actuals` accepts `recorded_at`, mirroring `verify` |
| `app/api/affiliate_self.py` | `GET /api/me/ranking/{month}` |
| `app/api/targets.py` | `pace` on each grid row |
| `frontend/src/screens/MyRanking.tsx` + `.css` | **New.** The board |
| `frontend/src/screens/Targets.tsx`, `.css` | The pace column |
| `frontend/src/screens/AffiliatePortal.tsx`, `components/AffiliateLayout.tsx` | Ranking routed; the last `NotBuiltYet` retired |
| `tests/test_performance.py` | **New.** 26 |
| `docs/redesign/decisions/D03-…`, `D08-…` | Both decisions, with the reasoning each overrode |

**No migration.** Head unchanged at `1c4b06a5f8d2`. Nothing is stored: both
answers are derived from rows that already exist.

### Why `record_actuals` grew an argument

`verify` has taken `verified_at` since Phase 5 for exactly this reason. **When**
a count was recorded became a fact with consequences in this batch — pace
compares it against the week — and a test that could not choose the date would
only ever exercise whichever week the suite happened to run in.

### Authorisation, idempotency and money

`GET /api/me/ranking/{month}` is behind `current_affiliate` and takes no
identifier. It returns **no other model's name and no other model's money**.
The pace column is on a route that already requires `targets.record`.

**Nothing is written and no money is computed.** §15 is untouched: a target
pays only on a guaranteed minimum, only at month end, and only when met *and*
verified. Weekly pace decides nothing.

### Existing failures distinguished from regressions

**No regressions.** `test_portal_api.py` 85, `test_reachability.py` 3,
`test_targets_api.py` 30 — the three files these changes could break. The
reachability guard passes because the new route is called by the new screen;
the last placeholder being retired removed no capability.

### No real credentials or personal data in evidence

Every fixture is synthetic. The board deliberately carries no name but the
reader's own.

### Exact commands, actual results and environment

Windows, Git Bash, local PostgreSQL on 5433, migration head `1c4b06a5f8d2`.
One pytest process at a time, database named explicitly.

| Check | Actual result |
|---|---|
| `tests/test_performance.py` | **26 passed**, exit 0 |
| `tests/test_portal_api.py` | **85 passed**, exit 0 |
| `tests/test_targets_api.py` | **30 passed**, exit 0 |
| `tests/test_reachability.py` | **3 passed**, exit 0 |
| `cd frontend && npm test` | **256 passed**, exit 0 |
| `cd frontend && npx tsc --noEmit` | exit 0 |
| `cd frontend && npm run build` | exit 0 |
| Full backend suite in one process | **Not run — the machine has been at ~0.5 GB free of 7.9 GB all session and killed three attempts on 10 September** |

### Visual comparison — not performed

Automation cannot sign in. The Ranking board and the pace column have not been
seen. Eighth consecutive batch in that position.

## Added after the first pass, 11 September

### Targets are fixed across a year

> The required targets for a single model is fixed along all year … a checkbox
> to select whether these targets are applied for all the months of the year or
> just this month. So in the future, if we wanted to edit a model's month not
> the entire year, we just don't click this checkbox.

A checkbox beside the save, **off by default and reset after every save** —
that is how it was described, and it rewrites twelve months at once, so it is a
deliberate act each time rather than a setting that stays armed. The button
says *Save the year* while it is ticked.

**January is included.** Asked whether "the whole year" meant this month onward
or every month including ones already gone, the owner chose every month.
The consequence was put to him in the same sentence and is asserted by a test
rather than left implicit: **raising a year re-decides months already counted**
— March achieved at four of four is not achieved once the year goes to eight,
and on a guaranteed minimum that is a floor applying or not applying.

**Two kinds of month are skipped, and only one of those is a choice.** An
agreed month is refused by `assert_month_recordable`, which is the whole of
05B — its snapshot froze the requirement it was agreed against. Refusing the
entire year instead would make the feature unusable by December, so it skips
and names them. A month from before the platform is skipped because ADR 0036
says it has an outcome and no counts, and giving it a requirement would invent
the evidence that record exists to say nobody kept.

The save reports what it reached and what it refused. *"12 rows saved"* would
be true and would hide both.

**Counts are never written across a year.** What she produced is a fact about
one month.

### A missing target is a gap, not a blank

> If no targets are recorded, or no required targets are set for this month,
> then those also are things to call for attention.

Both states existed and one of them rendered as **nothing at all** — a model
nobody had asked anything of showed an empty cell, which is exactly how it
stays unnoticed until payroll cannot close on her. The pace column now says
*Nothing asked for yet* and *Nothing recorded in week N*, so the two gaps that
block a month are visible in the same column as the pace itself.

---

## Continuation

### Remaining limitations

- **07A is unstarted**, and so is the rest of 07B: owner Home, top sellers,
  product analytics, and the code-uses figure on the model's own Home (M01).
  `uses_for` is built and ready for that Home; nothing calls it yet.
- **Ranking has no empty state worth the name.** A month where nobody has sold
  anything renders a board of zeroes, all sharing first place. Technically
  correct and not a sentence anybody wrote on purpose.
- **The board is not paged.** Twenty rows on a phone is a scroll; two hundred
  would be a problem, and HBA does not have two hundred models.
- **Pace reads the current cumulative count.** It cannot say she was behind in
  week one and caught up — only where she stands now. That is inherent to
  storing one pair a month, and 07B did not add weekly storage because the
  owner chose not to.

### Decisions recorded

**D03 and D08 both closed**, with records under `decisions/`. Open set is now
**D01, D02, D09, D10**.

### Exact next batch and prompt

**Phase 07A — Model Home and Orders.**
`docs/redesign/prompts/07_PERFORMANCE.md`, **07A only**.

It should put the code-uses figure on her Home (M01) using `uses_for`, which is
already built and tested. The rest of 07B — owner Home, top sellers, product
analytics — follows it.

### Live deployment or data changes

**None.** Not merged, not pushed, not deployed. `main` is at `3428af4` with
06A; 06B and this batch are both unmerged.
