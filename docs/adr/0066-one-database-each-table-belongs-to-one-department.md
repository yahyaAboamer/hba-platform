# 0066. One database; each table belongs to one department

**Status:** Accepted — owner, 25 October 2026, with the architecture proposal of that day. **Not built yet** (the rule applies to every new table now; the check that enforces it comes with ADR 0065's folders).
**Date:** 2026-10-25
**Builds on:** ADR 0065 (one application, arranged by department), ADR 0010 (two-tier order storage), ADR 0059 (the inbox holds the only customer data)

## Context

The platform has one Postgres database with 46 tables in one schema. Two
things in it depend on that:

- **A change and its audit entry are saved together or not at all.**
  `record_audit` stages the audit row and the caller commits it with the change
  it describes (`app/services/audit.py`). The same holds for a payment and its
  allocation, and for payroll's freeze, which reads orders and payments at once.
- **Departments already read each other's facts.** An order is held four ways,
  each for its own purpose: `order_index` (every Shopify order, thinly),
  `attributed_order` (the money detail of a model's orders), `ops_shopify_order`
  (Operations' five-minute read) and `order_confirmation` (the Inbox). All four
  are keyed by Shopify's order id, which is what lets one page show an order
  whole (ADR 0068).

Some table names already say whose they are (`inbox_…`, `ops_…`); most older
ones do not. Customer details are kept in the inbox's tables and nowhere else
(ADR 0059), and the catalogue and order tables were built to hold none.

## Decision

**One database and one schema. Every table belongs to exactly one department;
only that department's code writes it, and other departments read it through
that department's functions (ADR 0065).**

Today's tables belong as follows:

| Owner | Tables |
|---|---|
| **Shared core** | `user_account`, `role_assignment`, `auth_session`, `invitation`, `password_reset`, `staff_preference`, `audit_event`, `background_job`, `integration_event`, `notification_outbox`, `notification_preference`, `notice_mute`, `shopify_connection` |
| **Shopify mirror** (shared core, read by all) | `order_index`, `product`, `product_variant`, `order_line_item` |
| **Affiliates** | `affiliate_profile`, `attributed_order`, `discount_code_period`, `compensation_period`, `monthly_target`, `payroll_month`, `policy_version`, `payroll_snapshot`, `proof_file`, `payment_transaction`, `payment_allocation`, `payroll_adjustment`, `payout_destination`, `product_feature_request`, `model_shipment`, `manual_wardrobe_item` |
| **Operations** | `ops_source_status`, `ops_shopify_order`, `ops_estebdal_return`, `ops_bosta_delivery`, `ops_bosta_sync`, `ops_integration_key` |
| **Inbox** | `inbox_conversation`, `inbox_message`, `inbox_media`, `order_confirmation`, `meta_webhook_event`, `inbox_connection`, `shopify_tags_connection` |
| **Production** (ADR 0069) | Its own tables, added when its data moves in |

- **New tables carry their department's prefix.** Existing tables keep their
  names: renaming a live table buys nothing a reader needs and risks every
  query that names it.
- **The shared records every department points at:**
  - **A person** is `user_account`. A staff profile (department, job, manager,
    start date) joins it when People needs one.
  - **A customer** stays in the inbox's tables, keyed by phone, until a second
    department needs to point at one. It then becomes one shared customer
    record, and personal details still live only there.
  - **An order** is Shopify's order id. The four order tables are not merged;
    the order page reads each by that id.
  - **A product** is the Shopify catalogue copy. Production's materials and
    stock join it by product and variant when they need to.
- **Outside tools get views, not tables.** When an accountant's or reporting
  tool needs read access, it gets a `reporting` schema of read-only views and a
  database login that can see nothing else. Not before.

## Consequences

- The database does not stop one department writing another's table; the
  code check does, and only for code that goes through it. A raw SQL statement
  can still cross the line, so review has to watch for it.
- One database remains a single point of failure, as it is today. Backups
  (ADR 0032) and the migration rehearsal in the release gates are what cover
  it.
- Every department shares one connection pool. At HBA's volume this is not a
  constraint; if Production's or a report's queries ever crowd the others out,
  that is measured and dealt with then.
- Customer details stay in one place, which keeps the rule of ADR 0059 true as
  departments are added, at the cost of a lookup whenever another department
  needs a customer's name.

## Alternatives considered

- **A database per department.** Breaks the guarantee that a change and its
  audit entry land together, and makes the order page a join across databases.
- **A schema per department.** Moves 46 live tables and rewrites every
  migration and raw query for a tidier list in a database tool, with nothing a
  person using the platform would notice. Revisit only if a department ever
  needs its own database credentials.
- **Merge the four order tables now.** Each was sized and frozen for its own
  purpose (ADR 0010, ADR 0011, ADR 0057, ADR 0059); merging them would trade
  those guarantees for tidiness. The order page gets the same result by
  reading them by one id.
