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
16. **Read a rule's history before proposing to change it** (Targets). The
    recommendation to measure pace per kind was approved before the code
    showed the owner's own *any mix* rule; it had to be re-asked. The tests
    and ADRs say who decided what.
17. **Validate what the save sends, not what the screen shows** (Targets).
    On a screen with modes or filters, a hidden box still goes in the save:
    a mistyped requirement in the other mode was sent as 0.
18. **A status is not a role** (Targets). New affiliates start *pending*
    until their code is verified; "hide pending" would have hidden models
    being onboarded. Check the lifecycle before filtering on a status.
19. **Use your own disposable test DB when another session may be testing**
    (Targets). Two runs on `hba_platform_test` deadlocked on TRUNCATE. And
    give `run-suite.sh` its own `OUT_DIR` and `REV`: its log is shared.
20. **Polish is not the job; the job is whether each feature earns its place**
    (Targets, second pass). The first pass polished *Confirm* (hints, ticks,
    a take-back panel) without asking what it did: it changed pay in one
    case, the person who recorded the counts could confirm them a second
    later, and the next weekly count wiped it. The owner asked; the owner
    removed it (ADR 0081). Step 4 now asks this of every action.
21. **When a check goes, the save becomes the check** (Targets). With no
    confirm step, a typed count releases money by itself, so the save lists
    every change old → new, and what it turns (*Target met → Below target ·
    her guaranteed minimum no longer applies*), before anything is written.
22. **ADR numbers race.** Another branch took 0079 while this one was open.
    Check `git ls-tree origin/main docs/adr/` before numbering, and again
    before shipping.
