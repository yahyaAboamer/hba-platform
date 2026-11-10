# Mistakes already made once

From the Payments journal (§8 and §11). Read before starting; add new ones
at the end of each screen's pass.

1. **Fixtures that disagree with the server hide real bugs, and invent fake
   ones.** The 8,500 vs 8,000 "contradiction" on Hana's month was the
   fixture's, not the product's. Derive fixture fields from the server's own
   formula and the real enums (`PAY_TYPE`, not a remembered key). Better:
   seed a disposable database and let the real server compute.
2. **When two endpoints describe one fact, build the fact once** and derive
   both responses from it. Lesson 1 was applied to the row and not to the
   statement, and failed again.
3. **A contradiction in a screenshot is a harness suspect first.** Read the
   server before calling it a product bug.
4. **"Adds up" is not "means what it says."** Test every label in every state.
5. **Your own new wording fails the label test too.** *Too much sent* was
   false after a partial settle; the reviewer caught it. Run the tests on the
   after state, not only the before.
6. **Density is repetition.** Count appearances before shortening sentences.
7. **A button can be a financial risk.** Check every act against every state
   it appears in, then let the owner weigh it (he kept *Open InstaPay*).
8. **Shared components: ask early.** "Out of scope" was the wrong call for
   the month picker.
9. **CSS specificity:** an override lost to an equal-weight rule declared
   later; every test passed and the phone list broke. Look at the capture.
10. **Desktop scrollbars eat 15px of a "390px" capture.** Hide them in the
    harness; use a device-emulated session for touch.
11. **Check the sign-in before a capture run:** `playwright-cli list` and a
    200 from an authenticated GET.
12. **Git Bash heredocs break on curly apostrophes.** Write long text with
    the file tool. Bare `python` on this machine may hang (Store stub): use
    `.venv/Scripts/python.exe`.
13. **Disk:** C: filled to 0 MB mid-review. Put scratch captures and evidence
    on D:, and check free space before an 80-capture run.
14. **Labels are tested, and that is good:** copy assertions force each
    wording change to be deliberate.
15. **Real data shows what fixtures don't.** The InstaPay share-text problem
    was found by reading production's data read-only, not in the gallery.
    Where allowed, look at real values (never copy personal data out).
