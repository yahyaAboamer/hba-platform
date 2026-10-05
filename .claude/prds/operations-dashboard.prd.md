# Operations Dashboard

*Requirements written 3 October 2026 with the owner. Built on the same platform as the affiliate dashboard.*

## Problem

HBA's order flow lives in three systems that nobody sees together:

- **Shopify tags** record where each order is in confirmation: confirmed, no answer, WhatsApp sent, failed to reach Bosta, and so on.
- **Bosta** knows whether a parcel was printed, picked up or delivered, or is waiting on HBA.
- **E-stebdal** holds return and exchange requests that are waiting for review.

To know what needs doing, someone has to open all three and filter each one by hand. Stuck orders are found late or not at all. For example, an order that never reached Bosta, or a parcel waiting on HBA's action, stays stuck until a customer chases it. The cost is late deliveries, failed deliveries and returns, and a team that finds problems from complaints instead of by looking.

## Evidence

- **Live store, 3 Oct 2026** (read-only check through the platform's own Shopify connection). There are 29 open, unfulfilled orders. Of these:
  - 5 confirmed orders failed to sync to Bosta.
  - 7 are no-answer orders waiting for a second try.
  - 5 compression orders have no call confirmation.
  - 1 is tagged cancelled by the team but is still open in Shopify.

  None of this is visible anywhere today without filtering Shopify by hand.
- **Bosta, 3 Oct 2026** (milestone 1 check):
  - 29 orders had waited more than 2 working days for Bosta to pick them up, 26 of them 5 working days or more.
  - 9 parcels collected more than 3 working days earlier were still not delivered.
  - 2 orders were waiting on HBA's action.
- **28 Sep 2026:** 211 orders had been shipped and never confirmed delivered, some since February (ADR 0051). Orders fall between the systems unnoticed.
- **The need is not new.** The v1 design lists "operational monitoring across Shopify / Bosta / E-stebdal" as Amr's request and defers it to V2. Amr's `hba-operations-hub` (Aug 2026) prototyped it on made-up sample data and was never connected to Bosta or E-stebdal.
- **How many orders actually arrive late, and what that costs:** *Assumption.* This needs a baseline week of the dashboard's own numbers and the operations manager's account to confirm.

## Users

- **Primary: the operations manager.** There is exactly one, and the operations staff do not use the dashboard. He runs the daily order flow: confirmation calls, WhatsApp follow-ups, handing orders to Bosta, printing, pickups, delivery problems, and reviewing returns and exchanges. Opens the dashboard at the start of the day and through it, to see which orders need action now.
- **Also: the admin.** Sees the Operations dashboard as well as the affiliate dashboard, and switches between them.
- **Not for:**
  - The affiliate manager, content manager and models/ambassadors. None of them sees Operations.
  - Customers.

  The operations manager in turn sees nothing of the affiliate side.

## Decisions already made (do not reopen)

| Decision | Source |
|---|---|
| Same platform, same sign-in, same database. Not a separate app. | Owner, 1–3 Oct |
| New role, **operations manager**. They sign in and land on Operations. They see nothing of models, payroll, targets, payments or codes. | Owner |
| The admin sees both dashboards. Only the admin can give someone the operations-manager role. | Owner; existing rule "you can only give access you hold yourself" |
| Exactly one operations manager at a time. He cannot invite anyone, and the operations staff never use this dashboard. | Owner, 3 Oct |
| The affiliate manager, content manager and models see nothing of Operations. | Owner |
| Orders on Operations never show which model's code was used, or any commission. | Owner ("nothing is linked") |
| Operations only reads. Bosta's data never feeds commission or pay: delivery for money still comes from Shopify. ADR 0023 stands, and a new ADR records Bosta as an operations-only source. | Recommended 1 Oct; needs that ADR |
| Every card opens the list of orders behind its number. | Owner, 3 Oct |
| An order tagged Confirmed leaves the No answer, WhatsApp and No WhatsApp cards. | Owner, 3 Oct |
| Orders tagged `Cancelled ❌` that are still open in Shopify get their own card and leave every other card. | Owner, 3 Oct |
| The Bosta tab counts every Bosta order type: deliveries, exchanges and customer return pickups. | Owner, 3 Oct |
| Day limits count **working days** in Cairo time: Saturday to Thursday. Only Friday is off (Bosta picks up on Saturdays), and no holiday list is kept. | Owner, 3 Oct |
| The success rate is taken from Bosta as Bosta reports it, for a date range the user chooses. Successful and unsuccessful follow Bosta's dashboard. That dashboard counts a failed delivery that came back as **unsuccessful**, even though Bosta's status table calls "Returned to business" successful. | Owner, 3 Oct; checked against Bosta's dashboard for September |
| Every number on the dashboard is at most **10 minutes** old, for every order, whether or not a webhook reported the change. | Owner, 3 Oct |
| "Picked up per day" shows the last 7 days. | Owner, 3 Oct |
| "Shipped" (B6) starts on the day Bosta picked the parcel up from HBA. | Owner, 3 Oct |
| Lists carry no customer name or phone. Each order links to Shopify, Bosta or E-stebdal instead. | Owner, 3 Oct |
| Tag spellings found only on old orders are ignored, because the Shopify tab reads only open, unshipped orders. Both current spellings of Confirmed count: `Confirmed ✅` and `Confirmed✅` (without the space, still written on new orders). | Owner, 3 Oct; checked against the live store |

## What each tab shows

### Shopify tab

**Which orders count.** Every order that is still open in Shopify: not cancelled, not archived, and not fully shipped (unfulfilled or partly fulfilled). Shopify's own "unfulfilled" filter also returns about 3,500 old cancelled orders; those never count.

| # | Card | An order counts when it is… | 3 Oct |
|---|---|---|---|
| S1 | Confirmed | tagged `Confirmed ✅` | 17 |
| S2 | No answer | tagged `No answer`, not `no answer( 2 times )`, not Confirmed | 7 |
| S3 | No answer, WhatsApp not sent | tagged `No answer`, not `WA Sent 📤`, not `No WhatsApp 📵`, not Confirmed | 0 |
| S4 | No WhatsApp | tagged `No WhatsApp 📵`, not Confirmed | 1 |
| S5 | Bosta sync failed | tagged `bosta_sync_failed` | 5 |
| S6 | Compression, not call-confirmed | tagged `compression`, not `Call Confirmed📞` | 5 |
| S7 | Cancel in Shopify | tagged `Cancelled ❌` (the team cancelled it but Shopify still has it open) | 1 |

- An order tagged `Cancelled ❌` counts only on S7.
- An order can sit on more than one card, for example S1 and S5.
- `Confirmed ✅` and `Confirmed✅` both count as Confirmed. Spellings found only on old orders are ignored (Appendix A).
- Each card's list shows the order number, how long ago it was placed, its tags, and a link to the order in Shopify.

### Bosta tab

**Which orders count.** Every order HBA has on Bosta, of every type.

| # | Card | Counts |
|---|---|---|
| B1 | New, not shipped | Orders still new on Bosta (pickup requested, not picked up) more than **2 working days** after they were created on Bosta. |
| B2 | Not printed | Orders not yet picked up that have no airway-bill print date on Bosta. |
| B3 | Picked up per day | One row for each of the last 7 days: how many orders Bosta collected from HBA that day, by the collection time Bosta records on each order. Opening a day lists its orders. |
| B4 | Success rate | Bosta's successful-vs-unsuccessful rate for a chosen range: today, a chosen day, last 7 days, last 30 days, or a custom from–to. Bosta's API has no figure for a range, so the platform works it out the way Bosta's dashboard does:<br>• **Range:** orders created on Bosta in the range.<br>• **Successful:** delivered, plus finished exchanges and finished customer return pickups.<br>• **Unsuccessful:** failed deliveries that came back to HBA.<br>• **Rate:** successful ÷ (successful + unsuccessful). |
| B5 | Awaiting your action | Orders Bosta has flagged as waiting for HBA's action. This is the same flag behind Bosta's own "Awaiting your action" count, not the "Awaiting your action" status. |
| B6 | Shipped, not delivered | Orders Bosta collected from HBA more than **3 working days** ago that are still not delivered, returned, cancelled or otherwise finished. |

Each list shows the tracking number, the Shopify order number where Bosta has it, the Bosta status, the date that matters for the card (created or picked up), and a link to the order on Bosta.

### E-stebdal tab

| # | Card | Counts |
|---|---|---|
| E1 | Needs review | Return and exchange requests whose status on E-stebdal is "Needs Review". |

The list shows the return number, the order number, the date requested, and a link to E-stebdal.

### On every tab

- Each card shows when its number was last updated.
- If a source can't be reached, the card says so. A failure never shows as 0, and an old number is never shown as if it were current.
- Lists carry no customer details. Names and phone numbers are one click away in the source system.

## Hypothesis

We believe **one Operations dashboard that shows, for Shopify, Bosta and E-stebdal, how many orders need action and which ones** will **let stuck orders be caught the same day instead of when a customer complains** for **HBA's operations manager**.

We'll know we're right when:
- the Bosta "new, not shipped" and "shipped, not delivered" counts fall below their baseline week (target to be set with the owner after that week), and
- the operations manager no longer opens Shopify filters, Bosta and E-stebdal to decide what to do first (the owner confirms after two weeks of use).

## Success Metrics

| Metric | Target | How measured |
|---|---|---|
| Card accuracy | Every card equals the same filter in its source system | At acceptance, check each card side by side against Shopify admin, Bosta's dashboard and E-stebdal's dashboard |
| Freshness | No number older than 10 minutes, for every order (owner, 3 Oct) | The "last updated" time against the clock |
| B1 and B6 counts | Below the baseline week; target TBD after it | The cards, read daily |
| Needs Review backlog (E1) | TBD — needs validation with the operations manager | The card, read daily |
| One place instead of three | The operations manager starts the day from the dashboard | Operations manager and owner feedback after two weeks |

## Scope

**MVP**
- The three tabs and 14 cards above, each with its list of orders.
- The operations-manager role and where it lands after sign-in.
- The admin switching between the two dashboards.
- The admin entering the Bosta and E-stebdal API keys.

**Out of scope**
- **Acting from the dashboard** (changing tags, cancelling in Shopify, printing, booking pickups, approving returns). The dashboard links out to do these. The platform's Shopify access stays read-only (ADR 0015), and writing to any system is new risk.
- **Assigning orders to people, notes, "handled" marks.** Later, once the cards are trusted.
- **Alerts by email or WhatsApp.** Later.
- **Couriers other than Bosta.** HBA's other couriers are a separate question.
- **Trend charts.** Nothing beyond the success-rate range and the 7-day pickups.
- **Any change to commission, payroll, or the rule that delivery for money comes from Shopify.**
- **Arabic / RTL.** The platform is English-only for now.

## Delivery Milestones

| # | Milestone | Outcome | Status | Plan |
|---|---|---|---|---|
| 1 | Prove the Bosta and E-stebdal connections | The owner creates a **read-only** Bosta API key and an E-stebdal API key. A one-off read-only check confirms, card by card, what Bosta's API can supply: search with a key, the printed flag, the pickup day, the success figure and date ranges. Each Bosta card gets a go or no-go before anything is built. | complete — keys work and every card is supplied (Appendix C); B4 is within half a point of Bosta's dashboard, with the exact match left to acceptance | — |
| 2 | Operations-manager access | The admin can invite an operations manager. That person lands on Operations and sees nothing else, and the admin can switch between the two dashboards. A mockup is approved first, because no approved design exists for this screen. | in-progress | `.claude/plans/operations-dashboard.plan.md` (Phases 0–1) |
| 3 | Shopify tab | S1–S7 live with their lists, matching Shopify. | pending | `.claude/plans/operations-dashboard.plan.md` (Phases 2–3) |
| 4 | E-stebdal tab | E1 live with its list, matching E-stebdal. | pending | `.claude/plans/operations-dashboard.plan.md` (Phase 4) |
| 5 | Bosta tab | The B cards that passed milestone 1 are live with their lists, the success-rate range and the 7-day pickups. | pending | `.claude/plans/operations-dashboard.plan.md` (Phases 5–7) |

## Open Questions

- [ ] **B4 exact match.** For September, B4's definition gives 970 successful and 176 unsuccessful (84.6%); Bosta's dashboard shows 968 and 170 (85.1%).
  - **Possible causes:** orders that finished after Bosta last refreshed its figure, or a handful of edge cases.
  - **Next step:** reconcile order by order at the Bosta-tab acceptance, using an export of Bosta's unsuccessful orders for one range.
  - **Until then:** the agreed tolerance is TBD; proposed within 0.5 percentage points.
- [ ] **Navigation.** Operations is a separate dashboard, not a seventh tab, so the approved design's "six main tabs" rule still holds. Confirm with the mockup.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A tag is renamed or spelled differently by an app or a person | Medium | High: counts go wrong without anyone noticing | Tag rules kept in one agreed list, spelling variants included; a way to notice new, unknown tags (TBD) |
| A source is down or slow | Medium | Medium | "Last updated" on every card; failures shown as failures, never as 0 |
| Reading Bosta every few minutes hits its rate limits | Low: Bosta sends no rate-limit headers, and a full refresh of recently changed orders is about 3 requests | Medium: numbers older than 10 minutes | Read only orders changed since the last read; back off when refused |
| Bosta changes an undocumented field the cards rely on (print date, collection time, the waiting-for-action flag) | Medium | High: a card goes wrong without anyone noticing | Each card shows a failure, not a guess, when a field it relies on goes missing; checks against Bosta's own counts where Bosta has one |
| Operations work leaks into money logic | Low | High | Operations only reads; Bosta never feeds pay; new ADR |
| A Bosta key with write access is exposed | Low | High: it could create or cancel deliveries | Require a read-only key; stored encrypted; only the admin enters it |
| Release is tied to the audit repair | Medium | Medium | Separate branch; merged and released only when the owner authorises |
| A new role sees customer data | Low | Medium | Lists carry no customer details; link out to the source system |

## Appendix A — tag spellings in the live store (3 Oct 2026)

- **In use on recent orders:**
  - `Confirmed ✅` (also written `Confirmed✅`)
  - `Call Confirmed📞`
  - `No answer`, `no answer( 2 times )`
  - `WA Sent 📤`, `No WhatsApp 📵`
  - `bosta_synced`, `bosta_sync_failed`
  - `compression`, `UNDERWEAR`
  - `Cancelled ❌`
  - `Paid`, `Edit ✏️`, `الرقم غلط` (wrong number)
- **Only on old orders (ignored by the dashboard):**
  - `✅ Order Confirmed`, `Confirmed`
  - `⚠ NO WhatsApp`
  - `❌ Order Canceled`, `Cancelled`, `Canceled`
  - `⚠ Confirmation Pending`, `⌛ Confirmation Scheduled`
  - `out of trials`, `Edit Required✏️`

## Appendix B — source facts

**Bosta order statuses** (Bosta's documentation):

| Code | Status | Code | Status |
|---|---|---|---|
| 10 | Pickup requested (new) | 41 | Picked up (out for delivery) |
| 11 | Waiting for route | 45 | Delivered |
| 20 | Route assigned | 46 | Returned to business |
| 21 | Picked up from business | 47 | Exception |
| 22 | Picking up from consignee | 48 | Terminated |
| 23 | Picked up from consignee | 49 | Canceled |
| 24 | Received at warehouse | 60 | Returned to stock |
| 25 | Fulfilled | 100 | Lost |
| 30 | In transit between hubs | 101 | Damaged |
| 40 | Picking up | 102 | Investigation |
| | | 103 | Awaiting your action |
| | | 104 | Archived |
| | | 105 | On hold |

**Bosta API keys** can be created with a "Read Only" level, under Settings → API Integration. Creating one needs a code sent to the account phone.

**E-stebdal:**
- A request gets the status "Needs Review" when the customer submits it.
- The full status list is: Pending Payment, Needs Review, Approved, Rejected, Processing, Closed, Cancelled.
- The public API counts returns by status, using a key created in the E-stebdal dashboard.

## Appendix C — milestone 1 check (3 Oct 2026, read-only, from staging)

**Access.**
- The Bosta key works with a bare `Authorization` header for:
  - order search
  - single orders
  - pickups
  - Bosta's summary counts

  That is despite Bosta's documentation saying these need a dashboard sign-in.
- The E-stebdal key works on the returns list.
- The Shopify tags read through the app's existing access.

**What each card reads, and what it showed on 3 Oct:**

| Card | Source | 3 Oct |
|---|---|---|
| B1 New, not shipped | Orders in "Pickup requested", aged by their Bosta creation time | 103 waiting for pickup; **29** more than 2 working days (26 of them 5+) |
| B2 Not printed | The airway-bill print date on each order (`latestAWBPrintDate`) | 102 of 103 printed; **1** not printed |
| B3 Picked up per day | The time Bosta collected each parcel from HBA (`collectedFromBusiness`) | 3 Oct 5 · 2 Oct (Fri) 0 · 1 Oct 70 · 30 Sep 13 · 29 Sep 35 · 28 Sep 32 · 27 Sep 86 |
| B4 Success rate | Bosta's summary counts have no date range (date parameters are ignored), so the platform works it out from orders created in the range | September: **970 / 176 = 84.6%**; Bosta's dashboard: 968 / 170 = 85.1%. Counting by pickup or finish date was further off (1,002 / 212). |
| B5 Awaiting your action | The "waiting for business action" flag on unfinished orders | **2**, both delivery exceptions. Equals Bosta's own count of 2; searching by the status "Awaiting your action" finds 0. |
| B6 Shipped, not delivered | Collection time on unfinished orders | 60 on the way; **9** collected more than 3 working days ago |
| E1 Needs review | E-stebdal returns, filtered by status | **3** |

**Limits:**
- **Bosta search pages:** up to 200 orders a page. The `count` field always says 0, so totals are counted page by page. The search can be sorted by last change and limited to a creation-date range; other date filters are ignored. About 600 orders changed in the last 9 days, which is 3 pages.
- **Bosta pickups:** each pickup lists only some of the parcels it collected, so they are not used for B3.
- **Pickup time:** use `collectedFromBusiness`. The order's `state.pickedUpTime` is not when Bosta collected the parcel from HBA; it carries the delivery date.
- **Bosta rate limits:** no rate-limit headers sent.
- **E-stebdal rate limits:** 200 requests a minute.

---
*Status: DRAFT — requirements only. Implementation planning pending via /plan.*
