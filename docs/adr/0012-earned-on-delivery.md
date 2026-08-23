# 0012. Commission is earned on delivery; HBA absorbs late returns

**Status:** Accepted
**Date:** 2026-08-22

## Context

The old dashboard applied the commission rate to **every** order in a month
regardless of its status, so a pending order earned commission the moment it was
placed. Failed deliveries were neutralised only by a Shopify automation that
auto-cancels them - protection living entirely outside the codebase, which would
disappear silently if that automation were ever switched off.

For a brand shipping cash-on-delivery through Bosta, that matters: refusal rates
are material, and paying commission on goods never delivered is a direct loss.

## Decision

Each order carries a commission state:

| State | Meaning | Counts toward payout |
|---|---|---|
| `pending` | In transit, or an exchange is open | **No**, shown separately |
| `earned` | **Delivered**, no open return or exchange | **Yes** |
| `void` | Cancelled, fully refunded, or failed delivery | No |

An order becomes `earned` **on delivery**, not after the ten-day return window
closes. Waiting the full window would delay affiliate earnings for no practical
gain: a return arriving while the month is still draft simply voids the order
and removes the commission.

**The risk HBA accepts, deliberately:** an order delivered on 31 August and
approved on 5 September still carries six days of return exposure. If the
customer returns it afterwards, HBA absorbs the commission rather than clawing
it back from the affiliate.

## Consequences

Affiliates are paid promptly and predictably, which is worth more to the
relationship than recovering the occasional late return.

The exposure is bounded by the return window and is a business decision, not an
oversight. It is written here so that a future maintainer finding an
unrecovered commission does not treat it as a bug.

The platform enforces the delivery rule itself rather than depending on an
external Shopify automation.

## Alternatives considered

**Earn only after the return window matures.** More conservative, and delays
every affiliate's earnings by ten days to recover a small number of reversals.

**Claw back from the next payout.** Standard in larger affiliate programmes, and
corrosive at this scale, where the affiliates are twenty people the business
knows personally.
