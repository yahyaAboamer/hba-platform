# 0028 — Paying by bank or wallet needs a number, not a link

**Status:** accepted, amended 2026-08-27, deep link verified 2026-08-27
**Date:** 2026-08-26
**Amends:** spec §13.1 (InstaPay details), §14 (Payments and proof)
**Related:** [0017](0017-proof-is-shown-to-the-affiliate.md), §6.4 (payout destination changes)

## The problem, as reported

> "People that will not go with InstaPay and choose maybe e-wallets or bank
> accounts, they won't have this link. So the action of me clicking the button
> shouldn't redirect me to the link."

Correct, and it goes one step further than the button.

§13.1 and §14 were written entirely around InstaPay: collect the **Payment
Address URL**, put it behind a **Pay** button, tap it, InstaPay opens with the
address pre-filled. That flow has a property nobody noticed was load-bearing —
**the person paying never has to read the address.** The link carries it.

`app/services/payouts.py` masks every sensitive field, and
`mask_destination` is the only representation the API returns. An InstaPay
address shown as `…291` is fine, because the deep link does the work.

A bank account number shown as `…291` is **useless**. The whole act of paying
by bank transfer is: read the number, type it into your banking app. There is
no link to carry it. Same for an e-wallet phone number.

So there were two faults, and the second is the serious one:

1. A **Pay** button with nothing to open, for two of the three methods.
2. **No path at all** by which the person sending the money could obtain the
   number they need to send it. The payment screen, as specified, could not
   have worked for a bank or wallet payout.

The second was invisible because the payment screen has not been built yet.
It would have been found the first time somebody tried to pay a model who
does not use InstaPay.

## What masking is actually for

Re-reading §6.4.4, the rule is narrower than "nobody may ever see it":

> the change is recorded in the audit log with **sensitive fields masked** —
> raw account numbers and InstaPay addresses are never copied verbatim into
> generic before/after JSON

Masking protects **records**: audit rows, logs, notifications, and the
confirmation screen shown when a destination changes. It was never meant to
stop the person doing the paying from paying. Reading it as an absolute made a
necessary task impossible.

## Decision

**One action in one place, doing the right thing for the method.**

| Method | The action | What it does |
|---|---|---|
| InstaPay | Open InstaPay | Deep-links with the address pre-filled. Nothing is displayed. |
| Bank | Show account number | Reveals the number and the holder's name, with a copy control. |
| Wallet | Show wallet number | Reveals the number, with a copy control. |

The button does not disappear for non-InstaPay methods and it does not
navigate. It keeps its position and weight, and its label says what it will do
before it is pressed. A control whose label changes with the method is honest;
a control that sometimes goes nowhere teaches people the tool is unreliable.

**Revealing is a deliberate, recorded act.**

- It requires `payments.record` — the permission for moving money, not the one
  for reading a profile.
- It is a separate request. Nothing is unmasked by merely opening a screen, so
  a page left open on a desk is not twenty account numbers.
- It writes an audit row: **who revealed whose destination, and when.** The
  value itself is never in the record — that would recreate exactly the leak
  §6.4.4 forbids.

**Everywhere else stays masked.** The affiliate's profile, every audit record,
every notification, every log line. Recognition, never use.

## Why not simply show the details unmasked on the profile

It was the other option on the table, and it is cheaper. Rejected because the
profile screen is the one somebody leaves open while doing something else, and
a list of twenty full account numbers is a different object from a list of
twenty masked ones — the first is worth photographing.

The cost of the alternative is one deliberate click, a few times a month, by
the one person already authorised to send money. Measured against a permanent
standing display of every payout destination in the programme, that is the
cheaper of the two. The reveal is not defence in depth over an already-closed
hole; it is the only thing standing between "the payer can pay" and "every
screen shows every account number".

## Consequences

- A reveal endpoint exists, permission-gated and audited.
- The payment screen's action is method-aware, and is built that way from the
  start rather than retrofitted.
- `mask_destination` remains the only representation everywhere else, and the
  rule it enforces is now stated precisely enough not to be misread again.
- The InstaPay deep-link discovery item in §13.1 still stands, and now affects
  one method out of three rather than the whole payment flow.

---

## Amendment, 2026-08-27 — the phone number is part of paying, not a spare

The table above gave InstaPay one thing to reveal: the address, fed to the deep
link. The reasoning was that nobody has to *read* an InstaPay address, so
putting it on screen would be a credential displayed for no one's benefit.

