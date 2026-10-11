# 0057. Operations is its own dashboard, for one operations manager, and it only reads

**Status:** Accepted — owner, 5 October 2026, with the mockup `docs/design/operations-dashboard-2026-10-03.html`
**Date:** 2026-10-03
**To be amended by [0059](0059-order-confirmation-and-the-customer-inbox-move-into-the-platform.md) when that is built:** a fourth tab, WhatsApp, and the operations manager also holds the customer inbox. Until then this record stands as written.
**Follows:** 0023 (delivery is read from Shopify, not from Bosta), 0015 and 0045 (Shopify is read-only; its secret is kept encrypted in Settings)

## Context

HBA's order flow lives in three systems that nobody sees together:

- **Shopify tags** record how far confirmation has gone.
- **Bosta** knows whether a parcel was printed, collected or delivered, or is waiting on HBA.
- **E-stebdal** holds return and exchange requests waiting for review.

The v1 design deferred an operations module to V2 (spec §3). On 3 October 2026:

- 29 orders had waited more than 2 working days for Bosta to collect them, 26 of them for 5 or more.
- 9 parcels were more than 3 working days past collection and still not delivered.
- 5 confirmed orders had failed to reach Bosta.
- 3 returns were waiting for review.

None of this showed anywhere without filtering three systems by hand. The owner set the requirements on 1–3 October in `.claude/prds/operations-dashboard.prd.md`.

ADR 0023 keeps Bosta out of anything that decides pay: two sources that disagree about one parcel need a person every time.

The connection check on 3 October established:
- **Bosta:** a read key answers order search, single orders, pickups and Bosta's own summary, although the documentation says those need a dashboard sign-in.
- **E-stebdal:** its key answers the returns list.
- **Shopify:** tags read through the app's existing `read_orders` access.

## Decision

1. **Operations is its own dashboard on the same platform.** It shares the sign-in, accounts, database and deployment with the rest. It has three tabs: Shopify, Bosta and E-stebdal. It is not a seventh section of the affiliate dashboard.
2. **A new role, operations manager**, holds one permission, `order_ops.view`.
   - He lands on Operations and sees nothing of models, codes, targets, payroll or payments.
   - Affiliate managers, content managers and models see nothing of Operations.
   - The admin holds everything and switches between the two dashboards.
3. **Exactly one operations manager at a time.** The database refuses a second live holder. Only an admin can give the role, and the operations manager invites nobody.
4. **Operations only reads.** It writes nothing to Shopify, Bosta or E-stebdal; every order on it links to where the fix is made.
5. **Bosta is a source for operations only.** Its data never decides whether an order counts as delivered for pay, and ADR 0023 stands. Where Bosta and Shopify disagree about a parcel, Operations may show it; money keeps Shopify's answer.
6. **Every number is at most 10 minutes old, for every order.**
   - Each source is read every 5 minutes into the platform's own tables, and the dashboard reads only those.
   - Webhooks may make a change show sooner but are never relied on.
   - A card always shows when its number was read. A source that can't be reached shows as a failure, never as 0.
7. **No customer details are stored or shown.** That means no names, phones, addresses or notes. Lists carry order, tracking and return numbers. No model or commission detail appears either.
8. **Day limits count working days in Cairo time**: Saturday to Thursday. Only Friday is off, and there is no holiday list.
9. **Bosta's success rate is worked out the way Bosta's dashboard does it.**

   | Part | Definition |
   |---|---|
   | Range | Orders created on Bosta in the chosen range |
   | Successful | Delivered orders, finished exchanges and finished customer return pickups |
   | Unsuccessful | Failed deliveries that came back to HBA |

   Checked against Bosta's dashboard for September 2026, the figures are close but not equal:

   | | Successful | Unsuccessful | Rate |
   |---|---|---|---|
   | This definition | 970 | 176 | 84.6% |
   | Bosta's dashboard | 968 | 170 | 85.1% |

   The gap is reconciled order by order when the Bosta tab is accepted.
10. **Keys.** The Bosta key is read-only. The Bosta and E-stebdal keys are environment variables until Settings can hold them encrypted, as the Shopify secret is (ADR 0045).
    - *7 October 2026 (build phase 6):* Settings → Shopify now holds them, encrypted the same way and checked against their provider before saving; only the last four characters are ever shown. The environment variables remain the fallback when nothing is saved.

## Consequences

- **Two more outside systems to keep alive.** Bosta and E-stebdal each bring their own keys and limits. Three of the Bosta fields this relies on are undocumented: `latestAWBPrintDate`, `collectedFromBusiness` and `state.waitingForBusinessAction`. If one disappears, its card shows a failure, not a guess.
- **Steady background traffic.** Polling is a few requests per source every 5 minutes, and staging and production both poll.
- **New screens without an approved export.** Operations has its own shell and screens. They are built from an owner-approved mockup and recorded as a divergence.
- **Freshness depends on the background worker.** If the worker stops, every card shows its age and turns stale; it never looks current.
- **Card rules depend on how the team spells its tags.** A renamed tag drops orders from a card until the rule is updated.
- **The success rate is a reconstruction.** It can drift if Bosta changes how it groups outcomes.
- **Replacing the operations manager takes two steps.** First change the old account's access, then invite the new person.

## Alternatives considered

- **A separate app,** as the earlier `hba-operations-hub` was. Rejected: it duplicates sign-in, roles, the Shopify connection, the worker and the deploys. That hub ran on sample data and never reached Bosta or E-stebdal.
- **A seventh section in the affiliate dashboard.** Rejected: the operations manager must see nothing else, and the approved design has six sections.
- **Bosta as the source of delivery for pay, now that it is connected.** Rejected: ADR 0023's reason stands, and this ADR changes no money question.
- **Webhooks as the way numbers stay fresh.** Rejected, for three reasons:
  - Bosta sends nothing when an order is created or simply sits still, which is exactly what two cards count.
  - Staging receives no Shopify webhooks.
  - A missed webhook would leave a number quietly out of date.
- **Adding tags to the order sync's shared Shopify query.** Rejected: that query runs on every webhook and feeds commission, and one refused field stops orders indexing. Operations reads Shopify with its own query.
- **Bosta's own summary counts as the cards.** Rejected: they ignore date ranges, and "awaiting your action" isn't a searchable status. They are used only as a cross-check.
- **Showing customer names and phones in the lists.** Rejected by the owner. It would also need Shopify's protected-customer-data access and would widen what a leak exposes.
- **Several operations staff.** Rejected by the owner: the staff don't use this dashboard.
