# Milestone 6: Reviewer, memory and UI

**Goal:** every answer is checked by a compliance reviewer before you see it, the copilot remembers the conversation and short notes about members, and you can use it all in a web page with Approve and Reject buttons and a trace panel. **Check:** "Draft the appeal for that claim" works as a follow-up, and notes about a member come back in a new session.

## 1. The graph now

```text
supervisor ──> claims ─────┐
           ──> benefits ───┼──> reviewer ──(passed)──> approval (only if a submission is proposed) ──> remember ──> end
           ──> prior_auth ─┘       │                                                                    ^
           ──> clarify ────────────┼──(failed once)──> the same specialist again, told the reasons      │
                                   └──(failed twice)──> "needs human review" ───────────────────────────┘
```

- **Reviewer.** It calls no tools. It reads the question, the draft and the evidence (the tool results, plus any saved notes the agent was shown) and fills in `ReviewVerdict` (`passed`, `reasons`) through `decide_structured`, so its reply always parses. Three rules from the design: every fact traces to evidence, no coverage decision stated as final, no medical advice. On a first fail, the same specialist tries once more. It sees the reasons and the tool results it already has, so it doesn't repeat its lookups. Conclusions worked out from evidence (counting visits, weeks between dates, marking a criterion met) are allowed; the reviewer doesn't redo those judgements, a person does. On a second fail, you get "This answer needs human review" with the reasons, and a proposed prior auth is dropped, so a failed draft can never be submitted.
- **Remember.** A new last step on every question. It saves member notes from what really happened, by plain rules in code (a letter that was saved, a prior auth that was approved or rejected), never from the model's own words. It also adds the turn to the session history.
- **Sessions.** In milestone 5 each question was its own run. Now a **session** is one LangGraph thread, and each question inside it is a run with its own trace. The state keeps two kinds of fields: session fields that last (the last 6 turns, a summary of older ones, the member and claim in focus) and per-question fields that are cleared when a new question starts.

## 2. Memory, in one table

| Kind | What it holds | Where it lives | How long |
| --- | --- | --- | --- |
| Working memory | The last 6 questions and answers, a short summary of older turns, the member and claim IDs in focus | The LangGraph state, saved in `data/checkpoints.db` | One session |
| Member notes | Short facts like `appeal letter drafted for CLM-10482 on 2026-11-15` | New table `memory_notes` in `data/payer.db` | Across sessions |
| Analyst preferences | Things you type in the app, like "Keep answers to 3 sentences" | Same table | Across sessions |

You can inspect all of it: the sidebar of the app shows the IDs in focus, the member's notes and your preferences, and `sqlite3 data/payer.db "SELECT * FROM memory_notes;"` shows the raw table. The agents are told that memory is context only; facts still come from tools.

## 3. What's new

