# Milestone 0: Setup and smoke test

**Goal:** call Gemma from Python through one adapter, in both modes, and prove `json_action` picks the right action on at least 9 of 10 cases.

## 1. Versions I pinned (checked against PyPI and the docs on 17 Nov 2026)

| Package | Version | Why this one |
| --- | --- | --- |
| langgraph | 1.2.19 | Latest release older than two weeks. Has `interrupt()` and `Command(resume=...)`, which is exactly the pause-and-approve flow the design needs for prior auth. |
| langgraph-checkpoint-sqlite | 3.1.3 | Saves graph state to SQLite (milestone 5). |
| langchain-openai | 1.7.3 | The client that talks to LM Studio's OpenAI-style server. |
| langchain-core | 1.7.3 | Message types used by the adapter. |
| chromadb | 1.5.9 | Current release. On-disk vector index (milestone 4). |
| pydantic | 2.14.2 | Typed models for actions and tool inputs. |
| pyyaml | 6.0.3 | Reads `config.yaml`. |
| streamlit | 1.66.1 | UI (milestone 6). |
| pytest | 9.2.0 | Tests. |

I skipped versions released in the last two weeks (several came out today) because brand-new releases are the most likely to break. `pyproject.toml` also tells uv to ignore anything newer than 3 Nov 2026, and `uv.lock` records the exact version of every package underneath these, so your install matches mine.

## 2. LM Studio settings to apply

From the current LM Studio docs (Developer > OpenAI-compatible API):

1. **Use the GGUF build of Gemma 4 12B QAT, not MLX.** On GGUF, LM Studio enforces our JSON schema with llama.cpp grammar sampling, which is what the design relies on. (MLX uses a different engine.) The model's card in My Models shows its format.
2. **Load both models yourself**, from the model picker at the top of the window: the Gemma chat model and your embedding model.
   - Chat model load settings: **Context Length 8192**, GPU Offload at the maximum, leave the rest at defaults.
3. **Developer tab > Server Settings:** turn **Auto-Evict off**. With it on, LM Studio keeps only one auto-loaded model in memory, so the app would unload Gemma each time it needs embeddings. Leave Port at **1234**. You don't need "Serve on Local Network" or CORS.
4. **Developer tab: Start the server** (status should say Running at `http://localhost:1234`).
5. Temperature and response length are set by our code (`config.yaml`), so nothing to change in the app's sampling settings.

Note: the docs list Qwen, Llama and Mistral as "native" tool-calling models. Gemma isn't on that list, so in `native_tools` mode LM Studio uses its generic tool format and results can vary. That is why the design makes `json_action` the default, and the smoke test measures both.

## 3. Files in this milestone

| File | What it does, in plain words |
| --- | --- |
| `pyproject.toml` | The project's shopping list: Python 3.12 and the exact package versions. `uv sync` reads it and installs them into a private `.venv` folder. |
| `uv.lock` | uv's receipt: the exact version of every package, including the ones our packages need. You never edit it. |
| `.python-version` | Tells uv to use Python 3.12. |
| `config.yaml` | All settings in one place: server URL, model names, adapter mode, temperature. You change behaviour here without touching code. |
| `src/copilot/__init__.py` | Marks `copilot` as a Python package so other files can `import copilot...`. |
| `src/copilot/schemas.py` | The shapes of data. `Action` is what an agent decides ("call this tool with these arguments", or "final answer"). `ToolSpec` describes a tool to the model. One small model per tool says which arguments it takes. Pydantic checks real data against these shapes. |
| `src/copilot/llm.py` | The **adapter**, the only place that talks to the model. `decide_action()` asks "what's your next step?" and returns an `Action`, in either mode. In `json_action` it sends a JSON schema so LM Studio can only produce allowed actions. In `native_tools` it uses the model's own tool calling. Either way it validates the result before returning. Running it directly lists the models LM Studio serves. |
| `tests/test_smoke_llm.py` | 10 realistic requests (from the three demo stories), each with the right answer. Runs them in both modes and prints a scorecard. A case passes only if the action is valid **and** it's the right tool with the right IDs. (The design says "valid"; in `json_action` mode valid is nearly guaranteed by the schema, so I also require it to be correct, which is what actually tells you whether the model is good enough.) |
| `README.md` | Short project front page; grows each milestone. |
| `LEARNINGS.md` | Your 5 lines per milestone. |
| `.gitignore` | Files git should ignore (the virtual environment, databases, traces). |

