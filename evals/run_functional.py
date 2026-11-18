"""Functional tests: harder questions, to find what the copilot still gets wrong.

    uv run python evals/run_functional.py              all cases in functional_cases.json
    uv run python evals/run_functional.py fa01 fs04    only these cases

Unlike run_evals.py, these have no targets. Each case prints pass or FAIL with
the checks it missed and why the case exists, so a FAIL points at something to
fix. Every check is plain code, like the scorecard:

- route: the supervisor's route (or one of a list)
- tools: every expected tool was called
- facts: every expected value is in the answer (a list means any one of them)
- absent: none of these values is in the answer
- citation: one of the documents is named
- paused / recommendation: the approval box appeared (or didn't), with this recommendation
- search_all_claims: search_claims was never filtered by status
- nothing_written: no prior auth was submitted
- masked: these values never reached the model
- claim_in_focus: a follow-up picked up the claim from the earlier question
- not_repeated: the answer is not the same as the earlier answer

A case with "setup" first asks those questions in the same session. The run
never approves, so nothing is written to the auth queue.
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from copilot import tracing
from copilot.graph import new_question, open_graph

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_evals import SPECIALISTS, has_any, normalize, settings  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
CASES_FILE = EVAL_DIR / "functional_cases.json"
RESULTS_DIR = EVAL_DIR / "results"


def check_case(case: dict[str, Any], state: dict[str, Any], steps: list[dict[str, Any]],
               earlier_answer: str) -> list[str]:
    """What the run got wrong, as short lines. An empty list means the case passed."""
    answer = state.get("answer", "")
    agent_steps = [s for s in steps if s["agent"] in SPECIALISTS]
    tools_used = [s.get("action") for s in agent_steps]
    pending = state.get("pending_approval") or {}
    missed = []

    routes = case["route"] if isinstance(case["route"], list) else [case["route"]]
    if state.get("route") not in routes:
        missed.append(f"route {state.get('route')!r}, expected {' or '.join(routes)}")
    missed += [f"tool {t} not called" for t in case.get("tools", []) if t not in tools_used]
    for fact in case.get("facts", []):
        if not has_any(answer, fact):
            missed.append(f"fact missing: {' or '.join(fact) if isinstance(fact, list) else fact}")
    missed += [f"should not say: {v}" for v in case.get("absent", []) if normalize(v) in normalize(answer)]
    if "citation" in case and not has_any(answer, case["citation"]):
        missed.append(f"citation missing: {' or '.join(case['citation'])}")
    if "paused" in case and bool(state.get("__interrupt__")) != case["paused"]:
        missed.append("approval box expected" if case["paused"] else "approval box should not appear")
    if "recommendation" in case and pending:
        got = pending.get("arguments", {}).get("recommendation")
        if got not in case["recommendation"]:
            missed.append(f"recommendation {got!r}, expected {' or '.join(case['recommendation'])}")
    if case.get("search_all_claims"):
        filtered = [s["arguments"].get("status") for s in agent_steps
                    if s.get("action") == "search_claims" and s["arguments"].get("status")]
        if filtered:
            missed.append(f"search_claims filtered by status {filtered} (hides other claims)")
    if case.get("nothing_written") and state.get("submission"):
        missed.append(f"a prior auth was written: {state['submission']}")
    if "masked" in case:
        sent = json.dumps([s.get("prompt") for s in steps])
        missed += [f"reached the model unmasked: {v}" for v in case["masked"] if v in sent]
    if "claim_in_focus" in case and state.get("claim_id") != case["claim_in_focus"]:
        missed.append(f"claim in focus {state.get('claim_id')!r}, expected {case['claim_in_focus']}")
    if case.get("not_repeated") and earlier_answer and answer.strip() == earlier_answer.strip():
        missed.append("gave the same answer as last time")
    return missed


def run_case(graph: Any, case: dict[str, Any], stamp: str) -> dict[str, Any]:
    """Ask any setup questions, then the case's question, in one fresh session."""
    config = {"configurable": {"thread_id": f"functional-{stamp}-{case['id']}"}}
    start = time.perf_counter()
    earlier_answer, state, error = "", {}, None
    try:
        for question in case.get("setup", []):
            earlier_answer = graph.invoke(new_question(question, tracing.new_run_id()), config).get("answer", "")
        run_id = tracing.new_run_id()
        state = graph.invoke(new_question(case["question"], run_id), config)
        missed = check_case(case, state, tracing.read_run(run_id), earlier_answer)
    except Exception as e:  # one broken case must not stop the whole run
        run_id, error = None, f"{type(e).__name__}: {e}"
        missed = [f"error {error}"]
    return {"id": case["id"], "question": case["question"], "why": case["why"], "passed": not missed,
            "missed": missed, "route": state.get("route"), "answer": state.get("answer", ""),
            "paused_for_approval": bool(state.get("__interrupt__")), "run_id": run_id, "error": error,
            "seconds": round(time.perf_counter() - start, 1)}


def main() -> None:
    wanted = sys.argv[1:]
    cases = json.loads(CASES_FILE.read_text())["cases"]
    if wanted:
        cases = [c for c in cases if c["id"] in wanted]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    print(f"Running {len(cases)} functional cases.\n")
    graph = open_graph()
    results = []
    for case in cases:
        print(f"{case['id']}  {case['question'][:72]}", flush=True)
        result = run_case(graph, case, stamp)
        results.append(result)
        print(f"      {'pass' if result['passed'] else 'FAIL'}  {result['seconds']}s", flush=True)
        if not result["passed"]:
            for line in result["missed"]:
                print(f"        - {line}")
            print(f"        why this case: {case['why']}")

    failed = [r for r in results if not r["passed"]]
    print(f"\n{len(results) - len(failed)} of {len(results)} passed, "
          f"{round(sum(r['seconds'] for r in results) / 60, 1)} min in all.")
    if failed:
        print("Failed: " + ", ".join(r["id"] for r in failed)
              + ". Open a failed case's trace with: uv run python -m copilot.tracing RUN_ID (run IDs are in the saved file)")
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{stamp}_functional.json"
    out.write_text(json.dumps({"settings": settings(), "cases": results}, indent=2))
    print(f"Saved {out.relative_to(EVAL_DIR.parent)}")


if __name__ == "__main__":
    main()
