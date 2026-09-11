# Decision — D12

**Question:** The approved design shows a featured product as a card with the
product's image, and treats the accompanying note as optional. The server
refuses a feature request with a blank message. Which is right?

Not in the original list — it arose from the design-parity audit on
12 September 2026.

**Owner's answer**, 12 September 2026: **make it optional.**

---

## What was decided

A product can be featured for a model **with no message at all.** The image and
the product are the instruction; the note is there when somebody has something
extra to say ("before Thursday", "mention the shade"), and absent when they do
not.

## What changes

`app/services/wardrobe.py` raises `A feature request needs something to say` in
two places — once when creating a request and once when clearing an existing
message. **Both go.** A feature request with `message = None` becomes valid,
creatable and editable, and the model's Wardrobe renders the card without a
caption rather than falling back to placeholder text.

Clearing the note on an existing request must be possible too — otherwise a
sentence typed once can never be taken back, which is the same trap from the
other direction.

## Why the check existed, and why it goes

Nothing recorded justifies it; it reads as a default rather than a rule — a
required field because the form had a field. The cost is real: featuring ten
products for a campaign means typing ten notes that say the same thing, which
is how "please feature" becomes noise the model stops reading.

## What it does not change

**W09's three verbs are untouched** — `message` writes the wording, `visible`
shows or hides it, and removing is not the same as hiding. Making the message
optional does not merge hide and remove; the distinction exists so that hiding
keeps a paragraph somebody wrote.

**Eligibility is unchanged.** Which products a model may be offered, and the
Received/Processing states a request can be in, are D05 and the wardrobe rules.
