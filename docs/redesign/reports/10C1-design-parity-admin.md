# Batch report — C1, the admin screens against the approved design

Date: 12 September 2026.

Branch: `phase10/c1-design-parity`, based on `main` @ `7431360`, with
`review/approved-design-parity` (`ef0e597`) merged in.

Requested scope: **C1** of the design-parity correction — finish the admin
screens against the approved export. This report covers **Home and the Models
roster**; the profile, Settings and Products are carried forward.

**This is the first batch in this project with visual evidence.** Yahya signed
in himself on staging, and the approved export was served locally and compared
at 1440px. That is what this batch is founded on, and it is why it exists.

---

## Review

### What the comparison actually showed

The imported correction branch's audit was right, and my own status was wrong.
Rendered side by side, admin Home was not a themed version of the approved
design — it was a different page:

| | Approved | What shipped |
|---|---|---|
| Notices | 3 compact rows, each with a labelled action | 4 tall blocks, no action but *hide* |
| The money | 3 business cards, breakdown **inside** the payment card | 4 operational tiles, breakdown in a panel below |
| Content | A table of models: videos, stories, last update | Two aggregate count lines |
| Top three | Avatar, name, **discount code** | Name only |
| Sidebar | Count badges, filled active pill | Neither |

Nine batch reports said *visual evidence: none*, and every one of them was
telling the truth. The error was the inference stacked on top: that a feature
which exists, is routed and is covered by a test has been delivered as
designed. **A test asserting a component contains a word says nothing about
where that word sits, what it sits beside, or whether the screen opens with
money or with errors.**

### Home: the panel that counted people instead of naming them

The approved Home shows *Content progress to review* as a table — model,
videos, stories, last update. What shipped showed `2 models · nothing recorded
this week`, which tells the owner a number and then makes her open Targets to
find out which two.

`content_rows` now returns a row per model. Three distinctions it holds:

- **Nothing asked for is not nothing produced.** A missing `monthly_target`
  row and a row of zeroes mean opposite things — the first is HBA's own
  omission, the second is a fact about her month. Collapsing both to `0` puts
  a model in front of the owner as behind when the gap is HBA's.
- **Videos and stories stay apart**, unlike D08's pace, which adds them to
  decide whether she is on track. Four videos short is a different
  conversation from four stories short.
- **Worst first.** Untouched, then least produced. Alphabetical would put
  whoever is fine at the top on a good day.

The leaderboard now carries her code, read **for that month** rather than as
*her code now*, so a code that changes hands cannot relabel a settled month.

### The notice detail line that does not exist

The branch rendered `item.detail` under each notice, as the design draws it.
**There is no such field**, and there should not be: the owner already ruled on
this — *"this is too much and as an admin I don't need all of this. Just one
liners."* The dead render is removed and the reason recorded next to it, so the
design's two-line notice is not reintroduced later as a fix.

What the notices gained instead is the useful half: a **labelled** action
button — *Open sync*, not *Open* — so the column can be read down.

### Models: a roster you can search

The approved roster is segments and a search above a table whose first column
is the person: initial, name, and the code an order knows her by. Then status,
that month's sales, content, and what needs attention.

**Search covers name and code**, because those are the two things anybody
knows a model by — HBA thinks of her by name, and an order knows her only by
the code printed on it. A name-only search fails exactly when somebody is
holding an order and asking whose it is.

*Show archived* is gone, replaced by an **Archived segment**. Archived is one
of the states a model can be in; a separate checkbox let the two controls
disagree about what the list was showing.

The sales and content columns come from `month_performance` and the same
`content_rows` Home uses — **the models' own leaderboard figure (D03)**, so the
roster, Home and a model's own screen cannot tell three different stories about
one month. Neither column is money owed to anybody and neither recalculates any.

### The sidebar badge that is deliberately half-built

*Models* carries a count of applications waiting. **Payments does not**, and
that is the point: what is still owed is computed by the Payments screen from
snapshots and the ledger, and a sidebar working it out for itself would be a
second implementation of a money figure — the one thing this codebase refuses.
A test holds the absence, so the badge cannot be added casually; it joins when
the payments batch can hand it the same number from the same place.

### D12, and the migration nobody expected

The owner answered it this morning: **a featured product needs no message.**
The approved design shows the product's picture as the instruction and the note
as optional; the server refused a blank one in two places.

