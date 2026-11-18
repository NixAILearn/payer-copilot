"""LangGraph wiring: one entry point for every request.

    guard --(injection flagged)--> "can't act on that" ---------------------------------------------> remember
          --> supervisor --> claims -----\\
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

from copilot import guardrails, memory, tracing
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
SCOPE_ANSWER = ("I can only help with claims, plan coverage and prior authorizations for Acme Health Plan "
                "members. Ask me about a claim, what a plan covers, or whether a procedure needs prior auth.")
SCOPE_NOTE = "I left out \"{part}\": I can only help with claims, plan coverage and prior authorizations."
REVIEWER_FAILED = ("This answer needs human review. The compliance reviewer couldn't finish checking it, "
                   "so nothing was submitted. The unchecked draft was:\n\n{draft}")


def new_question(question: str, run_id: str) -> dict:
    """The input for a new question: sets the question and clears last question's results.
    Session fields (history, summary, IDs in focus) are left as they are."""
    return {"run_id": run_id, "question": question, "route": "", "answer": "", "evidence": [],
            "tool_calls": 0, "review": None, "review_attempts": 0, "pending_approval": None,
            "approval": None, "submission": None, "declined": None}


# ---------- nodes: each takes the state and returns the fields it changes ----------


def guard_node(state: CopilotState) -> dict:
    """Plain code, no model: mask SSN- and phone-shaped text, stop injection attempts."""
    question, masked = guardrails.mask_identifiers(state["question"])
    phrase = guardrails.flag_injection(question)
    if masked or phrase:
        tracing.write_step(state["run_id"], "guard", 0, action="blocked" if phrase else "masked",
                           arguments={"masked": masked, "injection": phrase})
    if phrase:
        return {"question": question, "route": "blocked",
                "answer": guardrails.BLOCKED_ANSWER.format(phrase=phrase)}
    return {"question": question}


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
    elif decision.route == "out_of_scope":
        update["answer"] = SCOPE_ANSWER  # a fixed reply, so it never turns into a loop of questions
    elif decision.out_of_scope_part:
        update["declined"] = decision.out_of_scope_part  # answer the work part, leave this out
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
    if state.get("declined"):
        text += (f"\n\n--- Leave out ---\nThe request also asks about: {state['declined']}. That is not "
                 "your job. Don't answer it or mention it; answer only the claims, coverage or prior auth part.")
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
    if state.get("pending_approval") and not verdict_dict["passed"]:
        verdict_dict = _waive_rule_2(verdict_dict)
    update = {"review": verdict_dict, "review_attempts": attempts}
    if not verdict_dict["passed"] and attempts >= MAX_REVIEWS:
        update["answer"] = NEEDS_HUMAN.format(reasons="\n- ".join(verdict_dict["reasons"]))
        update["pending_approval"] = None  # never submit a draft that failed review
    return update


def _waive_rule_2(verdict: dict) -> dict:
    """Rule 2 (no coverage decision) can't be broken by a proposed prior auth:
    nothing is decided until a named person approves it. The reviewer still
    read "deny" as a decision now and then, so plain code drops those reasons."""
    kept = [r for r in verdict["reasons"] if not r.strip().lower().startswith("rule 2")]
    if len(kept) == len(verdict["reasons"]):
        return verdict
    return {"passed": not kept, "reasons": kept + ["Rule 2 reasons dropped: a proposed prior auth is "
                                                   "only a recommendation until a person approves it."]}


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
    answer = state.get("answer", "")
    if state.get("declined"):
        answer += "\n\n" + SCOPE_NOTE.format(part=state["declined"])
    history, summary = memory.add_turn(state.get("history") or [], state.get("summary", ""),
                                       state["question"], answer)
    return {"history": history, "summary": summary, "answer": answer}


# ---------- wiring ----------


def build_graph(checkpointer: SqliteSaver) -> CompiledStateGraph:
    """Connect the nodes. Conditional edges pick the next node from the state."""
    graph = StateGraph(CopilotState)
    for name, node in [("guard", guard_node), ("supervisor", supervisor_node), ("claims", claims_node),
                       ("benefits", benefits_node), ("prior_auth", prior_auth_node),
                       ("reviewer", reviewer_node), ("approval", approval_node),
                       ("remember", remember_node)]:
        graph.add_node(name, node)

    graph.add_edge(START, "guard")
    graph.add_conditional_edges("guard", lambda s: "remember" if s.get("route") == "blocked" else "supervisor",
                                ["supervisor", "remember"])
    graph.add_conditional_edges("supervisor", lambda s: s["route"],
                                {"claims": "claims", "benefits": "benefits",
                                 "prior_auth": "prior_auth", "clarify": "remember",
                                 "out_of_scope": "remember"})
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
