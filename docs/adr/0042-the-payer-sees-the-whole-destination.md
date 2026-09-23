# 0042 — The payer sees the whole destination, without asking twice

**Status:** accepted
**Date:** 2026-09-20
**Amends:** [0028](0028-paying-by-bank-or-wallet-needs-a-number-not-a-link.md)
**Related:** spec §6.4.4, §13.1, §14;
`docs/redesign/designs/Admin Dashboard.dc.html` (`destinationCard`, `payRows`)

## The situation

ADR 0028 put the real payout values behind an audited reveal: a click, a POST,
an audit row, then the number. The payments table showed `InstaPay · …291` and
a *Copy* button that fetched the value through that route.

The reasoning was about records — an account number must not leak into a log,
a notification, or a change confirmation — and that part was right and stays
right.

**The owner has overruled the mechanism, explicitly:**

> Follow my approved payment-details design, including accessible full payment
> details and the supplied InstaPay link. Earlier internal decisions do not
> override my explicit requirements.

The approved export agrees with him in every particular, and always did:

```js
// the payments table
destinationLabel: "InstaPay · " + p.phone          // the whole number, on the row

// the payment detail card
rows: [{ label: "InstaPay number",              value: p.phone, copy: "number" },
       { label: "Payment link, as submitted",   value: p.link,  copy: "link" }],
link: p.link                                        // and an "Open InstaPay" button
```

There is no reveal step anywhere in the approved design. Reading 0028 as
absolute produced a screen that could not do the job it exists for: somebody
with a banking app open, working down a list of twenty transfers, cannot type
`…291`, and a click-to-reveal per row is a click per transfer at the one
moment the screen is supposed to be fast.

## Decision

**The destination is shown in full to the person who may send money, on the
row and on the card, with no intermediate step.**

1. `destination_line` — the export's `InstaPay · 010 7014 2033` — is on the
   payments row.
2. `destination_card` carries the labelled rows the export draws, each with
   its copy affordance, plus the InstaPay payment address **as she submitted
   it** (§13.1) behind an *Open InstaPay* button. The link is never rebuilt
   from the number; a phone hands the submitted link straight to the app,
   which is the whole reason that field is collected as a link.
3. Both are served **only** where `payments.record` holds — the permission
   ADR 0028 already chose for the reveal. Marketing reads the same screen and
   still sees the masked sentence.
3. **And on the model's own profile**, which is the same card drawn by the
   same component. Added 23 September 2026, after a browser sweep found the
   payments desk showing a model's whole InstaPay number while her profile one
   click away still printed `InstaPay · …291` — the same fact, to the same
   person, on the same permission, written two ways. The export draws the card
   on both. `frontend/src/components/DestinationDetails.tsx` is now the only
   place it is drawn, and `payout_destination_card` is served on the same
   `payments.record` check, so the gate cannot widen by being reimplemented.
4. **The admin reveal route is removed.** It was kept in a first draft of
   this ADR on the grounds that deleting a working route is churn;
   `test_reachability` disagreed, and it was right. A capability with no way
   in from the interface is exactly what that ratchet exists to catch, and an
   authenticated route nobody calls is a thing to be found later and wondered
   about. `/api/me/payout-destination` — the model's own, which she asks for
   deliberately — is untouched.

## What does not change

**`mask_destination` is untouched, and it is still the only representation
allowed outside the payer's screens.** Audit rows, logs, notifications, the
confirmation shown when a destination changes, the roster, and the model's own
portal summary: all masked, exactly as 0028 requires. Nothing in this ADR puts
a value anywhere it is written down.

*"The payer's screens"* is now two - the payments desk and the model's profile
- and the amendment above says why. The `payout_destination` field on that
profile is still masked and still what anything writing a record reads; what
was added beside it is a second field, served on `payments.record`, carrying
the card.

## The cost, stated plainly

**The audit no longer records who looked at a destination.** Under 0028 every
sight of a real number left a row saying who and when. Now anybody with
`payments.record` sees every destination whenever they open the desk, and
nothing records it.

That is a real loss and it is the thing being traded. What remains is the
permission itself — the set of people who can see these values is unchanged,
and it is small — plus the audit of what they *do*: recording a payment still
writes its own row, and that is the act with money attached.

The alternative was a screen that made the job slower at its busiest moment to
keep a log nobody had read. The owner weighed those and chose; this records
that he did, and what it cost, so that nobody re-derives 0028 from first
principles and quietly puts the click back.
