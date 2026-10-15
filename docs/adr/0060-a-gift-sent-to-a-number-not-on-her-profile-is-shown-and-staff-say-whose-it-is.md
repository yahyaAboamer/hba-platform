# 0060. A gift sent to a number not on her profile is shown, and staff say whose it is

**Status:** Accepted
**Date:** 2026-10-15
**Amends:** W03 and W12 (`docs/redesign/PRODUCT_RULES.md`): matching by the parcel's phone, and the bounded staff path

## Context

On 15 October 2026 the owner reported that products were not linked to every
model, after he had run *Read the catalogue* and *Match parcels*. Both runs had
finished. On production:

- 61 parcels were matched, every one with its products read.
- **47 free orders carrying a discount code** (`sponsordis`, HBA's gift code)
  matched nobody. Several carried a model's name: six gifts to "Mahmoud M"
  (Mahmoud eldahshan has none matched), two to "Faytoury F", one to
  "Mohamed Hany", four to "Mohamed Ahmed".

A parcel is matched to a model only when the phone on its shipping address
equals the phone on her profile. None of the 17 models had a *Phone on the
parcel* recorded, so the contact number was compared, and HBA ships many gifts
to a different number. The unmatched gifts were stored as `no_match`, which
the Settings screen counts as *customer orders, which is normal*, and lists
nowhere. Running *Match parcels* again repeats the same comparison and the
same answer.

A second, smaller fault: a number written `+20 010…` (country code **and** the
leading zero, thirteen digits) was refused as not an Egyptian mobile. About
forty orders are written that way. All were customers this time, but the next
model parcel written so would have been missed.

## Decision

### Gifts nobody received are shown, and staff say whose each is

Settings → Shopify and sync → *Needs attention* lists **gifts that matched no
model**: free orders (original subtotal zero) with a discount code, not
cancelled. Free exchange orders carry no code and stay out of it, so the list
holds HBA's gifts and nothing else. Each row shows the order, who it was
shipped to, the number and what was in it, read from Shopify when the list
opens.

For each row staff choose:

- **This is [model]**: the parcel becomes hers, and so does every other
  unmatched parcel sent to the same number. Its products are read within the
  hour.
- **Not a model**: the row leaves the list. It is not a match, and a later
  match on her profile phone still takes it.

Both are audited (`parcel.assigned`, `parcel.not_a_model`).

### A number staff confirmed is remembered

A number staff assigned to a model is one of **hers** from then on: the next
parcel sent to it matches her without anybody's help. No new table holds it.
The parcel staff confirmed is the record, marked `match_reason = 'assigned'`.

A model can therefore receive at more than one number: her profile phone and
every number staff confirmed. The rules that protect matching still hold:

- A number belonging to two models is refused as ambiguous and attaches to
  neither.
- An archived model takes no new parcels.
- A confirmed match is never re-decided.

### `+20 0…` is read as the Egyptian mobile it is

`+20 010 1234 5678` and `0020 010 1234 5678` normalise to `01012345678`. Any
other length is still refused.

## Consequences

- The products of a model's gifts reach her wardrobe and the catalogue's model
  coverage once staff assign the gift. Nothing is guessed from a name.
- A wrong assignment puts clothes in the wrong wardrobe. There is no undo on
  the screen in this change, and correcting one is a database change.
  Assignments are rare, single clicks with the recipient's name beside them,
  and audited.
- The list reads Shopify each time it opens: one request for up to 50 orders.
  If Shopify cannot be read, the rows show without names rather than not at all.