Both refusals are gone, and blank collapses to `NULL` on purpose — otherwise a
sentence typed once could never be taken back, which is the same trap from the
other side. `product_feature_request.message` was `NOT NULL`, so this needed a
migration: **`a17f4c9b2e30`**.

Its `downgrade` is the interesting half. A request written without a note
cannot exist under the old schema, so going back fills them with the word
*Featured* rather than deleting the row — deleting would silently un-feature a
product somebody chose. **It is a placeholder, not something anybody wrote**,
and the migration says so.

One existing test asserted the old refusal. It is **reversed in place rather
than deleted**, with the reason in its docstring, so nobody later wonders
whether the rule was lost by accident.

### Two bugs the ratchet caught, and one was in the imported branch

`test_every_capability_has_a_way_in` failed on two routes:

```
GET /api/operations/counts
PUT /api/products/{}/feature-request
```

Both were reachable from the interface. The scanner finds a route by matching
a call with its type parameter, and that pattern **stops at the first closing
angle bracket** — so a *nested* generic hides the call. Mine was
`api.get<Record<string, number>>`; the branch's was
`api.put<NonNullable<Detail[...]>>`.

The branch could not have known: **it never ran the backend suite**, having no
isolated PostgreSQL. Both are fixed by naming the type, which is better code
anyway. The scanner is left alone — a regex that parsed nested generics would
be a worse thing to maintain than a house rule that call sites use named types.

### What the owner should look at

Staging, once this deploys: **Home** and **Models**. On Home, the content panel
should now name models rather than count them, and the top three should show
codes. On Models, try the search with a **code** rather than a name.

### Approved-design deviations and reason

- **No notice detail line.** The owner asked for one-liners; the design's
  second line is superseded.
- **No Payments badge yet.** See above — it waits for the money path rather
  than inventing a second one.
- **`E£`, not `EGP`.** The owner chose it, 12 September; the export's `EGP` is
  a prototype default rather than a decision.
- **Home's sales-per-month chart is not built.** It needs an admin-side series
  that does not exist; it belongs with C2's read contracts.
- **The payout card has no *deductions carried in* line.** The design shows
  one. Getting it right means deciding whether the hero figure is net of
  recovery, which is a D04 question about what *expected payment* means —
  **C2**, not a layout change.

### Confirmation needed before the next dependent decision

**None.** D01–D12 are all closed.

---

## Engineering evidence

### Files changed

| File | Change |
|---|---|
| `app/services/overview.py` | `content_rows` per model; the code on the leaderboard |
| `app/api/payroll.py` | `content` on the month summary |
| `app/api/affiliates.py` | Roster takes a month; sales and content per row |
| `app/api/operations.py` | **New** `/api/operations/counts` |
| `app/services/wardrobe.py` | D12 — `_wording`, both refusals removed |
| `app/models/promotions.py` | `message` is nullable |
| `migrations/versions/a17f4c9b2e30_…` | **New migration** |
| `frontend/…/Overview.tsx`, `.css` | Content table, code, labelled actions |
| `frontend/…/Affiliates.tsx`, `.css` | Segments, search, approved columns |
| `frontend/…/Layout.tsx`, `.css` | The Models count badge |
| `frontend/…/Products.tsx` | Named `FeatureRequest` type |
| `tests/…` | 6 overview, 3 operations, 3 wardrobe; 1 reversed |
| `frontend/…/__tests__/Overview.test.tsx`, `Affiliates.test.tsx` | **New**, 18 |

### Database migrations

**One: `a17f4c9b2e30`** — `product_feature_request.message` becomes nullable.
Additive; no backfill; a `downgrade` that says what it costs.

### No real credentials or personal data in evidence

Every fixture is synthetic. The staging session was the owner's own, entered by
him in his own browser; no credential passed through this session.

---

## Continuation

### Remaining limitations

- **C1 is not finished.** The model profile, Settings subsections and the
  Products catalogue still need comparing against the export.
- **The model portal has not been looked at at all.** It is next after the
  admin, by the owner's instruction.
- The imported branch's portal changes (`MyMonth`, `MyWardrobe`, `MyOrders`,
  `AffiliateLayout`) are merged but **unreviewed and unseen**.

### Exact next batch

**C1 continued** — admin profile, Settings and Products against the export;
then the model portal, with a model sign-in.