The real tool code (database lookups etc.) comes in milestone 2. For now the model only has to *choose* the right tool; nothing is executed.

## 4. Commands (Terminal on your Mac)

```bash
# 1. Go to where you put the payer-copilot folder, for example:
cd ~/Projects/payer-copilot

# 2. Make sure uv has Python 3.12, then install the pinned packages
uv python install 3.12
uv sync

# 3. Check LM Studio is reachable and see the model IDs it serves
uv run python -m copilot.llm
```

Expected output of step 3 (your IDs will differ):

```text
LM Studio server: http://localhost:1234/v1
Models available:
  - google/gemma-4-12b-qat
  - text-embedding-nomic-embed-text-v1.5
config chat_model: PASTE-CHAT-MODEL-ID-HERE  [NOT FOUND, copy an ID from the list above]
config embedding_model: PASTE-EMBEDDING-MODEL-ID-HERE  [NOT FOUND, copy an ID from the list above]
config mode: json_action
```

Open `config.yaml`, paste the two IDs from that list into `chat_model` and `embedding_model`, save, and run step 3 again. Both lines should now end in `[OK]`.

```bash
# 4. Run the smoke test (both modes, about 1 to 3 minutes)
uv run python tests/test_smoke_llm.py
```

Expected output (shape; times and exact arguments will vary):

```text
=== mode: json_action ===
 1. PASS    2.1s  get_claim {'claim_id': 'CLM-10482'}
 2. PASS    1.4s  search_claims {'member_id': 'M-00217', 'status': 'denied'}
 3. PASS    1.2s  explain_denial_code {'code': 'CO-197'}
 4. PASS    1.5s  draft_letter {'letter_type': 'appeal', 'claim_id': 'CLM-10482'}
 5. PASS    1.6s  search_policy {'query': 'Silver plan physical therapy visit limit'}
 6. PASS    1.3s  check_auth_required {'procedure_code': '73721', 'plan': 'Gold'}
 7. PASS    1.1s  get_auth_criteria {'procedure_code': '73721'}
 8. PASS    1.2s  get_member {'member_id': 'M-00217'}
 9. PASS    3.0s  final_answer {'answer': 'Claim CLM-10482 was denied because ...'}
10. PASS    1.8s  final_answer {'answer': "You're welcome! ..."}
Score json_action: 10/10

=== mode: native_tools ===
 ...
Score native_tools: 7/10

=== summary ===
json_action : 10/10  (target 9)
native_tools: 7/10  (comparison only)
Milestone 0 check: PASSED
```

The first call is often slower because the model warms up. A FAIL line shows what the model returned instead, which is the useful part.

```bash
# 5. Optional: the same check as a pytest test
uv run pytest -s
```

Expected last line: `2 passed`.

**The check passes** when the summary says `Milestone 0 check: PASSED` (json_action 9/10 or better). If it says FAILED, or anything errors, send me the full error text and the FAIL lines. Per the design, if `json_action` is below 9/10 the fix is to try a non-QAT quantization of the same model before going further.

Please also tell me the `native_tools` score; it's a data point for the write-up.

## 5. Check your understanding

1. In `json_action` mode, why can't the model reply with a tool name that isn't in the agent's list, and what still *can* go wrong that the smoke test is there to catch?
2. Why does every part of the app call `decide_action()` in `llm.py` instead of creating its own connection to LM Studio? Name one thing you'd change in only one place because of this.
3. Why did we turn Auto-Evict off in LM Studio, and what would you expect to happen in milestone 4 if it were left on?

After you've run it, write your 5 lines in `LEARNINGS.md`.

## 6. Full file contents

The same files are in this folder; they're repeated here so you can read them in one place. (`uv.lock` is left out because it is long and machine-written.)

### `pyproject.toml`

````toml
[project]
name = "payer-copilot"
version = "0.1.0"
description = "Local multi-agent POC for a fictional health plan. Synthetic data only."
readme = "README.md"
requires-python = ">=3.12,<3.13"
dependencies = [
    "langgraph==1.2.19",
    "langgraph-checkpoint-sqlite==3.1.3",
    "langchain-core==1.7.3",
    "langchain-openai==1.7.3",
    "chromadb==1.5.9",
    "pydantic==2.14.2",
    "pyyaml==6.0.3",
    "streamlit==1.66.1",
    "pytest==9.2.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/copilot"]

