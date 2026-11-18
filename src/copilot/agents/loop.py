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
from collections.abc import Callable

import yaml
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from copilot import guardrails, tracing
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
              run_id: str | None = None, gated: tuple[str, ...] = (),
              finish_check: Callable[[list[Evidence], str], str | None] | None = None) -> AgentResult:
    """Run one specialist on one question and return its answer and evidence.

    `gated` names tools that need a person's approval; they end the loop
    instead of running. `finish_check`, if given, looks at the evidence and the answer
    when the model gives a final answer, and may send it back once with a reason
    (prior auth: a required auth must reach a person; benefits: name the source).
    """
    guardrails.check_allow_list(agent, [t.name for t in tools])
    run_id = run_id or tracing.new_run_id()
    limit = max_tool_calls()
    messages: list[BaseMessage] = [SystemMessage(content=system_prompt), HumanMessage(content=question)]
    evidence: list[Evidence] = []
    tool_calls = 0
    # Number steps after any earlier steps of this run (the supervisor, or a first attempt).
    first_step = max((s["step"] for s in tracing.read_run(run_id)), default=0) + 1
    sent_back = False
    think = None  # None: use config.yaml. False: thinking off for one retry after a cut-off.
    # Room for every tool call, one final answer and two invalid replies.
    for step in range(first_step, first_step + limit + 3):
        # At the limit only final_answer (and any gated tool) remains.
        allowed = tools if tool_calls < limit else [t for t in tools if t.name in gated]
        prompt = _as_dicts(messages)
        start = time.perf_counter()
        try:
            decision = decide_action(messages, allowed, role=agent, thinking=think)
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
            reason = None if sent_back or finish_check is None else finish_check(evidence, action.arguments.get("answer", ""))
            if reason:
                sent_back = True
                tracing.write_step(run_id, agent, step, **{**trace_fields, "note": f"sent back: {reason}"})
                messages.append(AIMessage(content=json.dumps(action.model_dump())))
                messages.append(HumanMessage(content=reason))
                continue
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
            finish = f"{' or '.join(gated)} or your final answer" if gated else "your final answer"
            note = f"\n\nYou have used all your lookups. Reply now with {finish}, from the results above."
        messages.append(AIMessage(content=json.dumps(action.model_dump())))
        messages.append(HumanMessage(content=f"Tool result from {action.action}:\n{json.dumps(result)}{note}"))

    return AgentResult(run_id=run_id, agent=agent, question=question, answer=SAFE_FALLBACK,
                       tool_calls=tool_calls, stopped_reason="step_limit", evidence=evidence)