That reasoning was sound and the conclusion was still wrong, because it assumed
the deep link works.

> "Maybe when I press open InstaPay and come back to our application, it asks me
> whether it worked or not."

The concern is right. §13.1 already flags the deep link as **unverified** —
behaviour on Android, on iPhone, with and without the app installed, is
reported from experience and not documented anywhere. And there is a case where
it certainly does not work: **a desktop browser has no InstaPay app to open.**
Month-end payroll is desktop work. So the machine where the fallback matters
most is the machine the original design served worst.

**Decided: an InstaPay reveal returns the address and the phone number
together.** §13.1 already collects the number for exactly this purpose.

There is no exposure argument against it. The address *is* the means of
payment — anyone permitted to see it may see the number beside it.

### Why not ask "did it work?"

The proposal was a prompt on return from InstaPay: yes, go on to record the
payment; no, show the number. Rejected, and it is worth saying why, because the
instinct behind it is correct.

- **It asks a question the platform cannot verify and does not need.** Whether
  the app opened is something the person can see. Whether the *money moved* is a
  different question entirely, and the only acceptable answer to that one is the
  screenshot — §14 is emphatic that the platform must never record a payment
  that may not have happened.
- **It taxes the common case to serve the rare one.** Twenty models, twenty
  prompts, to catch the few where the link fails.
- **On a desktop it is not the rare case, it is every case** — twenty prompts,
  all answered "no", to reach a number that could have been on the screen from
  the start.

Showing both costs nothing and serves both outcomes without asking anyone
anything. If the app opens, the number is ignored. If it does not, the number
is already there.

### A related correction

The proposal continued *"it will just move me to the next page, which is
sending the screenshot and finalizing the month"*. Those are two separate acts
and they run in the other order.

A payment allocates to a `payroll_snapshot`, which only exists once the month
has been **approved**. So the month is finalised *before* anybody can be paid
against it. Approve → pay → record the payment with its proof. Paying a model
finalises nothing; there is nothing left to finalise by then.

---

## The deep link works — verified 2026-08-27

§13.1 called this an implementation discovery item: *"deep-link behaviour must
be verified on Android and iPhone, with and without the app installed, before
the Pay flow is built around it."* The Pay flow shipped in Phase 7 with this
still untested, which was recorded as overdue rather than upcoming.

**Now tested, on iPhone.** The business tapped an `ipn.eg` link on an iPhone
with InstaPay installed. **iOS handed it to the InstaPay app**, which is the
behaviour §13.1 assumed and the entire reason that section collects a link
rather than a number.

The app then showed *"QR verification failed"* — expected, and not a finding
about the mechanism. The link tapped was invented seed data, so no account
exists behind it. What was being tested is whether `ipn.eg` routes to the app,
and it does.

**What remains untested:** Android, and the behaviour with the app *not*
installed.

Android is expected to work: the business's reading is that it will behave as
iPhone does, and the mechanism is the same one either platform uses to claim a
domain - iOS Universal Links, Android App Links. That is a reasonable
expectation and it is **not** a test, so it is written here as an expectation.

Both matter less than they did before this ADR's amendment, because the number
now sits beside the link either way — a link that fails to open costs one
manual step, not the payment. Neither is worth chasing before a real Android
model is on the programme and can try their own address.

## What this settles, and what it changes

Nothing in the built flow. The Pay button stays, the number stays beside it.

What it removes is the possibility that the whole approach was wrong — that
`ipn.eg` links were inert and §13.1 had been built on a misremembered detail.
That was the real exposure, and it is now closed.

## The field is validated as a consequence

`normalise_instapay_address` checks a payment address is a URL on `ipn.eg`.
The host is checked and **the path is not**, deliberately: the domain is a
principled line, since a URL anywhere else cannot open InstaPay whatever else
it is, while the path shape is a guess — no real address has ever been seen by
this codebase, and refusing a genuine one because its path looks unfamiliar
would stop a model joining at all.

The mistake worth catching is a **phone number in the link field**. §13.1
collects both and they sit next to each other on the form; mixed up, nothing
errors at the time and it surfaces at month end when somebody tries to pay them.
That case gets its own message rather than falling through the host check,
which produced *"that one points at 01001234567"* — true, and nonsense to the
person who has to fix it.

The check lives inside `set_destination`, so the application, a model changing
their own destination, and a maintainer correcting one are all covered by the
same rule. A validator on one path is a validator with a way around it.
