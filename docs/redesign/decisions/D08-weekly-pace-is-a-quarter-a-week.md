# Decision — D08

**Owner's question:** What qualifies as low weekly content performance, if an
automatic low-performance label is wanted?

**Owner's answer**, 11 September 2026. One is wanted, and this is the rule.

---

## The rule

**A quarter of the month's targets a week, counted together.**

> We will not divide only the number of stories by four, but actually we will
> first add the number of stories and videos and then divide them by four and
> count the total.

Videos and stories are **added first, then divided**. Sixteen targets — twelve
stories and four videos — is four a week, in any mix. Two videos and two
stories is four. Three videos and one story is four.

**Rounded up.** Five targets is two by the end of week one, not one and a
quarter. The threshold for week *w* is `ceil(total × w / 4)`.

## Where a week starts

> A weak weekly performance is calculated by checking the number of targets by
> the end of each week … at the day of the starting month. So if the month
> started on Thursday, then that's the start of the week, and the week ends on
> Wednesday.

**Weeks are anchored to the day the month begins**, not to Monday and not to
the ISO calendar. A month starting on a Thursday runs Thursday to Wednesday.
Cairo days, like every other date in the platform (ADR 0005) — the browser's
clock is not authoritative about anything.

## The fourth check is the end of the month

A month is not four weeks. August 2026 begins on a Saturday, so its fourth week
ends on Friday 28 August with three days still to go.

**Checkpoints are weeks one, two and three, and then the end of the month.**
Asked directly, the owner chose this: she gets every day the month actually
has, and the final check lands where met-or-missed is already decided rather
than three days early. A model who finishes on the 31st was never behind.

## Stale counts are not a failing model

The platform stores **one cumulative pair of actuals per month** and no weekly
history. So if her counts were last recorded in week one and it is now week
three, comparing what is on file against a week-three threshold does not
measure her at all — **it measures how recently somebody typed.**

> "Nothing recorded this week" rather than "behind".

If the actuals have not been recorded since the current week began, the answer
is that nothing has been recorded, not that she is behind. This is the same
distinction the platform enforces everywhere else and for the same reason
(§11.3): *unrecorded* and *missed* are different facts, and only one of them is
about her.

A month with **no target set** is likewise not a model who is behind. There is
nothing to be behind on.

## Who sees it

**HBA only.** Asked directly, and the owner chose the flag to stay internal —
it does not appear on the model's own screens in any wording.

So the label is for the month-end conversation, and nothing on her side changes.
The consequence to accept knowingly: **a model cannot catch up on a warning she
never sees.** That is the owner's call and it is recorded here so it reads as a
decision rather than an omission.

## What it does not touch

**Pay.** §15 is unchanged: a target decides money only on a guaranteed minimum,
only at month end, and only when met *and* verified. Weekly pace is a
management signal and decides nothing.
