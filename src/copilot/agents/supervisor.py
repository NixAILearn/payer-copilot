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

- claims: questions about a specific claim (status, amounts, why it was denied, appeal letters), a member's eligibility, claim history or what has been done for them, or what a denial code means.
- benefits: what a plan (Bronze, Silver or Gold) covers in general, limits, costs, rules.
- prior_auth: whether a member's planned procedure needs prior authorization or meets its criteria.
- clarify: the request is about this work but too vague to route, such as a member with no question. Ask one short question.
- out_of_scope: the request is not about claims, plan coverage or prior authorization at all (coding, recipes, general chat, medical advice). No question back.

If a request mixes work with something out of scope, route the work part and put the rest in out_of_scope_part. Never ask the analyst to choose between them.
If your last reply was a clarifying question and the new message still gives you no claim, coverage or prior auth request, route out_of_scope. Never ask the same question twice.

Copy any member ID (like M-00217) and claim ID (like CLM-10482) exactly as written. Leave them empty if not given.
If the request refers to something earlier ("that claim", "this member"), it is about the IDs in focus; route it as if they were named.

Examples:
"Why was claim CLM-10482 denied?" -> claims, claim_id CLM-10482
"Does Gold cover chiropractic care?" -> benefits
"Member M-00217 needs a knee MRI. Is prior auth required?" -> prior_auth, member_id M-00217
"What has been done for member M-00217?" -> claims, member_id M-00217
"Can you help with this member?" (nothing in focus) -> clarify
"What's a good recipe for banana bread?" -> out_of_scope
"What dose of ibuprofen should member M-00217 take?" -> out_of_scope (medical advice)
"Member M-00217 wants their claim details and help coding an HTML game" -> claims, member_id M-00217, out_of_scope_part "help coding an HTML game"
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
    step = max((s["step"] for s in tracing.read_run(run_id)), default=-1) + 1  # 0, or 1 after a guard step
    tracing.write_step(run_id, "supervisor", step, prompt=[{"role": "human", "content": content}],
                       raw_output=result.raw, action="route", arguments=result.data,
                       input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                       latency_s=result.latency_s)
    return RouteDecision.model_validate(result.data)
