# Decision — D03

**Owner's question:** Does a displayed code-use count every placed attributed
order, including failures, or only counted orders? Which period and tie
treatment should Ranking use?

**Owner's answer**, 11 September 2026.

---

## What a use is

> We check the status of the delivery from Shopify. If it was delivered, we
> count it. If the status was failed delivery, it doesn't count. If it's
> anything in between, it's counted as pending and accounted in the uses until
> it's either delivered, then it permanently counts, or failed, so we remove it
> from the counts.

**A use is a delivery outcome, not a financial one.** The only status that
removes an order from the count is a failed delivery. Everything else counts —
delivered permanently, and anything still in motion provisionally.

### The mistake this record exists to prevent

The platform's `commission_state` folds **three** different endings into one
`void`: cancelled before shipping, fully refunded, and failed delivery. It is
the obvious field to reach for and it is the **wrong** one. Reading it would
silently drop cancellations and refunds out of the use count, which is not what
was asked for — a refund is a financial event and says nothing about whether
her code was used and the parcel arrived.

Uses read `delivery_state` and exclude only `FAILED`. An order whose delivery
status Shopify has not given us yet is "anything in between", so it counts
until it resolves.

## How Ranking uses it

> Ranking is based on sales, but what is shown on the front end for the models
> are their number of uses. So if there is a tie, then the one who have more
> uses should win. And if those two conditions, the sales and the uses match,
> then we rank both models with the same rank. So we will have, for example,
> two as first, then there is no second, and we jump on the third.

- **Order by sales.** Uses are the tie-break, not the ordering.
- **Tie on sales → more uses wins.**
- **Tie on both → the same rank**, and the next rank skips the places used up:
  `1, 1, 3`, never `1, 1, 2`.
- **Peer values shown are uses** (M02), never another model's sales,
  commission or salary.

M02 also warns against implying that matching another model's uses guarantees
matching her rank — which is exactly what the tie-break makes true only
sometimes, and why the screen explains that the order is by sales.

## What it does not settle

**The period.** Taken as the month being viewed, consistent with every other
screen in the portal. Nothing here changes if that is wrong; it is one filter.

**Her own card.** Uses count pending deliveries and her sales figure does not,
so the two move independently — an order in transit raises her uses and not her
sales. That is correct and it needs saying on the card rather than leaving her
to notice it.
