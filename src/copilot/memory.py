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
