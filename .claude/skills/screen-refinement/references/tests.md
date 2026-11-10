# The tests every screen gets

Run each against **every state** in the gallery, at 390 and 1440. A failure
is a finding (ID, severity, where, what, screenshot). Origin in brackets:
the Payments journal section that produced the test.

## Meaning (run these first on any screen with figures)

1. **Adds up.** On any screen with more than one amount, the figures must
   reconcile (A − B = C really holds). (§4, F-L1)
2. **The label test.** Read each figure's label aloud in every state the row
   can be in, especially overpaid, credited, partly settled, zero and
   negative. Any state where the label is false is a finding. "Adds up" is
   necessary, not sufficient: *Total to send* added up and still called
   money already sent "to send". (§11, lesson 13)
3. **Same fact, same source.** Where one fact appears twice (a card and a
   warning), both must come from the same server field, or say it once.
   (§11, F2-1)
4. **Server, not client.** The client chooses which server figure goes under
   which label; it never sums or derives money. (ADR 0075, *Not changed*)

## Safety

5. **The act-in-state test.** For every button, list the states it shows in
   and ask whether pressing it there could cause harm (a send button on an
   overpaid or unapproved month). The owner weighs the finding. (lesson 15)
6. **Confirm only the irreversible**, name the consequence, and label the
   button with act + object (*Approve EGP 6,400*), never *Yes*. Do not add a
   confirmation where the action already has its own page or idempotent key.
7. **Nothing preselected** on a decision that moves or forgives money.
8. **Never hidden:** an amount, a consequence, an irreversible act, a
   changed destination, why something is blocked.

## Density

9. **The repetition count.** Per screen, count how many times each amount
   and each fact appears. More than once needs a reason. This cut more than
   shorter wording did. (lesson 14)
10. **Measure** words in `main` and page height at 390, before and after
    (`tools/words.js`). Record the table in the journal. (lesson 17)
11. **Hide what is empty:** zero-count filters, empty placeholders, cards
    that exist only to say they can't be used yet, rows that repeat another.
12. **Explanations → facts.** Replace "how it works" paragraphs with the one
    fact the reader needs; option descriptions must not restate their titles.

## Direction

13. **The next-step sentence.** For each screen, write the one sentence of
    what happens next. If you cannot, the screen has no clear next act.
    Show it only where it helps (Payments: only at the send stage).
14. **Three tiers of message**, each with one look: *warning* (real risk;
    bold fact + the act that fixes it, as a button), *note* (a fact that
    changes how to read a figure), *help* (quiet text). A missing setup that
    is somebody's turn is a warning, not an error.

## Forms and accessibility

15. Errors under their own field, `aria-invalid` + `aria-describedby`.
16. A disabled button says why, beside itself. Prefer a guard in submit too.
17. Optional fields marked; hints say what to do, not how the system works.
18. Keyboard: logical tab order, visible focus ring, dialogs open with focus
    on their act and return it on Cancel; pickers usable by arrow keys.

## Phone

19. No sideways scroll at 360 / 390 / 430.
20. Every control at least 44px tall; inputs and selects at least 16px text
    (iOS zooms below that).
21. Answer first: on a phone, the amount or status leads, then the next act;
    tables become rows, not a clipped table.
22. Touch checked in a device-emulated session with real `tap()`.

## Look

23. **Look at the after captures** after any CSS that hides, reorders or
    re-grids elements. Tests don't see layout.
24. Both themes. No new colours, icons or gradients; amounts inside buttons
    inherit the button's colour.
25. 0 console errors on every route.
