
## What Claude learned building this (for comparison with yours)

These are my notes from all eight milestones, written so you can compare them with your own lines above.

### Milestone 0: Setup and smoke test
1. Check the basics before blaming the code. The first failure was a port: LM Studio ran on 1235, not the usual 1234.
2. Schema-constrained JSON (`json_action`) made a small local model reliable at picking tools: 9 of 10 on the first smoke test.
3. A thinking model spends hidden tokens before it answers. With a 512-token limit, the reply was cut off with nothing visible, which looked like a bug.
4. A 10-case smoke test on day one gave a number to compare every later change against.
5. Pinning package versions and the lock file meant your Mac and my test machine ran the same code.

### Milestone 1: Synthetic data
1. Planting known cases (CLM-10482, M-00217, M-00250) in seeded data is what made every later test possible. You can't check an answer you don't already know.
2. A fixed "today" (2026-11-15) keeps date logic, like "X-ray within 60 days", the same on every run.
3. Building the policy documents from the same tables as the database keeps the two from contradicting each other.
4. Marking every row and document as synthetic is cheap, and it makes the boundary obvious to anyone reading.
5. A built-in check script (row counts, planted cases) catches a broken generator at once.

### Milestone 2: Tools
1. Typed inputs (Pydantic) turn the model's mistakes into clear error messages it can read and fix, instead of crashes.
2. Returning `{"error": ...}` instead of raising let the agent recover from a bad ID on its own.
3. Unit tests for the tools need no model, so they run in seconds and pin down the data layer.
4. A tool's output shapes what the model can reason about. Adding the procedure description to `search_claims` (milestone 5) is what let the prior auth agent find the PT visits.
5. Tests that assumed exact row counts broke as soon as real use added rows. Count before and after instead.

### Milestone 3: One agent, end to end
1. The trace file was the most useful debugging tool in the whole project. Almost every fix started from a trace line you pasted.
2. Prompts need to say what not to do. The first claims answer answered questions you hadn't asked, until the prompt said "answer only the question asked".
3. A step limit (4 tool calls) and a safe fallback answer keep a confused agent from looping forever.
4. Catching a cut-off reply and asking again turned a crash into a slow step.
5. "It runs" and "it's right" are different checks. Demo story 1 needed both.

### Milestone 4: RAG and benefits agent
1. The embedding model needed its own task prefixes ("search_document: ", "search_query: "). Without them, retrieval quality drops quietly.
2. Splitting documents by section headings gave citations a person can check, like `silver_coverage_summary.md > Physical therapy`.
3. "Answer only from the passages" is a rule a small model breaks. The facials question got an answer from outside knowledge, which is why it became eval case b06.
4. A passage about another plan can look relevant. The prompt had to say "check the document name".
5. Keeping embeddings local (LM Studio plus Chroma on disk) kept the whole pipeline offline.

### Milestone 5: Supervisor and prior auth with approval
1. Routing with structured output and no tools is simpler and more reliable than one big agent with nine tools.
2. LangGraph's `interrupt()` plus a SQLite checkpoint means an approval can wait, even across a restart. Resuming re-runs the paused node from the top, so nothing with a side effect may come before the interrupt.
3. The gated tool never runs inside the agent loop. The model can only propose it.
4. Small input details matter for a person at a terminal: "approve Nick" on one line had to work.
5. The design's tool table and its text disagreed (the prior auth agent needed `search_claims`). Reading the whole design, and asking, settled it.

### Milestone 6: Reviewer, memory and UI
1. Thinking is a dial, not a switch. With thinking on, the reviewer ran out of room; with it off, the reviewer misjudged. LM Studio's `reasoning_effort: "none"` was the control that worked, and asking the model to "think briefly" did not.
2. At temperature 0, asking again the same way gets the same failure. Retries must change something: the prompt, or the thinking setting.
3. A model reviewer needs exact rules, with examples of what passes. Without them it rejected correct drafts, such as a date written another way or a status repeated from the database.
4. Let code do what code is always right at. Looking up every date and ID in the evidence fixed the reviewer's false rejections, and left the judgement to the model.
5. Memory notes written by plain rules from what actually happened can't be made up. The note header also had to tell the agent the notes are records it may use.

### Milestone 7: Evals, demo and write-up
1. Equal totals can hide different failures. Thinking on and off both scored 14 of 15 facts, but only thinking off missed the prior auth story.
2. A setting can be chosen per part. Thinking stays on where it helped (prior auth) and is off where it only cost time.
3. Plain-code scoring is fast and repeatable, but it is strict about wording. A miss means "read this answer", not automatically "the answer was wrong".
4. Guardrails that run before the model (masking, injection flags) are cheap, fast and testable without a model.
5. The real numbers beat my estimate. I guessed 1 to 3 minutes per question, and the runs took 11 to 29 seconds on average. Measure, don't guess.
