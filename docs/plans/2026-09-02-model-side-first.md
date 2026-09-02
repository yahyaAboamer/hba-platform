# The six flows are paused. The model's side goes first.

**Decided:** 2026-09-02, by the business.

## Why

The six-flow audit was ordered by risk — onboarding, attribution, payroll,
payments, targets, then the model's own view. That order assumed everything
would be built before anyone used it.

The business changed the sequence for a better reason: **the admin side is
used by one person who can work around it; the model's side is used by twenty
people who cannot.** As long as the admin screens work and the numbers are
right, an awkward admin screen costs patience. An awkward model screen costs
trust, and it costs it with the people the platform exists to pay.

So: enhance what a model sees, ship it, onboard the twenty, and take the
admin side slowly afterwards. There is until the end of September before a
real month is paid, which is the deadline that actually matters.

## What shipped from flow 1

Merged and live in both environments.

| | |
|---|---|
| The emailed link could differ from the one on screen | One server-built link; they cannot disagree |
| Withdraw was offered on rows where it could only fail | Offered only where it can succeed |
| A dead link rendered the whole form | Checked on open; says why and stops |
| Invitations accumulated for ever | Closed when accepted; list filters on the account |
| Shopify rejected the credentials | Configuration; the container was older than the rotation |
| Two names for one person | One name, asked once, used on both sides |
| Fixing vs changing pay terms | One control: a later month opens, the same month rewrites |
| Paying mid-correction | Refused while any of that model's months sits reopened |
| A corrected month changed silently | Two sentences and an email with its own subject |

Also, not planned: Railway's builder upgraded itself and took every deploy
down. Both environments now build from a `Dockerfile` that cannot change
underneath the project, and a blanked variable no longer stops the app
booting. `affiliate.hbawear.store` is live and carries invitation emails.

## Agreed during flow 1, not built

Recorded so the pause does not quietly become a decision. None of these are
refused - they are owed.

- **Remove the customer discount field.** Agreed: it is recorded and never
  shown again, so it costs a decision each time and gives nothing back. Still
  present on the compensation screen.
- **Show the commission figure in the worked example.** "On E£10,000 of
  sales: E£5,000" states the answer without the E£2,000 it beat, so the
  reader cannot see which number won or by how much.
- **Let a model reveal their own payout details in full.** Masked at rest is
  right; masked with no way to look is not, for the person who typed them.
- **A dropdown of Egyptian banks**, and a sanity check on the account-holder
  field, which currently accepts sixteen digits as a name.
- **A dropdown of wallet providers**, plus the provider's name as its own
  field.
- **Add targets from the model's own page** rather than opening the whole
  list to record two numbers for one person.
- **More columns on the affiliates list** - this month's earnings, the
  arrangement, the last order date. Deferred deliberately: each is a
  per-model figure on a list screen, and the naive version costs one query
  per row. It wants the set-based treatment `readiness` already uses.
- **Verify what happens when a code is "changed" to the code it already is.**
  Unverified; exactly the shape that produces a confusing no-op.
- **The sign-out and glossary links wrap** mid-phrase in the portal header at
  desktop width.
- **Split the discount-code copy** for models who already have a code and
  those who do not.

Flows 2 to 6 - attribution, payroll, payments, targets - were never started.

## The new plan

1. **One walkthrough of the model's side**, in four parts (below), with the
   business reporting what they see, the same way flow 1 was run: what is
   good, what is confusing, what is wrong, what is missing.
2. **Build the enhancements.**
3. **Onboard the twenty models** on production.
4. **Then** the admin side, unhurried, including everything listed above.

## Before any model is invited

**There is no password reset, and a locked-out model cannot be re-invited.**
`create_invitation` refuses an address that already holds an account
("already on the programme"), and no reset route exists anywhere in the API.
A model who forgets their password today has no way back in short of editing
the database by hand.

That is survivable with one admin who knows their own password. It is not
survivable with twenty people. This is a launch blocker, not a nicety, and it
is being built now alongside the other password work agreed for after the
flows - strength feedback, rejecting known-breached passwords, and showing
what was typed. Two-factor stays version two.
