"""Milestone 0 smoke test: 10 cases, run in both adapter modes.

Each case gives the model an agent's instructions, that agent's tools and
one request, and states which action (and which key arguments) a correct
reply contains. A case passes only if the reply is a valid Action AND picks
the expected action with the expected IDs.

Design check: json_action must pass at least 9 of 10.
native_tools is scored for comparison only.

Run it two ways (LM Studio must be running):
    uv run python tests/test_smoke_llm.py      # prints a scorecard
    uv run pytest tests/test_smoke_llm.py -s   # same, as a pass/fail test
"""

import time

from langchain_core.messages import HumanMessage, SystemMessage

from copilot.llm import ActionError, decide_action
from copilot.schemas import FINAL_ANSWER
from copilot.tools.claims import EXPLAIN_DENIAL_CODE as EXPLAIN_DENIAL
from copilot.tools.claims import GET_CLAIM, GET_MEMBER, SEARCH_CLAIMS
from copilot.tools.letters import DRAFT_LETTER
from copilot.tools.policy import SEARCH_POLICY
from copilot.tools.prior_auth import CHECK_AUTH_REQUIRED as CHECK_AUTH
from copilot.tools.prior_auth import GET_AUTH_CRITERIA as GET_CRITERIA
from copilot.tools.prior_auth import SUBMIT_PRIOR_AUTH as SUBMIT_AUTH

# The tool specs now come from the real tool modules (milestone 2). Only the
# model's choice is tested here; no tool is run.

# ----- Each agent sees only its own tools (allow-lists from the design) -----

AGENTS = {
    "claims": (
        "You are the claims agent for Acme Health Plan's operations team. "
        "Explain a claim's status, amounts and denial reason using tools. "
        "Never guess facts; look them up.",
        [GET_MEMBER, GET_CLAIM, SEARCH_CLAIMS, EXPLAIN_DENIAL, SEARCH_POLICY, DRAFT_LETTER],
    ),
    "benefits": (
        "You are the benefits agent for Acme Health Plan. Answer coverage "
        "questions from the plan documents only, using search_policy.",
        [SEARCH_POLICY],
    ),
    "prior_auth": (
        "You are the prior authorization agent for Acme Health Plan. Check "
        "eligibility, whether auth is required, and which criteria are met. "
        "You recommend; a person decides.",
        [GET_MEMBER, CHECK_AUTH, GET_CRITERIA, SEARCH_POLICY, SUBMIT_AUTH],
    ),
}

# ----- The 10 cases: agent, request, expected action, expected arguments -----

CASES = [
    ("claims", "Why was claim CLM-10482 denied?", "get_claim", {"claim_id": "CLM-10482"}),
    ("claims", "List the denied claims for member M-00217.", "search_claims", {"member_id": "M-00217", "status": "denied"}),
    ("claims", "What does denial code CO-197 mean?", "explain_denial_code", {"code": "CO-197"}),
    ("claims", "Draft the appeal letter for claim CLM-10482.", "draft_letter", {"letter_type": "appeal", "claim_id": "CLM-10482"}),
    ("benefits", "Does the Silver plan cover physical therapy, and is there a visit limit?", "search_policy", {}),
    ("prior_auth", "Does procedure 73721 need prior auth on the Gold plan?", "check_auth_required", {"procedure_code": "73721", "plan": "Gold"}),
    ("prior_auth", "What criteria must be met for procedure 73721?", "get_auth_criteria", {"procedure_code": "73721"}),
    ("prior_auth", "Member M-00217 needs a knee MRI. Start by checking their eligibility.", "get_member", {"member_id": "M-00217"}),
    (
        "claims",
        "Why was claim CLM-10482 denied?\n\n"
        'Tool result from get_claim: {"claim_id": "CLM-10482", "status": "denied", '
        '"billed": 1240.00, "denial_code": "CO-197", "denial_meaning": "Prior '
        'authorization was required but not obtained."}\n\n'
        "You now have the facts. Answer the analyst.",
        FINAL_ANSWER,
        {},
    ),
    ("claims", "Thanks, that is all I needed.", FINAL_ANSWER, {}),
]

PASS_TARGET = 9


def run_case(mode: str, case: tuple) -> tuple[bool, str, float]:
    """Run one case. Return (passed, short note, seconds taken)."""
    agent, request, want_action, want_args = case
    system_prompt, tools = AGENTS[agent]
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=request)]
    start = time.perf_counter()
    try:
        action = decide_action(messages, tools, mode=mode).action
    except ActionError as e:
        return False, f"invalid: {e} | raw: {e.raw[:200]}", time.perf_counter() - start
    except Exception as e:  # server down, timeout, etc.
        return False, f"error: {type(e).__name__}: {e}", time.perf_counter() - start
    seconds = time.perf_counter() - start
    got = f"{action.action} {action.arguments}"
    if action.action != want_action:
        return False, f"wrong action, got {got}", seconds
    for key, value in want_args.items():
        if str(action.arguments.get(key, "")).strip().upper() != value.upper():
            return False, f"wrong {key}, got {got}", seconds
    return True, got, seconds


def run_mode(mode: str) -> int:
    """Run all cases in one mode, print a scorecard, return the pass count."""
    print(f"\n=== mode: {mode} ===")
    passed = 0
    for i, case in enumerate(CASES, start=1):
        ok, note, seconds = run_case(mode, case)
        passed += ok
        print(f"{i:>2}. {'PASS' if ok else 'FAIL'}  {seconds:5.1f}s  {note[:110]}")
    print(f"Score {mode}: {passed}/{len(CASES)}")
    return passed


def test_json_action_smoke() -> None:
    """Design check for milestone 0."""
    assert run_mode("json_action") >= PASS_TARGET


def test_native_tools_smoke() -> None:
    """Scored for comparison; never fails the build."""
    run_mode("native_tools")


if __name__ == "__main__":
    json_score = run_mode("json_action")
    native_score = run_mode("native_tools")
    print("\n=== summary ===")
    print(f"json_action : {json_score}/10  (target {PASS_TARGET})")
    print(f"native_tools: {native_score}/10  (comparison only)")
    print("Milestone 0 check:", "PASSED" if json_score >= PASS_TARGET else "FAILED")