[tool.uv]
# Ignore any package released after this date, so the install is the same
# on every run even when new versions come out.
exclude-newer = "2026-11-03T00:00:00Z"

[tool.pytest.ini_options]
testpaths = ["tests"]
````

### `.python-version`

````text
3.12
````

### `config.yaml`

````yaml
# Payer Copilot settings. Edit this file, not the code.

llm:
  base_url: "http://localhost:1234/v1"   # LM Studio local server
  api_key: "lm-studio"                    # LM Studio ignores it, but the client needs a value
  chat_model: "PASTE-CHAT-MODEL-ID-HERE"  # run: uv run python -m copilot.llm
  embedding_model: "PASTE-EMBEDDING-MODEL-ID-HERE"
  mode: "json_action"                     # json_action (default) or native_tools
  temperature: 0.0                        # routing, tool choice and review
  max_tokens: 512                         # cap on one reply, keeps calls fast
  timeout_seconds: 120
````

### `.gitignore`

````text
.venv/
__pycache__/
*.pyc
.pytest_cache/
data/payer.db
data/chroma/
evals/results/
traces/
outbox/
````

### `README.md`

````markdown
# Payer Copilot

A local multi-agent assistant for "Acme Health Plan", a made-up health payer.
It runs on a MacBook against Gemma 4 12B QAT in LM Studio. All data is synthetic.

## Status

- [x] Milestone 0: setup and smoke test
- [ ] Milestone 1: synthetic data
- [ ] Milestone 2: tools
- [ ] Milestone 3: one agent, end to end
- [ ] Milestone 4: RAG and benefits agent
- [ ] Milestone 5: supervisor and prior auth with approval
- [ ] Milestone 6: reviewer, memory and UI
- [ ] Milestone 7: evals, demo and write-up

## Run

```bash
uv sync                                   # install pinned packages
uv run python -m copilot.llm              # check LM Studio is reachable
uv run python tests/test_smoke_llm.py     # 10-case smoke test, both modes
```

The full write-up (architecture, results, limits) comes in milestone 7.
````

### `LEARNINGS.md`

````markdown
# Learnings

Write 5 lines in your own words after each milestone.

## Milestone 0: Setup and smoke test

1.
2.
3.
4.
5.
````

### `src/copilot/__init__.py`

````python
"""Payer Copilot: a local multi-agent POC with synthetic data only."""
````

### `src/copilot/schemas.py`

````python
"""Pydantic models shared across the app.

Milestone 0 holds only what the model adapter needs: the Action an agent
returns, the ToolSpec that describes a tool to the model, and the input
model for each of the nine tools in the design. Tool outputs and graph
state are added in later milestones.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FINAL_ANSWER = "final_answer"


class Action(BaseModel):
    """One decision from an agent: call a tool, or give the final answer."""

    action: str = Field(description="A tool name, or 'final_answer'.")
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolSpec(BaseModel):
    """What the model is told about one tool: its name, a one-line
    description, and the Pydantic model that its arguments must match."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    args_model: type[BaseModel]


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
````

### `src/copilot/llm.py`

````python
"""The model adapter. Every call to the model in this project goes through here.

Two modes, chosen in config.yaml (llm.mode):

- json_action (default): we ask for one JSON object
  {"action": ..., "arguments": {...}} and give LM Studio a JSON schema.
  LM Studio constrains the model to that schema, so the reply always parses.
- native_tools: we pass the tools in the OpenAI "tools" format and read the
  model's tool_calls. This depends on the model's own tool-calling skill.

Both modes return the same Action, so the rest of the app never needs to
know which mode ran.

Run `uv run python -m copilot.llm` to check that LM Studio is reachable and
to list the model IDs it serves.
"""

import json
from pathlib import Path
from typing import Any

import yaml
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import OpenAI
from pydantic import ValidationError

from copilot.schemas import FINAL_ANSWER, Action, FinalAnswerArgs, ToolSpec

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"
MODES = ("json_action", "native_tools")


class ActionError(Exception):
    """The model's reply could not be turned into a valid Action."""

    def __init__(self, message: str, raw: str) -> None:
        super().__init__(message)
        self.raw = raw


