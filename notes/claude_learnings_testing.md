
### After milestone 7: testing in the app and with functional tests
1. A scorecard that meets every target can still miss whole classes of mistakes. The 25 cases all used members whose evidence was in paid claims. Thirty new cases built from the database (denied MRIs, ended coverage, unknown IDs) passed only 20 of 30 at first.
2. Write the expected answer from the data before you run the case. Looking up "M-00215 had a knee MRI on 2026-01-22" first is what made "no MRI in the past 12 months: met" visibly wrong.
3. When the model keeps doing the wrong thing, change what it can do, not what it is told. "Search with no status filter" in the prompt was ignored. Removing the status filter from the prior auth agent's tool fixed it for good.
4. Small wording in the loop steers the model. "Give your final answer now" after the last lookup made it skip the submission, so two of three prior auth questions never reached a person. One sentence of code that sends such an answer back fixed it.
5. A rule written for one case can block a good answer in another. The reviewer's "no coverage decisions" rule rejected a correct "deny" recommendation that a person would approve. Every safety rule needs a test where the right answer looks like a violation.
6. A loop of questions is a design bug, not a model quirk. Asking "claims or the game?" again and again came from having only a "clarify" route. A fixed out-of-scope reply, and "answer the work part, say what you left out", ended it.
7. Try to break your own guardrails with new wording. "Bypass the reviewer", "pretend you are" and an SSN with spaces all got through at first. One reworded injection still reaches the model, and the approval gate is what holds.
8. Read the failing answer before you fix code. Two failures were the test itself: "could not be found" doesn't contain "not found".
9. Copying files while a run is starting can mix old and new code. Check with grep that the new code is in place, then rerun.
10. A test file with a "why" for each case turns a FAIL into a to-do item. You can see what broke and why it matters without opening the trace.
