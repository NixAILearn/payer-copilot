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
    An agent ("claims", "benefits", "prior_auth") uses its own line if
    config.yaml has one, otherwise the shared "agents" line.
    """
    settings = load_config().get("thinking", {})
    if role in settings:
        return bool(settings[role])
    if role in ("claims", "benefits", "prior_auth"):
        return bool(settings.get("agents", True))
    return True


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