| File | What it does, in plain words |
| --- | --- |
| `src/copilot/agents/reviewer.py` | **New. The compliance reviewer** described above. Before the model judges, plain code (`check_facts`) looks up every ID, code, date and $ amount in the draft in the full evidence, and hands the model two lists: found and not found. The model trusts the found list and judges the rest. Its verdict is written to the trace as its own step. The evidence it reads is cut at 6,000 characters to stay inside the 8,192-token context. If its own reply is cut off (its hidden thinking ran too long), it gets one more try with a note to think briefly. If that fails too, you get "needs human review" with the unchecked draft, and the specialist is not asked to redo work that was never judged. |
| `src/copilot/memory.py` | **New. All memory code:** save and read notes, decide which notes a run earns (`notes_from_run`), add a turn to the history (when there are more than 6, the oldest is folded into the summary by one model call), and build the context text the agents see. |
| `app/streamlit_app.py` | **New. The web app.** Chat on the left, trace on the right (one expandable box per step: arguments, tool result, raw model output, prompt, tokens). A sidebar with the session, the IDs in focus, member notes and your preferences. A "synthetic data only" banner. When a prior auth is proposed, an approval box appears with the recommendation and rationale you can **edit**, your name, and **Approve** / **Reject** buttons. The chat box is locked until you decide. |
| `.streamlit/config.toml` | **New.** Turns off Streamlit's usage statistics so nothing leaves your Mac, and stops it opening a browser by itself. |
| `src/copilot/graph.py` | **Rewritten** for the new nodes (reviewer, remember), sessions, and edits at approval. New terminal option `--session NAME`. `--resume` now takes the session name. |
| `src/copilot/agents/supervisor.py` | Reads the session context, so "that claim" means the claim in focus. One more example in its prompt. |
| `src/copilot/agents/loop.py` | Step numbers carry on after earlier steps of the same run, so a retry after the reviewer doesn't reuse step numbers. **If the model's thinking uses up the whole reply budget, that one step is retried with thinking off** (asking again the same way just ran out again, up to 4 times in a row at over 2 minutes each). The next step may think again. The trace marks such a step "thinking off after a cut-off". |
| `src/copilot/llm.py` | New `complete_text()`: a plain text reply, used only for the session summary. It still goes through the one adapter. New **thinking switch**: each call says which role it is for (agents, supervisor, reviewer, summary), and `config.yaml` says whether that role may think. Thinking off sends `reasoning_effort: "none"`, which your LM Studio test showed cuts a tiny question from 6.9s to 0.9s. |
| `config.yaml` | `max_tokens: 4096`, `timeout_seconds: 300`, and the new `thinking:` settings: on for the three agents, off for the supervisor, the reviewer and the summary. |
| `src/copilot/schemas.py` | New `ReviewVerdict`. `CopilotState` gained the session fields and `review`, `review_attempts`, `submission`. |
| `src/copilot/tracing.py` | One-line fix: steps with no timing (the approval steps) print as 0.0s instead of crashing. |
| `tests/test_tools.py` | Two new tests: a note is saved and read back, and notes come only from what really happened (a failed letter earns no note; an approval earns one with the approver's name). |

Four choices to know about:

- **For prior auth, the reviewer runs before the approval box**, not after. That way you see the reviewer's verdict when you decide, and a draft that failed review twice never reaches the approval box. The design's graph shows supervisor, specialist, reviewer, then approval, so I read it this way.
- **"Edit" is done as editable fields** (recommendation and rationale) in the approval box, then Approve. The trace records both the proposed and the final version, and the answer says "approved with edits". The member ID and procedure code are not editable, because changing those would be a different request.
- **Guardrails are not in this milestone.** The design puts `guardrails.py` (blocking prompt injection and requests for real PHI) next to the evals, so it comes in milestone 7.
- **Thinking is off for the supervisor, the reviewer and the summary, and on for the three agents.** With thinking on, the reviewer filled its whole 4,096-token budget on story 3 and never wrote a verdict, even when told to think briefly. The agents keep thinking because they do the reasoning over evidence. Each is one line in `config.yaml`, and the milestone 7 evals will show whether the settings hurt accuracy.
- **The memory tests went into `tests/test_tools.py`** rather than a new test file, because they use the same database setup.

## 4. Commands

Run each line on its own, with LM Studio running and both models loaded.

```bash
cd ~/Projects/payer-copilot
uv run pytest tests/test_tools.py
```

Expected: `30 passed`.

**Check part 1: a follow-up in the same session.** Ask story 1 in a session called `demo`:

```bash
uv run python -m copilot.graph --session demo "Why was claim CLM-10482 denied and what can the member do?"
```

Expected: the steps, now including a `[reviewer]` step near the end, then:

```text
=== Answer (route: claims, reviewer: passed) ===
...CO-197... no prior authorization... appeal...
Sources: ...
```

Now the follow-up, in the same session. It doesn't name the claim:

```bash
uv run python -m copilot.graph --session demo "Draft the appeal letter for that claim."
```

Expected: step 0 (the supervisor) shows `claim_id: CLM-10482` even though you didn't type it, the claims agent calls `draft_letter`, and the answer says the appeal letter was saved in `outbox/`. Check the letter and the note:

```bash
ls outbox
sqlite3 data/payer.db "SELECT * FROM memory_notes;"
```

Expected: the file `CLM-10482_appeal.md`, and one row like `1|member|M-00142|appeal letter drafted for CLM-10482 on 2026-11-15|2026-11-15|1`.

**Check part 2: notes come back in a new session.** A different session name means empty working memory:

```bash
uv run python -m copilot.graph --session fresh "Has anything been done on claim CLM-10482 already?"
```

Expected: the answer mentions that an appeal letter was already drafted for CLM-10482 on 2026-11-15. That fact came from the saved note, not from this session's history, which is empty. If you open the trace (`uv run python -m copilot.tracing`), the claims agent's prompt shows a "Notes from earlier sessions about this member" section.

**The web app:**

```bash
uv run streamlit run app/streamlit_app.py
```

Expected: `You can now view your Streamlit app in your browser.` and `Local URL: http://localhost:8501`. Open that address in your browser. To stop the app later, press Ctrl+C in the Terminal.

In the app, try:

1. Story 3: `Member M-00217 needs a knee MRI. Is prior auth required and do they meet criteria?` After a few minutes the approval box appears and the chat box is locked. Click **Approve** without a name first: you should get "Please type your name first." Then change the rationale a little, type your name and click **Approve**. Expected: "Submitted to the auth queue as PA-0062 (status pending), approved with edits by Nick." (PA-0062, because you already wrote PA-0061 in milestone 5.) The sidebar now shows a note about M-00217.
2. Open a few step boxes in the trace on the right: the reviewer's step shows `passed` and its reasons; the approval step shows `edited: true` and both versions.
3. Add a preference in the sidebar, for example `Keep answers to 3 sentences`, and click **Save preference**.
4. Click **New session**, ask `What has been done for member M-00217?`, and check that the sidebar and the answer show the prior auth note.

**The check passes** when the follow-up drafts the letter for CLM-10482 without you naming it, and the new session sees the note. Send me the output of the two `--session` commands and tell me what happened in the app, either way.

To reset everything (database, notes, letters) at any time: `uv run python data/generate.py`, then `rm -rf outbox data/checkpoints.db`.

## 5. Check your understanding

1. The reviewer rejects a draft twice. What do you see instead of the draft, and why can a proposed prior auth never reach the approval box in that case?
2. Where does "the claim in focus" live, and where does "appeal letter drafted for CLM-10482" live? Why does one disappear in a new session and the other doesn't?
3. Notes are written by plain rules in `notes_from_run`, not by asking the model "what should I remember?". What could go wrong if the model wrote its own notes?

Then add your 5 lines to `LEARNINGS.md`.

## 6. Full contents of new and changed files

### `src/copilot/agents/reviewer.py`

```python
"""The compliance reviewer: checks a specialist's draft against its evidence.

It calls no tools. It returns a ReviewVerdict (passed, reasons) through
structured output. Three rules, from the design:
1. Every factual claim traces to a tool result or a cited passage.
2. No coverage approval or denial is stated as final.
3. No medical advice.

Before the model judges, plain code looks up every ID, code, date and amount
in the draft in the full evidence (check_facts). Finding an exact date in a
long list is a lookup code always gets right and a small model often misses.
The model then judges only what code could not find, plus rules 2 and 3.
"""

import json
import re
import time
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage

from copilot import tracing
from copilot.common import today
from copilot.llm import ActionError, decide_structured
from copilot.schemas import ReviewVerdict

MAX_EVIDENCE_CHARS = 6000  # keeps the reviewer's prompt inside the context budget
MAX_ATTEMPTS = 2  # if the reviewer's own reply is invalid, it gets one more try
RETRY_NOTE = ("Your previous reply was cut off or invalid. Reply with the JSON verdict only, "
              "with at most one short reason per problem.")

# The kinds of facts code can look up exactly.
ID_PATTERN = re.compile(r"\b(?:CLM-\d+|M-\d+|PA-\d+|[A-Z]{2}-\d+|\d{5})\b")
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
WORD_DATE = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
                       r" \d{1,2}, \d{4}\b")
AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def check_facts(draft: str, sources: str) -> tuple[list[str], list[str]]:
    """Look up each ID, code, date and $ amount from the draft in the sources.

    Returns (found, not_found). Dates written in words ("August 4, 2026")
    are compared as 2026-08-04, and $1,240.00 matches 1240.0.
    """
    numbers = {float(n) for n in NUMBER.findall(sources.replace(",", ""))}
    facts: list[tuple[str, bool]] = []
    for fact in ID_PATTERN.findall(draft) + ISO_DATE.findall(draft):
        facts.append((fact, fact in sources))
    for fact in WORD_DATE.findall(draft):
        iso = datetime.strptime(fact, "%B %d, %Y").date().isoformat()
        facts.append((fact, iso in sources))
    for match in AMOUNT.finditer(draft):
        facts.append((match.group(0), float(match.group(1).replace(",", "")) in numbers))
    found = list(dict.fromkeys(f for f, ok in facts if ok))  # dict.fromkeys drops repeats, keeps order
    not_found = list(dict.fromkeys(f for f, ok in facts if not ok))
    return found, not_found


SYSTEM_PROMPT = """You are the compliance reviewer for Acme Health Plan's operations copilot. You check a draft answer before an analyst sees it.

Check the draft against exactly three rules:
1. Every fact in the draft (amounts, dates, codes, limits, statuses, names) appears in the evidence. General wording and suggested next steps from the evidence are fine. A fact that is not in the evidence breaks this rule.
   Code has already looked up every ID, code, date and $ amount in the draft. Trust its two lists: never fail a fact on the "found" list. A fact on the "not found" list breaks this rule, unless the draft clearly works it out from the evidence (such as a total, or a date 60 days before today). Check other facts (names, statuses, limits, counts) against the evidence yourself.
   Conclusions worked out from evidence are fine when the facts they use are in the evidence: counting visits, the weeks between two dates, whether a date is within 60 days, or marking a criterion met, not met or unknown. Do not fail a draft over a judgement call; a person reviews those. But do fail a conclusion that the evidence contradicts, such as a count, a date range or a "not found" that leaves out records shown in the evidence.
   The same fact written another way counts as present: "August 4, 2026" is the same as "2026-08-04", and "$1,240" is the same as 1240.0.
2. The draft never makes a new coverage decision of its own, such as "this claim will be paid", "the member's MRI will be covered" or "this request is approved". Repeating the evidence is fine: "the claim was denied" or "these claims were paid" repeats the database, and "the Silver plan covers 30 PT visits" repeats a policy document. A recommendation for a person to review is also fine.
3. The draft gives no medical advice.

Saying the documents don't cover something is fine; it is not a fact that needs evidence.
Pass the draft if it follows all three rules. If it fails, give one short reason per problem, naming the rule and the words at fault.
"""


def review(question: str, draft: str, evidence: list[dict], run_id: str,
           notes: list[str] | None = None) -> ReviewVerdict:
    """Check one draft. Returns the verdict and writes it to the trace.

    notes are the saved member notes the specialist was shown. They count as
    evidence too, so "an appeal letter was already drafted" can pass.
    """
    evidence_text = json.dumps([{"tool": e["tool"], "result": e["result"]} for e in evidence])
    if len(evidence_text) > MAX_EVIDENCE_CHARS:
        evidence_text = evidence_text[:MAX_EVIDENCE_CHARS] + " ...(cut)"
    content = (f"Analyst's question:\n{question}\n\nDraft answer:\n{draft}\n\n"
               f"Evidence (tool results):\n{evidence_text or 'none'}")
    if notes:
        content += "\n\nEvidence (saved notes from earlier sessions):\n- " + "\n- ".join(notes)
    # The lookup uses the full evidence, not the cut text, plus the question and today's date.
    sources = " ".join([json.dumps(evidence), *(notes or []), question, today().isoformat()])
    found, not_found = check_facts(draft, sources)
    content += (f"\n\nChecked by code. Found in the evidence: {', '.join(found) or 'none'}."
                f"\nNot found in the evidence: {', '.join(not_found) or 'none'}.")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        step = max((s["step"] for s in tracing.read_run(run_id)), default=0) + 1
        start = time.perf_counter()
        # On the retry, the same prompt at temperature 0 would give the same
        # reply, so the retry note says what went wrong.
        text = content if attempt == 1 else f"{content}\n\n{RETRY_NOTE}"
        messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=text)]
        try:
            result = decide_structured(messages, ReviewVerdict, "reviewer")
        except ActionError as e:
            tracing.write_step(run_id, "reviewer", step, prompt=[{"role": "human", "content": text}],
                               raw_output=e.raw, error=str(e), latency_s=round(time.perf_counter() - start, 2))
            if attempt == MAX_ATTEMPTS:
                raise
            continue
        tracing.write_step(run_id, "reviewer", step, prompt=[{"role": "human", "content": text}],
                           raw_output=result.raw, action="review", arguments=result.data,
                           input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                           latency_s=result.latency_s)
        return ReviewVerdict.model_validate(result.data)
    raise AssertionError("unreachable")
```

### `src/copilot/memory.py`

```python
"""Memory: what the copilot remembers, and where you can inspect it.

- Working memory (one session): the last 6 question-and-answer turns plus a
  running summary of older ones, and the member and claim IDs in focus. It
  lives in the LangGraph state, so it is saved in data/checkpoints.db.
- Long-term memory (across sessions): short notes in the memory_notes table
  of payer.db. Notes about a member ("appeal letter drafted for CLM-10482
  on 2026-11-15") are written by an explicit step at the end of a run, from
  what the tools actually did, never by the model deciding freely. Analyst
  preferences are typed in by the analyst in the app.
"""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from copilot.common import connect, today
from copilot.llm import complete_text

MAX_TURNS = 6
MAX_NOTES = 5

TABLE = """CREATE TABLE IF NOT EXISTS memory_notes (
    note_id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT CHECK (kind IN ('member', 'analyst')),
    member_id TEXT,
    note TEXT,
    created_at TEXT,
    is_synthetic INTEGER NOT NULL DEFAULT 1)"""


# ---------- long-term notes ----------


def add_note(kind: str, note: str, member_id: str | None = None) -> None:
    """Save one note. kind is 'member' (with a member_id) or 'analyst'."""
    with connect() as con:
        con.execute(TABLE)
        con.execute("INSERT INTO memory_notes (kind, member_id, note, created_at) VALUES (?, ?, ?, ?)",
                    (kind, member_id, note, today().isoformat()))


def member_notes(member_id: str | None) -> list[str]:
    """The newest notes about one member."""
    if not member_id:
        return []
    with connect() as con:
        con.execute(TABLE)
        rows = con.execute("SELECT note FROM memory_notes WHERE kind = 'member' AND member_id = ? "
                           "ORDER BY note_id DESC LIMIT ?", (member_id, MAX_NOTES)).fetchall()
    return [r["note"] for r in rows]


def analyst_preferences() -> list[str]:
    """The analyst's saved preferences, newest first."""
    with connect() as con:
        con.execute(TABLE)
        rows = con.execute("SELECT note FROM memory_notes WHERE kind = 'analyst' "
                           "ORDER BY note_id DESC LIMIT ?", (MAX_NOTES,)).fetchall()
    return [r["note"] for r in rows]


def notes_from_run(state: dict[str, Any]) -> list[tuple[str, str]]:
    """Decide which member notes this run earns, as (member_id, note) pairs.

    Plain rules on what really happened, so a note can't be invented:
    a letter that was saved, and a prior auth that was approved or rejected.
    """
    notes, day = [], today().isoformat()
    for e in state.get("evidence") or []:
        if e["tool"] == "draft_letter" and "error" not in e["result"]:
            claim_id = e["result"]["claim_id"]
            with connect() as con:
                row = con.execute("SELECT member_id FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
            if row:
                notes.append((row["member_id"], f"{e['result']['letter_type']} letter drafted for {claim_id} on {day}"))
    approval, submission = state.get("approval"), state.get("submission")
    if approval and approval.get("arguments"):
        args = approval["arguments"]
        if approval["decision"] == "approve" and submission and "error" not in submission:
            notes.append((args["member_id"], f"prior auth {submission['auth_id']} for {args['procedure_code']} "
                          f"submitted ({args['recommendation']}), approved by {approval['approver']} on {day}"))
        elif approval["decision"] == "reject":
            notes.append((args["member_id"], f"prior auth for {args['procedure_code']} "
                          f"({args['recommendation']}) rejected by {approval['approver']} on {day}"))
    return notes


# ---------- working memory ----------


def add_turn(history: list[dict[str, str]], summary: str, question: str,
             answer: str) -> tuple[list[dict[str, str]], str]:
    """Add one turn. If more than MAX_TURNS are kept, fold the oldest into the summary."""
    history = [*history, {"question": question, "answer": answer}]
    if len(history) <= MAX_TURNS:
        return history, summary
    oldest, history = history[0], history[1:]
    prompt = [SystemMessage(content="Update a running summary of a claims analyst's session. Keep IDs, "
                                    "amounts and decisions. At most 80 words. Reply with the summary only."),
              HumanMessage(content=f"Summary so far: {summary or '(none)'}\n\n"
                                   f"Turn to add:\nQ: {oldest['question']}\nA: {oldest['answer']}")]
    return history, complete_text(prompt).strip()


def context_block(state: dict[str, Any]) -> str:
    """What a specialist should know from memory, as text added to its question.

    Earlier turns are context only; the agent must still get facts from tools.
    """
    parts = []
    if state.get("summary"):
        parts.append(f"Summary of earlier conversation: {state['summary']}")
    for turn in (state.get("history") or [])[-3:]:  # the last 3 turns keep the prompt short
        parts.append(f"Earlier question: {turn['question']}\nEarlier answer: {turn['answer'][:400]}")
    ids = [f"member {state['member_id']}" if state.get("member_id") else "",
           f"claim {state['claim_id']}" if state.get("claim_id") else ""]
    ids = [i for i in ids if i]
    if ids:
        parts.append(f"IDs in focus: {', '.join(ids)}.")
    notes = member_notes(state.get("member_id"))
    if notes:
        parts.append("Notes from earlier sessions about this member (saved records of actions already taken; "
                     "include them when asked what has been done):\n- " + "\n- ".join(notes))
    prefs = analyst_preferences()
    if prefs:
        parts.append("Analyst preferences:\n- " + "\n- ".join(prefs))
    return "\n\n".join(parts)
```

### `src/copilot/graph.py`

```python
"""LangGraph wiring: one entry point for every request.

    supervisor --> claims -----\\
               --> benefits ----> reviewer --(pass)--> approval (if a submission is proposed) --> remember --> end
               --> prior_auth -/       |                                                          ^
               --> clarify ------------+--(fail once)--> back to the same specialist, with the reasons
                                       +--(fail twice)--> "needs human review" ------------------/

Each session is one LangGraph thread. LangGraph saves the state in a SQLite
checkpoint after every step. That gives three things: a run paused for
approval can resume later, even after a restart; a follow-up question sees
the earlier turns and the IDs in focus; and you can inspect it all.

    uv run python -m copilot.graph "Why was claim CLM-10482 denied and what can the member do?"
    uv run python -m copilot.graph --session demo "Why was claim CLM-10482 denied?"
    uv run python -m copilot.graph --session demo "Draft the appeal letter for that claim."
    uv run python -m copilot.graph --resume <session_id>
"""

import json
import sqlite3
import sys
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt

from copilot import memory, tracing
from copilot.agents import benefits, claims, prior_auth
from copilot.agents.reviewer import review
from copilot.agents.supervisor import route
from copilot.common import checkpoint_db, connect
from copilot.llm import ActionError
from copilot.schemas import AgentResult, CopilotState
from copilot.tools import run_tool

MAX_REVIEWS = 2  # the first draft, plus one retry
MAX_EVIDENCE_CHARS = 6000  # earlier tool results passed to a retry, cut to fit the context
NEEDS_HUMAN = ("This answer needs human review. The compliance reviewer found problems twice:\n- {reasons}\n"
               "The evidence gathered is in the trace.")
REVIEWER_FAILED = ("This answer needs human review. The compliance reviewer couldn't finish checking it, "
                   "so nothing was submitted. The unchecked draft was:\n\n{draft}")


def new_question(question: str, run_id: str) -> dict:
    """The input for a new question: sets the question and clears last question's results.
    Session fields (history, summary, IDs in focus) are left as they are."""
    return {"run_id": run_id, "question": question, "route": "", "answer": "", "evidence": [],
            "tool_calls": 0, "review": None, "review_attempts": 0, "pending_approval": None,
            "approval": None, "submission": None}


# ---------- nodes: each takes the state and returns the fields it changes ----------


def supervisor_node(state: CopilotState) -> dict:
    """Pick a specialist and update the IDs in focus."""
    context = memory.context_block({k: state.get(k) for k in ("member_id", "claim_id", "history")})
    try:
        decision = route(state["question"], state["run_id"], context)
    except ActionError:
        return {"route": "clarify", "answer": "Sorry, I couldn't work out what you need. Could you rephrase?"}
    member_id = decision.member_id or None
    claim_id = decision.claim_id or None
    update = {"route": decision.route}
    if member_id and member_id != state.get("member_id"):
        # A different member: their claim, if any, replaces the old one in focus.
        update["member_id"], update["claim_id"] = member_id, claim_id
    elif claim_id:
        update["claim_id"] = claim_id
    if update.get("claim_id"):
        # A claim belongs to one member. Take that member from the database,
        # not from the model, and put them in focus so their notes load.
        update["member_id"] = _member_for_claim(update["claim_id"]) or update.get("member_id")
    if decision.route == "clarify":
        update["answer"] = decision.clarifying_question or "Could you tell me a bit more about what you need?"
    return update


def _member_for_claim(claim_id: str) -> str | None:
    """The member a claim belongs to, from the database (None if unknown)."""
    with connect() as con:
        row = con.execute("SELECT member_id FROM claims WHERE claim_id = ?", (claim_id.upper(),)).fetchone()
    return row["member_id"] if row else None


def _specialist_input(state: CopilotState) -> str:
    """The question, plus memory, plus the reviewer's reasons on a retry."""
    text = state["question"]
    context = memory.context_block(state)
    if context:
        text += f"\n\n--- Context from this session (facts still come from tools) ---\n{context}"
    if _is_retry(state):
        evidence = json.dumps([{"tool": e["tool"], "arguments": e["arguments"], "result": e["result"]}
                               for e in state.get("evidence", [])])
        if len(evidence) > MAX_EVIDENCE_CHARS:
            evidence = evidence[:MAX_EVIDENCE_CHARS] + " ...(cut)"
        text += ("\n\n--- Tool results from your previous attempt (still correct; don't look them up again) ---\n"
                 + evidence
                 + "\n\n--- A compliance reviewer rejected your previous draft ---\n- "
                 + "\n- ".join(state["review"]["reasons"]) + "\nFix these problems in your new answer.")
    return text


def _is_retry(state: CopilotState) -> bool:
    """True when the reviewer sent the last draft back."""
    verdict = state.get("review")
    return bool(verdict) and not verdict["passed"]


def _from_result(result: AgentResult) -> dict:
    """The state fields a specialist's result fills in."""
    pending = result.pending_action.model_dump() if result.pending_action else None
    return {"answer": result.answer, "evidence": [e.model_dump() for e in result.evidence],
            "tool_calls": result.tool_calls, "pending_approval": pending}


def _run_specialist(agent: Any, state: CopilotState) -> dict:
    """Run one specialist. On a retry, it keeps the evidence it already has,
    so it doesn't repeat its lookups and the reviewer still sees all of it."""
    update = _from_result(agent.run(_specialist_input(state), state["run_id"]))
    if _is_retry(state):
        earlier = state.get("evidence", [])
        update["evidence"] = earlier + [e for e in update["evidence"] if e not in earlier]  # no repeats
    return update


def claims_node(state: CopilotState) -> dict:
    return _run_specialist(claims, state)


def benefits_node(state: CopilotState) -> dict:
    return _run_specialist(benefits, state)


def prior_auth_node(state: CopilotState) -> dict:
    return _run_specialist(prior_auth, state)


def reviewer_node(state: CopilotState) -> dict:
    """Check the draft. On a second failure, replace it with a safe message."""
    attempts = state.get("review_attempts", 0) + 1
    try:
        verdict = review(state["question"], state["answer"], state.get("evidence", []), state["run_id"],
                         memory.member_notes(state.get("member_id")))
        verdict_dict = verdict.model_dump()
    except ActionError as e:
        # The reviewer couldn't finish (twice). The draft was never judged, so
        # asking the specialist to redo it would not help: stop and ask a person.
        return {"review": {"passed": False, "reasons": [f"The reviewer couldn't finish: {e}"]},
                "review_attempts": MAX_REVIEWS, "pending_approval": None,
                "answer": REVIEWER_FAILED.format(draft=state["answer"])}
    update = {"review": verdict_dict, "review_attempts": attempts}
    if not verdict_dict["passed"] and attempts >= MAX_REVIEWS:
        update["answer"] = NEEDS_HUMAN.format(reasons="\n- ".join(verdict_dict["reasons"]))
        update["pending_approval"] = None  # never submit a draft that failed review
    return update


def after_review(state: CopilotState) -> str:
    """Where to go after the reviewer."""
    if state["review"]["passed"]:
        return "approval" if state.get("pending_approval") else "remember"
    if state["review_attempts"] < MAX_REVIEWS:
        return state["route"]  # one more try by the same specialist
    return "remember"


def approval_node(state: CopilotState) -> dict:
    """Pause for a person, then submit or not.

    interrupt() stops the run here. When the run resumes, LangGraph starts
    this node again from the top and interrupt() returns the person's
    decision. So nothing with a side effect may come before it.
    """
    pending = state["pending_approval"]
    decision = interrupt({"question": state["question"], "draft": state["answer"],
                          "action": pending, "review": state.get("review")})
    run_id, approver = state["run_id"], decision["approver"]
    arguments = decision.get("arguments") or pending["arguments"]  # the person may have edited them
    edited = arguments != pending["arguments"]
    step = max(s["step"] for s in tracing.read_run(run_id)) + 1
    tracing.write_step(run_id, "approval", step, action=decision["decision"],
                       arguments={"approver": approver, "edited": edited, "final": arguments,
                                  "proposed": pending["arguments"]})
    approval = {"decision": decision["decision"], "approver": approver, "arguments": arguments, "edited": edited}
    if decision["decision"] != "approve":
        return {"approval": approval, "pending_approval": None,
                "answer": f"{state['answer']}\n\nNot submitted: rejected by {approver}."}

    result = run_tool(pending["action"], arguments)
    tracing.write_step(run_id, "approval", step + 1, action=pending["action"], arguments=arguments,
                       tool_result=result, note=f"approved by {approver}")
    if "error" in result:
        answer = f"{state['answer']}\n\nApproved by {approver}, but the submission failed: {result['error']}"
    else:
        note = " with edits" if edited else ""
        answer = (f"{state['answer']}\n\nSubmitted to the auth queue as {result['auth_id']} "
                  f"(status {result['status']}), approved{note} by {approver}.")
    return {"approval": approval, "submission": result, "pending_approval": None, "answer": answer}


def remember_node(state: CopilotState) -> dict:
    """The explicit memory step at the end of every question: save member
    notes from what really happened, and add the turn to the session history."""
    for member_id, note in memory.notes_from_run(state):
        memory.add_note("member", note, member_id)
    history, summary = memory.add_turn(state.get("history") or [], state.get("summary", ""),
                                       state["question"], state.get("answer", ""))
    return {"history": history, "summary": summary}


# ---------- wiring ----------


def build_graph(checkpointer: SqliteSaver) -> CompiledStateGraph:
    """Connect the nodes. Conditional edges pick the next node from the state."""
    graph = StateGraph(CopilotState)
    for name, node in [("supervisor", supervisor_node), ("claims", claims_node),
                       ("benefits", benefits_node), ("prior_auth", prior_auth_node),
                       ("reviewer", reviewer_node), ("approval", approval_node),
                       ("remember", remember_node)]:
        graph.add_node(name, node)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", lambda s: s["route"],
                                {"claims": "claims", "benefits": "benefits",
                                 "prior_auth": "prior_auth", "clarify": "remember"})
    for specialist in ("claims", "benefits", "prior_auth"):
        graph.add_edge(specialist, "reviewer")
    graph.add_conditional_edges("reviewer", after_review,
                                ["claims", "benefits", "prior_auth", "approval", "remember"])
    graph.add_edge("approval", "remember")
    graph.add_edge("remember", END)
    return graph.compile(checkpointer=checkpointer)


def open_graph() -> CompiledStateGraph:
    """The graph with its SQLite checkpoint store."""
    connection = sqlite3.connect(checkpoint_db(), check_same_thread=False)
    return build_graph(SqliteSaver(connection))


# ---------- terminal entry point ----------


def ask_for_approval(payload: dict) -> dict:
    """Show the proposed action and ask the person at the terminal."""
    print("\n" + "=" * 60)
    print("APPROVAL NEEDED. Nothing has been written yet.")
    print("=" * 60)
    print(payload["draft"])
    if payload.get("review"):
        print(f"\nReviewer: {'passed' if payload['review']['passed'] else 'FAILED'}")
    while True:
        # Accept "approve", or "approve Nick" with the name on the same line.
        words = input("\nType approve or reject (you can add your name after it): ").split()
        choice = words[0].strip(".,:;!").lower() if words else ""
        if choice in ("approve", "reject"):
            break
        print("Please start with the word approve or reject.")
    name_words = words[1:]
    if name_words and name_words[0].lower().startswith("name"):  # "approve name: Nick"
        name_words = name_words[1:]
    approver = " ".join(name_words).strip(" -:,") or input("Your name: ").strip() or "unknown"
    return {"decision": choice, "approver": approver}


def run_in_terminal(question: str | None, session_id: str | None = None, resume: bool = False) -> None:
    """Ask a question in a session (or resume a paused one), handle any approval, print the result."""
    graph = open_graph()
    run_id = tracing.new_run_id()
    session_id = session_id or run_id
    config = {"configurable": {"thread_id": session_id}}
    if resume:
        snapshot = graph.get_state(config)
        if not snapshot.next:
            print(f"Session {session_id} has nothing waiting.")
            return
        run_id = snapshot.values["run_id"]
        state = {"__interrupt__": snapshot.interrupts}
    else:
        print(f"Question: {question}\nSession: {session_id}\nWorking (each step calls the model)...")
        state = graph.invoke(new_question(question, run_id), config)

    while state.get("__interrupt__"):
        print(f"\n(Paused and saved. You can close this window and later run:"
              f"\n uv run python -m copilot.graph --resume {session_id})")
        decision = ask_for_approval(state["__interrupt__"][0].value)
        state = graph.invoke(Command(resume=decision), config)

    print()
    for step in tracing.read_run(run_id):
        print(tracing.format_step(step))
    verdict = state.get("review") or {}
    print(f"\n=== Answer (route: {state.get('route')}, reviewer: "
          f"{'passed' if verdict.get('passed') else verdict.get('reasons', 'not run')}) ===")
    print(state.get("answer", ""))
    print(f"\nTrace: run {run_id}. Session: {session_id} (reuse it with --session {session_id})")


def main() -> None:
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--resume":
        run_in_terminal(None, session_id=args[1], resume=True)
    elif len(args) >= 3 and args[0] == "--session":
        run_in_terminal(" ".join(args[2:]), session_id=args[1])
    else:
        run_in_terminal(" ".join(args) or "Why was claim CLM-10482 denied and what can the member do?")


if __name__ == "__main__":
    main()
```

### `app/streamlit_app.py`

```python
"""Payer Copilot web app: chat, approval buttons and a trace panel.

Run:  uv run streamlit run app/streamlit_app.py
Then open http://localhost:8501 in your browser.

Each browser session is one LangGraph thread, so follow-up questions
remember earlier turns. All model calls still go through the graph and the
adapter; this file only shows things and passes on your clicks.
"""

import streamlit as st
from langgraph.types import Command

from copilot import memory, tracing
from copilot.graph import new_question, open_graph

st.set_page_config(page_title="Payer Copilot", layout="wide")
RECOMMENDATIONS = ["approve", "deny", "needs_more_info"]


@st.cache_resource
def get_graph():
    """One graph (and checkpoint connection) shared by every rerun of this page."""
    return open_graph()


def start_session() -> None:
    """A fresh session: new thread, empty chat."""
    st.session_state.session_id = tracing.new_run_id()
    st.session_state.chat = []
    st.session_state.run_id = None
    st.session_state.pending = None


if "session_id" not in st.session_state:
    start_session()
ss = st.session_state
graph = get_graph()
config = {"configurable": {"thread_id": ss.session_id}}


def show_result(state: dict) -> None:
    """After the graph returns: either it paused for approval, or it has an answer."""
    if state.get("__interrupt__"):
        ss.pending = state["__interrupt__"][0].value
        return
    ss.pending = None
    ss.chat.append({"role": "assistant", "content": state.get("answer", ""),
                    "route": state.get("route"), "review": state.get("review")})


# ---------- sidebar: session, memory ----------

with st.sidebar:
    st.header("Session")
    st.caption(f"Session ID: {ss.session_id}")
    if st.button("New session"):
        start_session()
        st.rerun()

    values = graph.get_state(config).values
    st.subheader("In focus")
    st.write(f"Member: {values.get('member_id') or '-'}  \nClaim: {values.get('claim_id') or '-'}")

    st.subheader("Notes about this member")
    notes = memory.member_notes(values.get("member_id"))
    st.write("\n".join(f"- {n}" for n in notes) if notes else "None yet.")

    st.subheader("Your preferences")
    for pref in memory.analyst_preferences():
        st.write(f"- {pref}")
    new_pref = st.text_input("Add a preference", placeholder="e.g. Keep answers to 3 sentences", key="new_pref")
    if st.button("Save preference") and new_pref.strip():
        memory.add_note("analyst", new_pref.strip())
        st.rerun()

# ---------- main area ----------

st.title("Payer Copilot")
st.warning("SYNTHETIC DATA ONLY. Acme Health Plan, its members and claims are fictional. "
           "The copilot recommends; a person decides.")
chat_col, trace_col = st.columns([3, 2])

with chat_col:
    for message in ss.chat:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant" and message.get("route"):
                review = message.get("review") or {}
                status = "passed" if review.get("passed") else "not passed" if review else "not run"
                st.caption(f"Route: {message['route']} · Reviewer: {status}")

    if ss.pending:
        action = ss.pending["action"]
        args = action["arguments"]
        with st.container(border=True):
            st.subheader("Approval needed. Nothing has been written yet.")
            st.markdown(ss.pending["draft"].replace("\n", "  \n"))
            review = ss.pending.get("review") or {}
            st.caption(f"Reviewer: {'passed' if review.get('passed') else review.get('reasons')}")
            st.markdown("**Edit before approving, if needed**")
            recommendation = st.selectbox("Recommendation", RECOMMENDATIONS, key="recommendation",
                                          index=RECOMMENDATIONS.index(args["recommendation"]))
            rationale = st.text_area("Rationale", value=args["rationale"], height=150, key="rationale")
            approver = st.text_input("Your name (required)", key="approver")
            approve_col, reject_col = st.columns(2)
            clicked = None
            if approve_col.button("Approve", type="primary"):
                clicked = "approve"
            if reject_col.button("Reject"):
                clicked = "reject"
            if clicked and not approver.strip():
                st.error("Please type your name first. The decision is logged with it.")
            elif clicked:
                edited = {**args, "recommendation": recommendation, "rationale": rationale}
                decision = {"decision": clicked, "approver": approver.strip(), "arguments": edited}
                with st.spinner("Recording your decision..."):
                    show_result(graph.invoke(Command(resume=decision), config))
                st.rerun()

    question = st.chat_input("Ask about a claim, a plan's coverage, or a prior auth",
                             disabled=bool(ss.pending))
    if question:
        ss.chat.append({"role": "user", "content": question})
        ss.run_id = tracing.new_run_id()
        with st.spinner("Working. Each step calls the local model, so this can take a few minutes..."):
            show_result(graph.invoke(new_question(question, ss.run_id), config))
        st.rerun()

with trace_col:
    st.subheader("Trace of the latest question")
    steps = tracing.read_run(ss.run_id) if ss.run_id else []
    if not steps:
        st.caption("Ask a question to see each step here.")
    for step in steps:
        label = (f"Step {step['step']} · {step['agent']} · {step.get('action') or 'error'} · "
                 f"{step.get('latency_s') or 0:.1f}s")
        with st.expander(label):
            if step.get("error"):
                st.error(step["error"])
            if step.get("arguments") is not None:
                st.markdown("**Arguments**")
                st.json(step["arguments"])
            if "tool_result" in step:
                st.markdown("**Tool result**")
                st.json(step["tool_result"], expanded=False)
            if step.get("raw_output"):
                st.markdown("**Raw model output**")
                st.code(step["raw_output"], language="json")
            if step.get("prompt"):
                st.markdown("**Prompt the model saw**")
                st.json(step["prompt"], expanded=False)
            st.caption(f"Tokens in/out: {step.get('input_tokens')} / {step.get('output_tokens')}")
```

### `.streamlit/config.toml`

```toml
# Keep the app fully local: no usage statistics sent to Streamlit.
[browser]
gatherUsageStats = false

[server]
headless = true
```

### `src/copilot/agents/supervisor.py`

```python
"""The supervisor: reads the analyst's request and picks one specialist.

It calls no tools. It returns a RouteDecision through structured output, so
the reply always parses. An unclear request gets a clarifying question
instead of a guess.
"""

from langchain_core.messages import HumanMessage, SystemMessage

from copilot import tracing
from copilot.llm import decide_structured
from copilot.schemas import RouteDecision

SYSTEM_PROMPT = """You route requests from a claims analyst at Acme Health Plan to one specialist.

- claims: questions about a specific claim (status, amounts, why it was denied, appeal letters), a member's claim history or what has been done for them, or what a denial code means.
- benefits: what a plan (Bronze, Silver or Gold) covers in general, limits, costs, rules.
- prior_auth: whether a member's planned procedure needs prior authorization or meets its criteria.
- clarify: the request is unclear, or doesn't fit the above. Ask one short question.

Copy any member ID (like M-00217) and claim ID (like CLM-10482) exactly as written. Leave them empty if not given.
If the request refers to something earlier ("that claim", "this member"), it is about the IDs in focus; route it as if they were named.

Examples:
"Why was claim CLM-10482 denied?" -> claims, claim_id CLM-10482
"Does Gold cover chiropractic care?" -> benefits
"Member M-00217 needs a knee MRI. Is prior auth required?" -> prior_auth, member_id M-00217
"What has been done for member M-00217?" -> claims, member_id M-00217
"Can you help with this member?" (nothing in focus) -> clarify
"Draft the appeal letter for that claim" (claim CLM-10482 in focus) -> claims

Keep your private thinking short."""


def route(question: str, run_id: str, context: str = "") -> RouteDecision:
    """Decide which specialist handles the question.

    `context` is what the session remembers (IDs in focus, last question),
    so a follow-up like "draft the appeal for that claim" can be routed.
    """
    content = f"{context}\n\nNew request: {question}" if context else question
    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=content)]
    result = decide_structured(messages, RouteDecision, "supervisor")
    tracing.write_step(run_id, "supervisor", 0, prompt=[{"role": "human", "content": content}],
                       raw_output=result.raw, action="route", arguments=result.data,
                       input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                       latency_s=result.latency_s)
    return RouteDecision.model_validate(result.data)
```

### `src/copilot/agents/loop.py`

```python
"""The specialist loop: decide an action, call a tool, read the result, repeat.

Every specialist (claims, benefits, prior auth) uses this same loop with its
own instructions and tools. It stops when the model gives a final answer, or
after the tool-call limit, when the model must answer from what it has.

A "gated" tool (submit_prior_auth) is never run here. When the model picks
it, the loop stops and returns the action as pending_action, so the graph
can ask a person to approve it first.

The conversation alternates assistant and user turns on purpose: some chat
templates, Gemma's among them, refuse two user messages in a row. So a tool
result goes back to the model as a user message.
"""

import json
import time

import yaml
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from copilot import tracing
from copilot.llm import CONFIG_PATH, ActionError, decide_action
from copilot.schemas import FINAL_ANSWER, AgentResult, Evidence, ToolSpec
from copilot.tools import run_tool

SAFE_FALLBACK = ("I couldn't finish this within the step limit. "
                 "Please review the trace, or ask a narrower question.")


def max_tool_calls() -> int:
    """Tool-call limit per run, from config.yaml (design: 4)."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)["agents"]["max_tool_calls"]


def _as_dicts(messages: list[BaseMessage]) -> list[dict[str, str]]:
    """Messages as plain {role, content} dicts, for the trace."""
    return [{"role": m.type, "content": str(m.content)} for m in messages]


def _describe_pending(arguments: dict) -> str:
    """A readable draft of a gated action, for the person approving it."""
    lines = [f"{key}: {value}" for key, value in arguments.items()]
    return "Prior auth recommendation (for a person to review):\n" + "\n".join(lines)


def run_agent(agent: str, system_prompt: str, tools: list[ToolSpec], question: str,
              run_id: str | None = None, gated: tuple[str, ...] = ()) -> AgentResult:
    """Run one specialist on one question and return its answer and evidence.

    `gated` names tools that need a person's approval; they end the loop
    instead of running.
    """
    run_id = run_id or tracing.new_run_id()
    limit = max_tool_calls()
    messages: list[BaseMessage] = [SystemMessage(content=system_prompt), HumanMessage(content=question)]
    evidence: list[Evidence] = []
    tool_calls = 0
    # Number steps after any earlier steps of this run (the supervisor, or a first attempt).
    first_step = max((s["step"] for s in tracing.read_run(run_id)), default=0) + 1
    think = None  # None: use config.yaml. False: thinking off for one retry after a cut-off.
    # Room for every tool call, one final answer and two invalid replies.
    for step in range(first_step, first_step + limit + 3):
        # At the limit only final_answer (and any gated tool) remains.
        allowed = tools if tool_calls < limit else [t for t in tools if t.name in gated]
        prompt = _as_dicts(messages)
        start = time.perf_counter()
        try:
            decision = decide_action(messages, allowed, thinking=think)
        except ActionError as e:
            tracing.write_step(run_id, agent, step, prompt=prompt, raw_output=e.raw, error=str(e),
                               latency_s=round(time.perf_counter() - start, 2))
            if e.cut_off:
                # The hidden thinking used up the whole reply budget. Asking again
                # the same way gets the same result, so retry this step without thinking.
                think = False
                continue
            messages.append(AIMessage(content=e.raw))
            messages.append(HumanMessage(content=f"That reply was not valid: {e} Reply again with one valid action."))
            continue

        think_note = "thinking off after a cut-off" if think is False else None
        think = None  # the next step may think again
        action = decision.action
        trace_fields = dict(note=think_note, prompt=prompt, raw_output=decision.raw, action=action.action,
                            arguments=action.arguments, input_tokens=decision.input_tokens,
                            output_tokens=decision.output_tokens, latency_s=decision.latency_s)
        if action.action == FINAL_ANSWER:
            tracing.write_step(run_id, agent, step, **trace_fields)
            return AgentResult(run_id=run_id, agent=agent, question=question,
                               answer=action.arguments["answer"], tool_calls=tool_calls,
                               stopped_reason="final_answer", evidence=evidence)

        if action.action in gated:
            tracing.write_step(run_id, agent, step, **{**trace_fields, "note": "paused for human approval"})
            return AgentResult(run_id=run_id, agent=agent, question=question,
                               answer=_describe_pending(action.arguments), tool_calls=tool_calls,
                               stopped_reason="needs_approval", evidence=evidence, pending_action=action)

        result = run_tool(action.action, action.arguments)
        tool_calls += 1
        evidence.append(Evidence(tool=action.action, arguments=action.arguments, result=result))
        tracing.write_step(run_id, agent, step, **trace_fields, tool_result=result)

        note = ""
        if tool_calls >= limit:
            note = "\n\nYou have used all your tool calls. Give your final answer now from the results above."
        messages.append(AIMessage(content=json.dumps(action.model_dump())))
        messages.append(HumanMessage(content=f"Tool result from {action.action}:\n{json.dumps(result)}{note}"))

    return AgentResult(run_id=run_id, agent=agent, question=question, answer=SAFE_FALLBACK,
                       tool_calls=tool_calls, stopped_reason="step_limit", evidence=evidence)
```

### `src/copilot/llm.py`

```python
"""The model adapter. Every call to the model in this project goes through here.

Two modes, chosen in config.yaml (llm.mode):

- json_action (default): we ask for one JSON object
  {"action": ..., "arguments": {...}} and give LM Studio a JSON schema.
  LM Studio constrains the model to that schema, so the reply always parses.
- native_tools: we pass the tools in the OpenAI "tools" format and read the
  model's tool_calls. This depends on the model's own tool-calling skill.

Both modes return the same Decision (the Action plus the raw reply, token
counts and time taken, for the trace), so the rest of the app never needs
to know which mode ran.

decide_structured() fills in one Pydantic model, used for routing and review.
complete_text() returns plain text, used for the conversation summary.
embed() turns text into vectors for the policy search (RAG).

Run `uv run python -m copilot.llm` to check that LM Studio is reachable and
to list the model IDs it serves.
"""

import json
import time
from pathlib import Path
from typing import Any

import yaml
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import LengthFinishReasonError, OpenAI
from pydantic import BaseModel, ValidationError

from copilot.schemas import FINAL_ANSWER, Action, Decision, FinalAnswerArgs, Structured, ToolSpec

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"
MODES = ("json_action", "native_tools")


class ActionError(Exception):
    """The model's reply could not be turned into a valid Action."""

    def __init__(self, message: str, raw: str, cut_off: bool = False) -> None:
        super().__init__(message)
        self.raw = raw
        self.cut_off = cut_off  # True when the reply hit max_tokens (usually long thinking)


def load_config() -> dict[str, Any]:
    """Read the llm section of config.yaml."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)["llm"]


def thinking_on(role: str) -> bool:
    """Whether this role lets the model think before replying (config.yaml, llm.thinking).

    Thinking (hidden reasoning before the reply) helps with harder steps but
    is slow, and long thinking can use up the whole max_tokens budget.
    """
    return bool(load_config().get("thinking", {}).get(role, True))


def get_chat_model(temperature: float | None = None, thinking: bool = True) -> ChatOpenAI:
    """Build the LangChain chat client that points at LM Studio.

    thinking=False sends reasoning_effort "none", which LM Studio uses to
    turn Gemma 4's hidden thinking off for that call.
    """
    cfg = load_config()
    return ChatOpenAI(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["chat_model"],
        temperature=cfg["temperature"] if temperature is None else temperature,
        max_tokens=cfg["max_tokens"],
        timeout=cfg["timeout_seconds"],
        max_retries=0,
        extra_body=None if thinking else {"reasoning_effort": "none"},
    )


def decide_action(
    messages: list[BaseMessage],
    tools: list[ToolSpec],
    mode: str | None = None,
    role: str = "agents",
    thinking: bool | None = None,
) -> Decision:
    """Ask the model for its next step: one tool call or the final answer.

    `messages` is the conversation so far (system prompt first).
    `tools` is the allow-list for the calling agent. An empty list leaves
    only final_answer. `role` picks the thinking setting in config.yaml;
    `thinking` overrides it for this one call.
    Raises ActionError if the reply is not a valid Action.
    """
    mode = mode or load_config()["mode"]
    think = thinking_on(role) if thinking is None else thinking
    start = time.perf_counter()
    if mode == "json_action":
        action, raw, reply = _decide_json_action(messages, tools, think)
    elif mode == "native_tools":
        action, raw, reply = _decide_native_tools(messages, tools, think)
    else:
        raise ValueError(f"Unknown mode {mode!r}. Use one of {MODES}.")
    usage = reply.usage_metadata or {}
    return Decision(
        action=action,
        raw=raw,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        latency_s=round(time.perf_counter() - start, 2),
    )


# ---------- json_action mode ----------


def _action_schema(tools: list[ToolSpec]) -> dict[str, Any]:
    """Build the JSON schema the model must follow.

    It allows one shape per tool ({"action": "<that tool>", "arguments":
    <that tool's arguments>}) plus one shape for final_answer. LM Studio
    turns this schema into a grammar, so the model cannot invent a tool name
    or leave out a required argument.
    """
    choices = [_one_choice(t.name, t.args_model.model_json_schema()) for t in tools]
    choices.append(_one_choice(FINAL_ANSWER, FinalAnswerArgs.model_json_schema()))
    return {"anyOf": choices}


def _one_choice(name: str, args_schema: dict[str, Any]) -> dict[str, Any]:
    """Schema for one allowed action and its arguments."""
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": [name]},
            "arguments": args_schema,
        },
        "required": ["action", "arguments"],
    }


def _tool_list_prompt(tools: list[ToolSpec]) -> str:
    """Plain-text tool list added to the system prompt in json_action mode.

    The schema enforces the shape; this text tells the model what each
    tool is for.
    """
    lines = ["You can take exactly one action per reply. Available actions:"]
    for t in tools:
        args = ", ".join(t.args_model.model_fields)
        lines.append(f"- {t.name}({args}): {t.description}")
    lines.append(
        f"- {FINAL_ANSWER}(answer): Reply to the analyst when you have what you need."
    )
    lines.append(
        'Reply with one JSON object: {"action": "<name>", "arguments": {...}}.'
    )
    return "\n".join(lines)


def _add_to_system_prompt(messages: list[BaseMessage], extra: str) -> list[BaseMessage]:
    """Append text to the system prompt. Some chat templates (Gemma's among
    them) accept only one system message, so we merge instead of adding a
    second one."""
    if messages and isinstance(messages[0], SystemMessage):
        merged = SystemMessage(content=f"{messages[0].content}\n\n{extra}")
        return [merged, *messages[1:]]
    return [SystemMessage(content=extra), *messages]


def _decide_json_action(
    messages: list[BaseMessage], tools: list[ToolSpec], thinking: bool = True
) -> tuple[Action, str, AIMessage]:
    """json_action mode: schema-constrained JSON, then validate it."""
    prompt = _add_to_system_prompt(messages, _tool_list_prompt(tools))
    data, raw, reply = _json_schema_call(prompt, "action", _action_schema(tools), thinking)
    action = Action(action=data.get("action", ""), arguments=data.get("arguments") or {})
    return _validate(action, tools, raw), raw, reply


def _json_schema_call(
    prompt: list[BaseMessage], name: str, schema: dict[str, Any], thinking: bool = True
) -> tuple[dict[str, Any], str, AIMessage]:
    """One model call whose reply must match a JSON schema. Returns the
    parsed JSON, the raw text and the reply message."""
    response_format = {"type": "json_schema", "json_schema": {"name": name, "schema": schema}}
    try:
        reply = get_chat_model(thinking=thinking).invoke(prompt, response_format=response_format)
    except LengthFinishReasonError as e:
        # The reply was cut off at max_tokens. Thinking models such as Gemma 4
        # spend part of that budget on hidden reasoning before the JSON.
        usage = e.completion.usage
        raise ActionError(
            f"Reply cut off at max_tokens ({usage.completion_tokens} tokens used). "
            "Keep the reply short.",
            raw=str(e.completion.choices[0].message.content or ""),
            cut_off=True,
        ) from e
    raw = str(reply.content)
    try:
        return json.loads(raw), raw, reply
    except json.JSONDecodeError as e:
        raise ActionError(f"Reply is not JSON: {e}", raw) from e


# ---------- structured output (supervisor and reviewer) ----------


def decide_structured(messages: list[BaseMessage], schema: type[BaseModel], role: str) -> Structured:
    """Ask the model to fill in one Pydantic model, such as a routing decision.

    `role` ("supervisor" or "reviewer") picks the thinking setting in config.yaml.
    Always uses a JSON schema, whatever the mode, because routing must parse.
    Raises ActionError if the reply doesn't fit the model.
    """
    start = time.perf_counter()
    data, raw, reply = _json_schema_call(messages, schema.__name__, schema.model_json_schema(),
                                       thinking_on(role))
    try:
        value = schema.model_validate(data)
    except ValidationError as e:
        raise ActionError(f"Reply doesn't fit {schema.__name__}: {e}", raw) from e
    usage = reply.usage_metadata or {}
    return Structured(
        data=value.model_dump(),
        raw=raw,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        latency_s=round(time.perf_counter() - start, 2),
    )


# ---------- native_tools mode ----------


def _decide_native_tools(
    messages: list[BaseMessage], tools: list[ToolSpec], thinking: bool = True
) -> tuple[Action, str, AIMessage]:
    """native_tools mode: OpenAI-style tool calling, then validate it."""
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.args_model.model_json_schema(),
            },
        }
        for t in tools
    ]
    model = get_chat_model(thinking=thinking)
    if openai_tools:
        reply = model.bind_tools(openai_tools, tool_choice="auto").invoke(messages)
    else:  # no tools left: the model can only answer
        reply = model.invoke(messages)
    raw = json.dumps({"content": reply.content, "tool_calls": reply.tool_calls})
    if reply.tool_calls:
        call = reply.tool_calls[0]  # one action per step, like json_action mode
        action = Action(action=call["name"], arguments=call["args"])
    else:
        action = Action(action=FINAL_ANSWER, arguments={"answer": str(reply.content)})
    return _validate(action, tools, raw), raw, reply


# ---------- shared ----------


def _validate(action: Action, tools: list[ToolSpec], raw: str) -> Action:
    """Check the action is allowed and its arguments match the tool's model."""
    specs = {t.name: t.args_model for t in tools}
    specs[FINAL_ANSWER] = FinalAnswerArgs
    if action.action not in specs:
        raise ActionError(f"Action {action.action!r} is not in the allow-list.", raw)
    try:
        args = specs[action.action].model_validate(action.arguments)
    except ValidationError as e:
        raise ActionError(f"Bad arguments for {action.action}: {e}", raw) from e
    return Action(action=action.action, arguments=args.model_dump(exclude_none=True))


def complete_text(messages: list[BaseMessage]) -> str:
    """A plain text reply, with no schema. Used to write the running summary."""
    return str(get_chat_model(thinking=thinking_on("summary")).invoke(messages).content)


def embed(texts: list[str], kind: str) -> list[list[float]]:
    """Turn texts into embedding vectors with the embedding model in LM Studio.

    `kind` is "document" (when building the index) or "query" (when
    searching). nomic-embed-text works best when each text starts with a
    task prefix, set in config.yaml.
    """
    cfg = load_config()
    prefix = cfg["embedding_document_prefix"] if kind == "document" else cfg["embedding_query_prefix"]
    client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"], timeout=cfg["timeout_seconds"])
    response = client.embeddings.create(model=cfg["embedding_model"], input=[prefix + t for t in texts])
    return [item.embedding for item in response.data]


def list_models() -> list[str]:
    """Return the model IDs LM Studio is serving (GET /v1/models)."""
    cfg = load_config()
    client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"], timeout=10)
    return [m.id for m in client.models.list().data]


def main() -> None:
    """Connection check: list models and say whether config.yaml matches."""
    cfg = load_config()
    print(f"LM Studio server: {cfg['base_url']}")
    try:
        ids = list_models()
    except Exception as e:  # any connection problem
        print(f"Could not reach LM Studio: {e}")
        print("Is the server running? LM Studio > Developer > Start server.")
        return
    print("Models available:")
    for model_id in ids:
        print(f"  - {model_id}")
    for key in ("chat_model", "embedding_model"):
        found = "OK" if cfg[key] in ids else "NOT FOUND, copy an ID from the list above"
        print(f"config {key}: {cfg[key]}  [{found}]")
    print(f"config mode: {cfg['mode']}")


if __name__ == "__main__":
    main()
```

### `src/copilot/schemas.py`

```python
"""Pydantic models shared across the app.

- Action: what an agent decides (call a tool, or give the final answer).
- ToolSpec: how a tool is described to the model, plus the code that runs it.
- Tool inputs: one model per tool; the model's arguments must match it.
- Tool outputs: one model per tool; what the tool hands back.
- AgentResult: what one agent run produces.
- RouteDecision, ReviewVerdict and CopilotState: the supervisor's and the
  reviewer's outputs, and the graph's state.
"""

from typing import Any, Callable, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

FINAL_ANSWER = "final_answer"


class Action(BaseModel):
    """One decision from an agent: call a tool, or give the final answer."""

    action: str = Field(description="A tool name, or 'final_answer'.")
    arguments: dict[str, Any] = Field(default_factory=dict)


class Decision(BaseModel):
    """What the adapter returns: the Action, plus details for the trace."""

    action: Action
    raw: str = Field(description="The model's reply exactly as it came back.")
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_s: float


class Structured(BaseModel):
    """What decide_structured returns: the filled-in fields, plus trace details."""

    data: dict[str, Any]
    raw: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_s: float


class ToolSpec(BaseModel):
    """One tool: the name and one-line description the model reads, the
    Pydantic model its arguments must match, and the function that runs it."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    args_model: type[BaseModel]
    func: Callable[[Any], BaseModel]


# ---------- Tool inputs (one model per tool in the design) ----------


class FinalAnswerArgs(BaseModel):
    """Arguments for the built-in final_answer action."""

    answer: str = Field(description="The reply to the analyst.")


class GetMemberArgs(BaseModel):
    member_id: str = Field(description="Member ID, like M-00217.")


class GetClaimArgs(BaseModel):
    claim_id: str = Field(description="Claim ID, like CLM-10482.")


class SearchClaimsArgs(BaseModel):
    member_id: str = Field(description="Member ID, like M-00217.")
    status: Literal["paid", "denied", "pending"] | None = Field(
        default=None, description="Only claims with this status."
    )
    start_date: str | None = Field(default=None, description="YYYY-MM-DD, inclusive.")
    end_date: str | None = Field(default=None, description="YYYY-MM-DD, inclusive.")


class ExplainDenialCodeArgs(BaseModel):
    code: str = Field(description="Denial code, like CO-197.")


class SearchPolicyArgs(BaseModel):
    query: str = Field(description="What to look for in the plan and policy documents.")


class CheckAuthRequiredArgs(BaseModel):
    procedure_code: str = Field(description="Procedure code, like 73721.")
    plan: Literal["Bronze", "Silver", "Gold"] = Field(description="The member's plan.")


class GetAuthCriteriaArgs(BaseModel):
    procedure_code: str = Field(description="Procedure code, like 73721.")


class SubmitPriorAuthArgs(BaseModel):
    member_id: str = Field(description="Member ID, like M-00217.")
    procedure_code: str = Field(description="Procedure code, like 73721.")
    recommendation: Literal["approve", "deny", "needs_more_info"] = Field(
        description="The copilot's recommendation. A person makes the decision."
    )
    rationale: str = Field(description="Criteria met and unmet, in one or two sentences.")


class DraftLetterArgs(BaseModel):
    letter_type: Literal["appeal", "member"] = Field(description="Which template to fill.")
    claim_id: str = Field(description="Claim ID, like CLM-10482.")


# ---------- Tool outputs ----------


class MemberOut(BaseModel):
    member_id: str
    name: str
    date_of_birth: str
    plan: str
    eligibility_start: str
    eligibility_end: str | None
    is_active: bool = Field(description="Eligible on the app's 'today' date.")
    deductible: int
    coinsurance_pct: int
    pt_visit_limit: int


class ClaimLineOut(BaseModel):
    line_no: int
    procedure_code: str
    procedure: str
    diagnosis_code: str
    diagnosis: str
    units: int
    billed_amount: float


class ClaimOut(BaseModel):
    claim_id: str
    member_id: str
    provider: str
    provider_in_network: bool
    service_date: str
    received_date: str
    status: str
    billed_amount: float
    allowed_amount: float
    paid_amount: float
    member_owes: float
    denial_code: str | None
    lines: list[ClaimLineOut]


class ClaimSummary(BaseModel):
    claim_id: str
    service_date: str
    services: str = Field(description="Procedure codes and names on the claim.")
    status: str
    billed_amount: float
    paid_amount: float
    denial_code: str | None


class ClaimSearchOut(BaseModel):
    member_id: str
    total_found: int
    claims: list[ClaimSummary] = Field(description="Newest first, at most 20.")


class DenialCodeOut(BaseModel):
    code: str
    name: str
    meaning: str
    next_step: str


class PolicyPassage(BaseModel):
    document: str
    section: str
    text: str
    score: float


class PolicySearchOut(BaseModel):
    query: str
    passages: list[PolicyPassage] = Field(description="Best match first. Empty if nothing matched.")


class AuthRequiredOut(BaseModel):
    procedure_code: str
    procedure: str
    plan: str
    auth_required: bool
    policy_document: str | None


class AuthCriteriaOut(BaseModel):
    procedure_code: str
    procedure: str
    criteria: list[str]
    policy_document: str


class SubmitPriorAuthOut(BaseModel):
    auth_id: str
    member_id: str
    procedure_code: str
    status: str
    recommendation: str


class LetterOut(BaseModel):
    letter_type: str
    claim_id: str
    path: str
    text: str


# ---------- Agent results ----------


class Evidence(BaseModel):
    """One tool call the agent made, and what came back."""

    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any]


class AgentResult(BaseModel):
    run_id: str
    agent: str
    question: str
    answer: str
    tool_calls: int
    stopped_reason: Literal["final_answer", "step_limit", "needs_approval"]
    evidence: list[Evidence]
    pending_action: Action | None = Field(
        default=None, description="A gated tool call waiting for a person to approve it."
    )


# ---------- Supervisor and graph state ----------


class RouteDecision(BaseModel):
    """The supervisor's output."""

    route: Literal["claims", "benefits", "prior_auth", "clarify"] = Field(
        description="claims: a specific claim or denial code. benefits: what a plan covers. "
        "prior_auth: whether a procedure needs or meets prior authorization. "
        "clarify: the request is unclear."
    )
    member_id: str | None = Field(default=None, description="Member ID in the request, like M-00217.")
    claim_id: str | None = Field(default=None, description="Claim ID in the request, like CLM-10482.")
    clarifying_question: str | None = Field(
        default=None, description="Only for route 'clarify': one short question back to the analyst."
    )


class ReviewVerdict(BaseModel):
    """The compliance reviewer's output."""

    passed: bool = Field(description="True only if the draft follows all three rules.")
    reasons: list[str] = Field(default_factory=list, description="For a fail: each rule broken and where.")


class CopilotState(TypedDict, total=False):
    """Everything the graph knows about one session. LangGraph saves it in a
    checkpoint after every step, so a paused run can resume later and a
    follow-up question can see earlier turns.

    Session fields last across questions; per-question fields are reset by
    graph.new_question() at the start of each question.
    """

    # session: kept across questions
    history: list[dict[str, str]]  # last turns, [{"question": ..., "answer": ...}]
    summary: str  # running summary of turns older than the kept ones
    member_id: str | None  # IDs in focus
    claim_id: str | None
    # per question
    run_id: str
    question: str
    route: str
    answer: str
    evidence: list[dict[str, Any]]
    tool_calls: int
    review: dict[str, Any] | None  # ReviewVerdict.model_dump()
    review_attempts: int
    pending_approval: dict[str, Any] | None  # the gated action, as Action.model_dump()
    approval: dict[str, Any] | None  # {"decision", "approver", "arguments" actually used, "edited"}
    submission: dict[str, Any] | None  # what submit_prior_auth returned, after approval
```

### `src/copilot/tracing.py`

```python
"""JSONL trace writer: one line per agent step, in traces/trace.jsonl.

Each line records what the model saw (prompt), what it said (raw output),
the action it chose, the tool's result, tokens and time taken. Reading the
trace is the fastest way to learn why an agent did what it did.

    uv run python -m copilot.tracing            # show the latest run
    uv run python -m copilot.tracing <run_id>   # show one run
"""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

TRACE_FILE = Path(__file__).resolve().parents[2] / "traces" / "trace.jsonl"


def new_run_id() -> str:
    """A short unique ID for one question, like 20261118-091502-3fa1."""
    return f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"


def write_step(run_id: str, agent: str, step: int, **fields: Any) -> None:
    """Append one JSON line for one step of one run."""
    TRACE_FILE.parent.mkdir(exist_ok=True)
    line = {"run_id": run_id, "time": datetime.now().isoformat(timespec="seconds"),
            "agent": agent, "step": step, **fields}
    with open(TRACE_FILE, "a") as f:
        f.write(json.dumps(line, default=str) + "\n")


def read_run(run_id: str | None = None) -> list[dict[str, Any]]:
    """All steps of one run. With no run_id, the most recent run."""
    if not TRACE_FILE.exists():
        return []
    lines = [json.loads(line) for line in TRACE_FILE.read_text().splitlines() if line.strip()]
    if run_id is None and lines:
        run_id = lines[-1]["run_id"]
    return [line for line in lines if line["run_id"] == run_id]


def format_step(step: dict[str, Any]) -> str:
    """One step as a short readable block."""
    tokens = f"{step.get('input_tokens')}->{step.get('output_tokens')} tokens"
    head = f"step {step['step']} [{step['agent']}] {step.get('latency_s') or 0:.1f}s {tokens}"
    if step.get("error"):
        return f"{head}\n  ERROR: {step['error']}\n  raw: {str(step.get('raw_output'))[:200]}"
    body = f"  action: {step.get('action')} {json.dumps(step.get('arguments'))}"
    if "tool_result" in step:
        body += f"\n  result: {json.dumps(step['tool_result'])[:300]}"
    return f"{head}\n{body}"


def main() -> None:
    steps = read_run(sys.argv[1] if len(sys.argv) > 1 else None)
    if not steps:
        print("No trace found. Ask the agent a question first.")
        return
    print(f"run {steps[0]['run_id']}")
    for step in steps:
        print(format_step(step))


if __name__ == "__main__":
    main()
```

### `tests/test_tools.py`

```python
"""Unit tests for the nine tools. No model needed; runs in a few seconds.

Each test works on a temporary copy of payer.db and a temporary outbox, so
running the tests never changes your real data. The two search_policy
search tests also need the policy index and LM Studio; they are skipped
if either is missing.

Run:  uv run pytest tests/test_tools.py -v
"""

import shutil
import sqlite3

import pytest

from copilot.llm import list_models
from copilot.rag.ingest import load_sections, open_collection
from copilot import common
from copilot.tools import run_tool

REAL_DB = common.ROOT / "data" / "payer.db"


@pytest.fixture(autouse=True)
def temp_data(tmp_path, monkeypatch):
    """Point every tool at a copy of payer.db and a temporary outbox."""
    if not REAL_DB.exists():
        pytest.skip("payer.db missing. Run: uv run python data/generate.py")
    db_copy = tmp_path / "payer.db"
    shutil.copy(REAL_DB, db_copy)
    monkeypatch.setattr(common, "db_path", lambda: db_copy)
    monkeypatch.setattr(common, "outbox_dir", lambda: tmp_path / "outbox")
    return db_copy


# ---------- get_member ----------

def test_get_member_active():
    out = run_tool("get_member", {"member_id": "M-00217"})
    assert out["plan"] == "Silver" and out["is_active"] is True


def test_get_member_lapsed():
    out = run_tool("get_member", {"member_id": "M-00250"})
    assert out["is_active"] is False and out["eligibility_end"] == "2026-06-30"


def test_get_member_tidies_id():
    assert run_tool("get_member", {"member_id": " m-00217 "})["member_id"] == "M-00217"


def test_get_member_unknown():
    assert "not found" in run_tool("get_member", {"member_id": "M-99999"})["error"]


# ---------- get_claim ----------

def test_get_claim_demo_story_1():
    out = run_tool("get_claim", {"claim_id": "CLM-10482"})
    assert out["status"] == "denied" and out["denial_code"] == "CO-197"
    assert out["billed_amount"] == 1240.0 and out["lines"][0]["procedure_code"] == "72148"


def test_get_claim_bad_id():
    assert "doesn't look like" in run_tool("get_claim", {"claim_id": "10482"})["error"]


# ---------- search_claims ----------

def test_search_claims_all_for_member():
    out = run_tool("search_claims", {"member_id": "M-00217"})
    assert out["total_found"] == 10
    assert out["claims"][0]["service_date"] >= out["claims"][-1]["service_date"]  # newest first


def test_search_claims_filters():
    assert run_tool("search_claims", {"member_id": "M-00142", "status": "denied"})["total_found"] == 1
    out = run_tool("search_claims", {"member_id": "M-00217", "start_date": "2026-10-01", "end_date": "2026-10-31"})
    assert [c["claim_id"] for c in out["claims"]] == ["CLM-11499"]
    assert out["claims"][0]["services"] == "73562 Knee X-ray, three views"  # the agent needs to see what each claim was for


def test_search_claims_bad_inputs():
    assert "2026-09-12" in run_tool("search_claims", {"member_id": "M-00217", "start_date": "Oct 1"})["error"]
    assert "Bad arguments" in run_tool("search_claims", {"member_id": "M-00217", "status": "Denied"})["error"]


# ---------- explain_denial_code ----------

def test_explain_denial_code():
    out = run_tool("explain_denial_code", {"code": "co-197"})
    assert out["name"] == "No prior authorization"


def test_explain_denial_code_unknown():
    assert "Known codes" in run_tool("explain_denial_code", {"code": "XX-1"})["error"]


# ---------- search_policy and the policy index ----------

def test_load_sections_splits_documents():
    sections = load_sections()
    assert len({s["document"] for s in sections}) == 10
    assert all(s["section"] and s["text"] for s in sections)
    assert ("silver_coverage_summary.md", "Physical therapy") in [(s["document"], s["section"]) for s in sections]


def test_silver_pt_limit_matches_table_and_document():
    """Design rule: the plans table and the Silver document must agree."""
    limit = run_tool("get_member", {"member_id": "M-00217"})["pt_visit_limit"]
    silver_pt = [s for s in load_sections()
                 if s["document"] == "silver_coverage_summary.md" and s["section"] == "Physical therapy"]
    assert limit == 30 and f"up to {limit} visits" in silver_pt[0]["text"]


def test_search_policy_empty_query():
    assert "empty" in run_tool("search_policy", {"query": "  "})["error"]


@pytest.fixture
def policy_index():
    """search_policy needs the index and LM Studio's embedding model; skip if either is missing."""
    if open_collection() is None:
        pytest.skip("No policy index. Run: uv run python -m copilot.rag.ingest")
    try:
        list_models()
    except Exception:
        pytest.skip("LM Studio is not reachable, so queries can't be embedded.")


def test_search_policy_finds_silver_pt(policy_index):
    out = run_tool("search_policy", {"query": "Does the Silver plan cover physical therapy, and is there a visit limit?"})
    found = [(p["document"], p["section"]) for p in out["passages"]]
    assert ("silver_coverage_summary.md", "Physical therapy") in found


def test_search_policy_finds_appeal_deadline(policy_index):
    out = run_tool("search_policy", {"query": "How long does a member have to file an appeal?"})
    assert out["passages"][0]["document"] == "appeals_procedure.md"


# ---------- check_auth_required and get_auth_criteria ----------

def test_check_auth_required():
    assert run_tool("check_auth_required", {"procedure_code": "73721", "plan": "Silver"})["auth_required"] is True
    assert run_tool("check_auth_required", {"procedure_code": "70450", "plan": "Gold"})["auth_required"] is False
    assert run_tool("check_auth_required", {"procedure_code": "99213", "plan": "Bronze"})["auth_required"] is False


def test_check_auth_required_unknown_code():
    assert "not found" in run_tool("check_auth_required", {"procedure_code": "00000", "plan": "Gold"})["error"]


def test_get_auth_criteria():
    out = run_tool("get_auth_criteria", {"procedure_code": "73721"})
    assert len(out["criteria"]) == 5 and out["policy_document"] == "prior_auth_imaging.md"


def test_get_auth_criteria_none_needed():
    assert "does not need" in run_tool("get_auth_criteria", {"procedure_code": "99213"})["error"]


# ---------- submit_prior_auth (the only write) ----------

def _auth_rows(db) -> int:
    """How many prior auth requests are in the database."""
    return sqlite3.connect(db).execute("SELECT COUNT(*) FROM prior_auth_requests").fetchone()[0]


def test_submit_prior_auth_writes_one_row(temp_data):
    # Count first: after you approve demo story 3, your real payer.db has 61 rows, not 60.
    before = _auth_rows(temp_data)
    args = {"member_id": "M-00217", "procedure_code": "73721",
            "recommendation": "approve", "rationale": "All 5 criteria met."}
    out = run_tool("submit_prior_auth", args)
    assert out["auth_id"] == f"PA-{before + 1:04d}" and out["status"] == "pending"
    assert _auth_rows(temp_data) == before + 1
    con = sqlite3.connect(temp_data)
    assert con.execute("SELECT member_id FROM prior_auth_requests WHERE auth_id = ?",
                       (out["auth_id"],)).fetchone()[0] == "M-00217"


def test_submit_prior_auth_refuses_lapsed_member(temp_data):
    before = _auth_rows(temp_data)
    args = {"member_id": "M-00250", "procedure_code": "73721",
            "recommendation": "approve", "rationale": "x"}
    assert "not eligible" in run_tool("submit_prior_auth", args)["error"]
    assert _auth_rows(temp_data) == before


# ---------- draft_letter ----------

def test_draft_letter_appeal():
    out = run_tool("draft_letter", {"letter_type": "appeal", "claim_id": "CLM-10482"})
    assert "CO-197" in out["text"] and "$1,240.00" in out["text"]
    assert out["path"].endswith("CLM-10482_appeal.md")
    assert common.outbox_dir().joinpath("CLM-10482_appeal.md").exists()


def test_draft_letter_appeal_needs_denied_claim():
    assert "nothing to appeal" in run_tool("draft_letter", {"letter_type": "appeal", "claim_id": "CLM-11499"})["error"]


def test_draft_letter_member():
    out = run_tool("draft_letter", {"letter_type": "member", "claim_id": "CLM-11499"})
    assert "The plan paid" in out["text"]


# ---------- run_tool safety ----------

def test_run_tool_unknown_tool():
    assert "Unknown tool" in run_tool("delete_everything", {})["error"]


def test_run_tool_missing_argument():
    assert "claim_id" in run_tool("get_claim", {})["error"]


# ---------- long-term memory notes (memory.py; no model needed) ----------

def test_member_notes_round_trip():
    from copilot import memory
    # Your real payer.db may already hold notes, so check the newest one only.
    memory.add_note("member", "test note for M-00142", "M-00142")
    memory.add_note("analyst", "test preference")
    assert memory.member_notes("M-00142")[0] == "test note for M-00142"
    assert "test note for M-00142" not in memory.member_notes("M-00217")
    assert memory.analyst_preferences()[0] == "test preference"


def test_notes_come_only_from_what_happened():
    from copilot import memory
    letter = {"tool": "draft_letter", "result": {"letter_type": "appeal", "claim_id": "CLM-10482"}}
    failed = {"tool": "draft_letter", "result": {"error": "not denied"}}
    assert memory.notes_from_run({"evidence": [letter, failed]}) == [
        ("M-00142", "appeal letter drafted for CLM-10482 on 2026-11-15")]
    args = {"member_id": "M-00217", "procedure_code": "73721", "recommendation": "approve", "rationale": "x"}
    rejected = {"approval": {"decision": "reject", "approver": "Nick", "arguments": args}}
    assert "rejected by Nick" in memory.notes_from_run(rejected)[0][1]
    assert memory.notes_from_run({"evidence": []}) == []


# ---------- the reviewer's fact lookup (plain code, no model) ----------


def test_check_facts_finds_dates_ids_and_amounts():
    from copilot.agents.reviewer import check_facts

    sources = '{"claim_id": "CLM-11498", "service_date": "2026-09-22", "billed_amount": 1240.0, "code": "CO-197"}'
    draft = ("CLM-11498 on September 22, 2026 (2026-09-22) was billed $1,240.00 and denied CO-197. "
             "CLM-99999 on 2026-12-01 for $55.")
    found, not_found = check_facts(draft, sources)
    assert found == ["CLM-11498", "CO-197", "2026-09-22", "September 22, 2026", "$1,240.00"]
    assert not_found == ["CLM-99999", "2026-12-01", "$55"]
```

### `config.yaml`

```yaml
# Payer Copilot settings. Edit this file, not the code.

llm:
  base_url: "http://localhost:1235/v1"   # LM Studio local server
  api_key: "lm-studio"                    # LM Studio ignores it, but the client needs a value
  chat_model: "google/gemma-4-12b-qat"  # run: uv run python -m copilot.llm
  embedding_model: "text-embedding-nomic-embed-text-v1.5"
  embedding_document_prefix: "search_document: "   # nomic-embed-text wants these task prefixes
  embedding_query_prefix: "search_query: "
  mode: "json_action"                     # json_action (default) or native_tools
  temperature: 0.0                        # routing, tool choice and review
  max_tokens: 4096                        # cap on one reply, including hidden "thinking" tokens
  timeout_seconds: 300
  thinking:               # let the model think (hidden reasoning) before replying? on = slower, off = fast
    agents: true          # claims, benefits and prior auth: the steps that reason over evidence
    supervisor: false     # picks a route and IDs
    reviewer: false       # checks a draft against three rules; with thinking on it ran out of room
    summary: false        # folds old turns into the session summary

data:
  db_path: "data/payer.db"
  policies_dir: "data/policies"
  outbox_dir: "outbox"
  chroma_dir: "data/chroma"   # the vector index, rebuilt by: uv run python -m copilot.rag.ingest
  policy_top_k: 3             # passages search_policy returns
  checkpoint_db: "data/checkpoints.db"   # LangGraph saves paused and finished runs here
  today: "2026-11-15"   # the app's fixed "today"; must match TODAY in data/generate.py

agents:
  max_tool_calls: 4     # per run; design limit
```