def load_config() -> dict[str, Any]:
    """Read the llm section of config.yaml."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)["llm"]


def get_chat_model(temperature: float | None = None) -> ChatOpenAI:
    """Build the LangChain chat client that points at LM Studio."""
    cfg = load_config()
    return ChatOpenAI(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["chat_model"],
        temperature=cfg["temperature"] if temperature is None else temperature,
        max_tokens=cfg["max_tokens"],
        timeout=cfg["timeout_seconds"],
        max_retries=0,
    )


def decide_action(
    messages: list[BaseMessage],
    tools: list[ToolSpec],
    mode: str | None = None,
) -> Action:
    """Ask the model for its next step: one tool call or the final answer.

    `messages` is the conversation so far (system prompt first).
    `tools` is the allow-list for the calling agent.
    Raises ActionError if the reply is not a valid Action.
    """
    mode = mode or load_config()["mode"]
    if mode == "json_action":
        return _decide_json_action(messages, tools)
    if mode == "native_tools":
        return _decide_native_tools(messages, tools)
    raise ValueError(f"Unknown mode {mode!r}. Use one of {MODES}.")


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


def _decide_json_action(messages: list[BaseMessage], tools: list[ToolSpec]) -> Action:
    """json_action mode: schema-constrained JSON, then validate it."""
    prompt = _add_to_system_prompt(messages, _tool_list_prompt(tools))
    response_format = {
        "type": "json_schema",
        "json_schema": {"name": "action", "schema": _action_schema(tools)},
    }
    reply = get_chat_model().invoke(prompt, response_format=response_format)
    raw = str(reply.content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ActionError(f"Reply is not JSON: {e}", raw) from e
    action = Action(action=data.get("action", ""), arguments=data.get("arguments") or {})
    return _validate(action, tools, raw)


# ---------- native_tools mode ----------


def _decide_native_tools(messages: list[BaseMessage], tools: list[ToolSpec]) -> Action:
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
    reply = get_chat_model().bind_tools(openai_tools, tool_choice="auto").invoke(messages)
    raw = json.dumps({"content": reply.content, "tool_calls": reply.tool_calls})
    if reply.tool_calls:
        call = reply.tool_calls[0]  # one action per step, like json_action mode
        action = Action(action=call["name"], arguments=call["args"])
    else:
        action = Action(action=FINAL_ANSWER, arguments={"answer": str(reply.content)})
    return _validate(action, tools, raw)


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
````

### `tests/test_smoke_llm.py`

````python
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
from copilot.schemas import (
    FINAL_ANSWER,
    CheckAuthRequiredArgs,
    DraftLetterArgs,
    ExplainDenialCodeArgs,
    GetAuthCriteriaArgs,
    GetClaimArgs,
    GetMemberArgs,
    SearchClaimsArgs,
    SearchPolicyArgs,
    SubmitPriorAuthArgs,
    ToolSpec,
)

# ----- The nine tools from the design (descriptions only; code comes in M2) -----

GET_MEMBER = ToolSpec(name="get_member", description="Member profile, plan and eligibility dates by member ID.", args_model=GetMemberArgs)
GET_CLAIM = ToolSpec(name="get_claim", description="One claim with lines, amounts, status and denial code.", args_model=GetClaimArgs)
SEARCH_CLAIMS = ToolSpec(name="search_claims", description="A member's claims, filtered by date range or status.", args_model=SearchClaimsArgs)
EXPLAIN_DENIAL = ToolSpec(name="explain_denial_code", description="Plain-language meaning and usual next step for a denial code.", args_model=ExplainDenialCodeArgs)
SEARCH_POLICY = ToolSpec(name="search_policy", description="Top passages from plan and policy documents, with document and section.", args_model=SearchPolicyArgs)
CHECK_AUTH = ToolSpec(name="check_auth_required", description="Whether a procedure code needs prior auth on a given plan.", args_model=CheckAuthRequiredArgs)
GET_CRITERIA = ToolSpec(name="get_auth_criteria", description="The checklist of criteria for a procedure.", args_model=GetAuthCriteriaArgs)
SUBMIT_AUTH = ToolSpec(name="submit_prior_auth", description="Writes a request with the recommendation to the auth queue. Needs human approval.", args_model=SubmitPriorAuthArgs)
DRAFT_LETTER = ToolSpec(name="draft_letter", description="Fills an appeal or member letter template for a claim.", args_model=DraftLetterArgs)

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
        action = decide_action(messages, tools, mode=mode)
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
````
