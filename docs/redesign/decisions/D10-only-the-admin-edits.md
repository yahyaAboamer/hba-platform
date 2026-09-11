# Decision — D10

**Owner's question:** If finance colleagues need their own accounts, which
roles and permissions should they have? Is a restricted payer role wanted?

**Owner's answer**, 12 September 2026: **skip it — only the admin edits.**

---

## What was decided

**No new role.** Recording a payment stays admin-only, as it is today. The
prototype's *Finance* label described a person who does not exist at HBA.

HBA is two people. A restricted payer role would be a permission boundary
between colleagues who sit in the same room, maintained forever, protecting
against nothing.

## What this settles

`ROUTE_AND_PERMISSION_MAP.md` recorded the factual mapping — which capability
each existing role actually has — and marked the question of whether a new one
was *wanted* as the owner's. It is answered: no.

Phase 08 shipped settings without a role change, correctly.

## What it does not change

**The existing roles stay exactly as they are**, including `content_manager`,
and nobody is promoted to admin to get a job done. **Accounts are never
shared** — that was true before this decision and is not weakened by it. If HBA
hires someone who needs to send money without editing terms, this is reopened
then, with a real person to design it around.

Open set after this: **none.** D01–D12 are all closed.
