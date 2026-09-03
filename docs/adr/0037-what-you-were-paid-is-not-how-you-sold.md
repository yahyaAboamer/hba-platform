# 0037 — What a model was paid and how their sales performed are two numbers

**Status:** accepted
**Date:** 2026-09-04
**Implements:** spec §9.5, §11.1
**Related:** [0027](0027-numerals-change-face-when-a-figure-becomes-an-obligation.md), [0036](0036-pre-go-live-months-are-ordinary-months.md)

## The situation

The Year screen had one line chart labelled *"What you earned"*. On a
commission arrangement that label is exact — what they earned and what their
sales produced are the same number.

On a **guaranteed minimum** they are not, and the gap is the point of the
arrangement. A model with a E£5,000 floor whose code sold E£12,000 that month
earns E£1,200 in commission and is paid **E£5,000**, provided she met her
targets. The business put it plainly:

> *"This does not tell the models what was their performance on sales. It tells
> them their performance on HBA tasks but not on sales, not how many people
> actually used their code."*

A single figure cannot answer both questions. Print the pay and her sales
performance is invisible; print the commission and the screen appears to show
her less money than she received.

The same split exists, less sharply, on **salary plus commission**: the salary
is the same every month and says nothing about how she sold.

## Decision

**The Year screen answers both questions, and never lets one stand in for the
other.**

- **The headline is what she was paid.** Total for the year, with a second line
  splitting it: *"E£12,400 of it from your sales."* On a commission
  arrangement the two figures are equal and the second line is absent, so
  nothing changes for most models.
- **The line chart is her sales, always.** It plots commission and nothing
  else — no salary, no guarantee — and is renamed from *"What you earned"* to
  **"What your sales earned"**, because on two of the three arrangements the
  old label was false. This is the same measure for every model, which is what
  makes it a performance chart rather than a payslip.
- **The bar chart is unchanged:** the number of orders that counted, by month.
- **A month where the guarantee applied is ringed on the line.** Its sales
  point is genuinely low, and without a mark a good month reads as a bad one.
  The ring says the month was topped up; the caption says it once.
- **Selecting a month shows both**: the figure she was paid, large, and beneath
  it what her sales earned and why the two differ.
- **The all-time tiles follow the arrangement.** Commission: best month and
  orders counted. Salary: best month and salary for the year. Guarantee: best
  month and *"your guarantee applied in 4 of 6 months"*.

**That count is over the months she was actually on a guarantee**, not over
every month she has. The guarantee arrangement began mid-2026; counting January
against it would measure her against a rule that did not exist, and would make
a model who was on it for four months and met every target look like she met
four out of nine.

## Consequences

The word *earned* leaves the interface. It was doing two jobs, and the screens
now say either *paid* or *what your sales earned*.

Every all-time figure becomes arrangement-aware, so the Year screen has three
shapes rather than one. That is more code than a single layout and it is the
cost of not lying to two thirds of the models.

The ring is a fifth thing on a chart that already carries points, hollow
points, ticks and a baseline. It is drawn only where a guarantee actually
applied, which on most models is never.

## Alternatives considered

**Two lines on one chart — paid and sales.** Rejected by the business, who
asked for salary and guarantee to sit outside the graph entirely. It also
doubles the ink on a phone chart to answer a question most models do not have.

**A third tab, "What you were paid".** Rejected: three tabs above a chart on a
390px screen, and the answer already lives in the headline and the reading
panel where it is read for free.

**Leave the label and explain it in the glossary.** Rejected. A label that
needs a glossary to stop being false is a false label.
