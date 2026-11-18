# Milestone 2: Tools

**Goal:** the nine tools from the design, each with a typed input, a typed output and a one-line description, callable from the terminal. **Check:** unit tests pass for all 9 tools.

## 1. What's new

| File | What it does, in plain words |
| --- | --- |
| `src/copilot/tools/common.py` | Shared helpers: reads the new `data` settings in `config.yaml`, opens `payer.db`, tidies IDs (`" m-00217 "` becomes `M-00217`), and defines `ToolError`, the kind of error a tool raises when the model asked for something impossible, such as an unknown claim. |
| `src/copilot/tools/claims.py` | `get_member`, `get_claim`, `search_claims`, `explain_denial_code`. Each is a fixed SQL query with `?` placeholders. The model only supplies values like a claim ID and never writes SQL, which is one of the design's two safety rules. |
| `src/copilot/tools/policy.py` | `search_policy`. Splits the 10 documents at their `##` headings and returns the 3 best-matching sections, each with document and section name (the future citation). **For now it matches words; in milestone 4 the inside becomes vector search.** Its input and output stay the same, so nothing else changes then. |
| `src/copilot/tools/prior_auth.py` | `check_auth_required`, `get_auth_criteria`, `submit_prior_auth`. The last is the project's only write: it adds a `pending` row to the auth queue, and refuses if the member isn't eligible. The human approval pause that guards it comes in milestone 5. |
| `src/copilot/tools/letters.py` | `draft_letter`. Fills an appeal or member letter from database facts (never from the model's memory) and saves it to `outbox/` as Markdown, marked as a synthetic draft. Nothing is sent. |
| `src/copilot/tools/__init__.py` | The list of all 9 tools and `run_tool()`, the one safe way to call any tool. It checks arguments **before** the tool runs. Anything wrong comes back as `{"error": "..."}` instead of a crash, so an agent can read it and retry. That's the design's second safety rule. |
| `src/copilot/tools/__main__.py` | Lets you call any tool from the terminal (commands below). |
| `src/copilot/schemas.py` | Gained an output model for each tool, and `ToolSpec` now also holds the function that runs the tool. |
| `tests/test_tools.py` | 25 tests: each tool's normal case plus its error cases, the planted demo facts, the Silver PT "table and document agree" rule, and that a write adds exactly one row. Every test works on a temporary copy of `payer.db`, so your real data is never changed. |
| `tests/test_smoke_llm.py` | Now imports the tool descriptions from the real tools instead of keeping its own copy, so there is one source of truth. The descriptions are word-for-word the same, so your milestone 0 baseline still holds. |
| `config.yaml` | New `data:` section (database path, outbox, and the fixed "today", 15 Nov 2026). I added it to your copy and kept your port and model IDs. |

Two small choices to know about:

- **`common.py` is an extra file** not named in the design's layout. It holds the helpers all four tool files share, so each one doesn't repeat them.
- **`search_policy` is a simple word-match search until milestone 4**, so the tool exists and can be tested now.

## 2. Commands

```bash
cd ~/Projects/payer-copilot

# Run the 25 tool tests (no model needed, takes about a second)
uv run pytest tests/test_tools.py -v
```

Expected last line:

```text
============================== 25 passed in 0.3s ==============================
```

(Run only `tests/test_tools.py`. A bare `uv run pytest` would also run the smoke test, which calls the model.)

Now call the tools yourself:

```bash
# List all 9 tools and their arguments
uv run python -m copilot.tools

# Demo story 1: the denied claim
uv run python -m copilot.tools get_claim '{"claim_id": "CLM-10482"}'
uv run python -m copilot.tools explain_denial_code '{"code": "CO-197"}'

# Demo story 2: coverage question, and a topic the documents don't cover
uv run python -m copilot.tools search_policy '{"query": "Silver plan physical therapy visit limit"}'
uv run python -m copilot.tools search_policy '{"query": "acupuncture"}'

# Demo story 3: the knee MRI pre-check
uv run python -m copilot.tools get_member '{"member_id": "M-00217"}'
uv run python -m copilot.tools search_claims '{"member_id": "M-00217"}'
uv run python -m copilot.tools check_auth_required '{"procedure_code": "73721", "plan": "Silver"}'
uv run python -m copilot.tools get_auth_criteria '{"procedure_code": "73721"}'

# Validation at work: the same mistake Gemma made in native_tools mode
uv run python -m copilot.tools search_claims '{"member_id": "M-00217", "status": "Denied"}'

# A letter lands in outbox/
uv run python -m copilot.tools draft_letter '{"letter_type": "appeal", "claim_id": "CLM-10482"}'
open outbox/CLM-10482_appeal.md
```

Expected (first lines of two of them):

```text
$ ... get_claim '{"claim_id": "CLM-10482"}'
{
  "claim_id": "CLM-10482",
  "member_id": "M-00142",
  "provider": "Riverbend Radiology",
  "provider_in_network": true,
  "service_date": "2026-09-12",
  ...
  "status": "denied",
  "billed_amount": 1240.0,
  ...
  "denial_code": "CO-197",

$ ... search_claims '{"member_id": "M-00217", "status": "Denied"}'
{
  "error": "Bad arguments for search_claims: status: Input should be 'paid', 'denied' or 'pending'"
}
```

The `acupuncture` search returns `"passages": []`. That empty list is how the benefits agent will know to say "not in the documents".

I left `submit_prior_auth` out of the commands on purpose: it writes to your real database. The tests try it on a copy. If you do run it, rerun `uv run python data/generate.py` afterwards to reset the data.

**The check passes** when `tests/test_tools.py` shows `25 passed`. If anything fails, send me the full output.

## 3. Check your understanding

1. When the model asks for `search_claims` with `status: "Denied"`, what stops it, where in the code does that happen, and why is returning `{"error": ...}` better than letting the program crash?
2. Why does `draft_letter` look up the claim in the database instead of letting the model write the amount and denial code into the letter?
3. The tests change `prior_auth_requests` (they add a row), yet your real `payer.db` is never touched. How?

Then add your 5 lines to `LEARNINGS.md`.

## 4. Full contents of new and changed files

### `config.yaml`

````yaml
# Payer Copilot settings. Edit this file, not the code.

llm:
  base_url: "http://localhost:1235/v1"   # LM Studio local server
  api_key: "lm-studio"                    # LM Studio ignores it, but the client needs a value
  chat_model: "google/gemma-4-12b-qat"  # run: uv run python -m copilot.llm
  embedding_model: "text-embedding-nomic-embed-text-v1.5"
  mode: "json_action"                     # json_action (default) or native_tools
  temperature: 0.0                        # routing, tool choice and review
  max_tokens: 512                         # cap on one reply, keeps calls fast
  timeout_seconds: 120

data:
  db_path: "data/payer.db"
  policies_dir: "data/policies"
  outbox_dir: "outbox"
  today: "2026-11-15"   # the app's fixed "today"; must match TODAY in data/generate.py
````

### `src/copilot/schemas.py`

````python
"""Pydantic models shared across the app.

- Action: what an agent decides (call a tool, or give the final answer).
- ToolSpec: how a tool is described to the model, plus the code that runs it.
- Tool inputs: one model per tool; the model's arguments must match it.
- Tool outputs: one model per tool; what the tool hands back.
Graph state is added in a later milestone.
"""

from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

FINAL_ANSWER = "final_answer"


class Action(BaseModel):
    """One decision from an agent: call a tool, or give the final answer."""

    action: str = Field(description="A tool name, or 'final_answer'.")
    arguments: dict[str, Any] = Field(default_factory=dict)


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
````

### `src/copilot/tools/common.py`

````python
"""Small helpers every tool module shares: settings, the database
connection, and the error type a tool raises when it can't do its job."""

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]  # the payer-copilot folder


class ToolError(Exception):
    """A problem the model can read and fix, such as an unknown claim ID."""


def data_config() -> dict[str, Any]:
    """Read the data section of config.yaml."""
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)["data"]


def db_path() -> Path:
    """Where payer.db lives."""
    return ROOT / data_config()["db_path"]


def outbox_dir() -> Path:
    """Where drafted letters are saved."""
    return ROOT / data_config()["outbox_dir"]


def policies_dir() -> Path:
    """Where the policy Markdown files live."""
    return ROOT / data_config()["policies_dir"]


def today() -> date:
    """The app's fixed 'today', so eligibility answers never drift."""
    return date.fromisoformat(str(data_config()["today"]))


def connect() -> sqlite3.Connection:
    """Open payer.db. Rows come back as dict-like objects (row["claim_id"])."""
    path = db_path()
    if not path.exists():
        raise ToolError(f"{path.name} not found. Run: uv run python data/generate.py")
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def check_id(value: str, prefix: str, example: str) -> str:
    """Tidy an ID (trim spaces, upper case) and check it starts right."""
    value = value.strip().upper()
    if not value.startswith(prefix):
        raise ToolError(f"{value!r} doesn't look like an ID such as {example}.")
    return value
````

### `src/copilot/tools/claims.py`

````python
"""Claims tools: members, claims and denial codes.

Every query is fixed and parameterized (the ? marks). The model only ever
supplies values like a claim ID; it never writes SQL.
"""

from datetime import date

from copilot.schemas import (
    ClaimLineOut,
    ClaimOut,
    ClaimSearchOut,
    ClaimSummary,
    DenialCodeOut,
    ExplainDenialCodeArgs,
    GetClaimArgs,
    GetMemberArgs,
    MemberOut,
    SearchClaimsArgs,
    ToolSpec,
)
from copilot.tools.common import ToolError, check_id, connect, today

MAX_SEARCH_RESULTS = 20


def get_member(args: GetMemberArgs) -> MemberOut:
    """Member profile, plan and eligibility dates by member ID."""
    member_id = check_id(args.member_id, "M-", "M-00217")
    with connect() as con:
        row = con.execute(
            """SELECT m.*, p.deductible, p.coinsurance_pct, p.pt_visit_limit
               FROM members m JOIN plans p USING (plan_id)
               WHERE m.member_id = ?""",
            (member_id,),
        ).fetchone()
    if row is None:
        raise ToolError(f"Member {member_id} not found.")
    end = row["eligibility_end"]
    is_active = date.fromisoformat(row["eligibility_start"]) <= today() and (
        end is None or date.fromisoformat(end) >= today()
    )
    return MemberOut(
        member_id=row["member_id"],
        name=f"{row['first_name']} {row['last_name']}",
        date_of_birth=row["date_of_birth"],
        plan=row["plan_id"],
        eligibility_start=row["eligibility_start"],
        eligibility_end=end,
        is_active=is_active,
        deductible=row["deductible"],
        coinsurance_pct=row["coinsurance_pct"],
        pt_visit_limit=row["pt_visit_limit"],
    )


def get_claim(args: GetClaimArgs) -> ClaimOut:
    """One claim with lines, amounts, status and denial code."""
    claim_id = check_id(args.claim_id, "CLM-", "CLM-10482")
    with connect() as con:
        claim = con.execute(
            """SELECT c.*, pr.name AS provider, pr.in_network
               FROM claims c JOIN providers pr USING (provider_id)
               WHERE c.claim_id = ?""",
            (claim_id,),
        ).fetchone()
        if claim is None:
            raise ToolError(f"Claim {claim_id} not found.")
        lines = con.execute(
            """SELECT l.*, p.description AS procedure, d.description AS diagnosis
               FROM claim_lines l
               JOIN procedures p USING (procedure_code)
               JOIN diagnoses d USING (diagnosis_code)
               WHERE l.claim_id = ? ORDER BY l.line_no""",
            (claim_id,),
        ).fetchall()
    return ClaimOut(
        claim_id=claim["claim_id"],
        member_id=claim["member_id"],
        provider=claim["provider"],
        provider_in_network=bool(claim["in_network"]),
        service_date=claim["service_date"],
        received_date=claim["received_date"],
        status=claim["status"],
        billed_amount=claim["billed_amount"],
        allowed_amount=claim["allowed_amount"],
        paid_amount=claim["paid_amount"],
        member_owes=claim["member_owes"],
        denial_code=claim["denial_code"],
        lines=[
            ClaimLineOut(
                line_no=line["line_no"],
                procedure_code=line["procedure_code"],
                procedure=line["procedure"],
                diagnosis_code=line["diagnosis_code"],
                diagnosis=line["diagnosis"],
                units=line["units"],
                billed_amount=line["billed_amount"],
            )
            for line in lines
        ],
    )


def search_claims(args: SearchClaimsArgs) -> ClaimSearchOut:
    """A member's claims, filtered by date range or status."""
    member_id = check_id(args.member_id, "M-", "M-00217")
    for value in (args.start_date, args.end_date):
        if value is not None:
            try:
                date.fromisoformat(value)
            except ValueError:
                raise ToolError(f"Date {value!r} must look like 2026-09-12.") from None
    # Each filter is either a value or NULL; "? IS NULL" makes a missing filter match everything.
    params = (member_id, args.status, args.status, args.start_date, args.start_date,
              args.end_date, args.end_date)
    with connect() as con:
        if con.execute("SELECT 1 FROM members WHERE member_id = ?", (member_id,)).fetchone() is None:
            raise ToolError(f"Member {member_id} not found.")
        rows = con.execute(
            """SELECT claim_id, service_date, status, billed_amount, paid_amount, denial_code
               FROM claims
               WHERE member_id = ?
                 AND (? IS NULL OR status = ?)
                 AND (? IS NULL OR service_date >= ?)
                 AND (? IS NULL OR service_date <= ?)
               ORDER BY service_date DESC""",
            params,
        ).fetchall()
    return ClaimSearchOut(
        member_id=member_id,
        total_found=len(rows),
        claims=[ClaimSummary(**dict(r)) for r in rows[:MAX_SEARCH_RESULTS]],
    )


def explain_denial_code(args: ExplainDenialCodeArgs) -> DenialCodeOut:
    """Plain-language meaning and usual next step for a denial code."""
    code = args.code.strip().upper()
    with connect() as con:
        row = con.execute("SELECT * FROM denial_codes WHERE code = ?", (code,)).fetchone()
        if row is None:
            known = ", ".join(r[0] for r in con.execute("SELECT code FROM denial_codes"))
            raise ToolError(f"Denial code {code} not found. Known codes: {known}.")
    return DenialCodeOut(code=row["code"], name=row["name"], meaning=row["meaning"],
                         next_step=row["next_step"])


GET_MEMBER = ToolSpec(name="get_member", description="Member profile, plan and eligibility dates by member ID.", args_model=GetMemberArgs, func=get_member)
GET_CLAIM = ToolSpec(name="get_claim", description="One claim with lines, amounts, status and denial code.", args_model=GetClaimArgs, func=get_claim)
SEARCH_CLAIMS = ToolSpec(name="search_claims", description="A member's claims, filtered by date range or status.", args_model=SearchClaimsArgs, func=search_claims)
EXPLAIN_DENIAL_CODE = ToolSpec(name="explain_denial_code", description="Plain-language meaning and usual next step for a denial code.", args_model=ExplainDenialCodeArgs, func=explain_denial_code)
````

### `src/copilot/tools/policy.py`

````python
"""Policy search tool.

For now this is a simple word-match search over the sections of the policy
documents. In milestone 4 the inside of search_policy is replaced by vector
search (rag/retrieve.py); its input and output stay exactly the same, so no
agent or test has to change.
"""

import re

from copilot.schemas import PolicyPassage, PolicySearchOut, SearchPolicyArgs, ToolSpec
from copilot.tools.common import ToolError, policies_dir

TOP_K = 3
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "how",
    "i", "if", "in", "is", "it", "of", "on", "or", "the", "there", "this", "to", "what", "when",
    "which", "who", "with",
}


def load_sections() -> list[tuple[str, str, str]]:
    """Split every policy document at its '## ' headings.

    Returns (document file name, section heading, section text) for each section.
    """
    sections = []
    for path in sorted(policies_dir().glob("*.md")):
        heading, body = "", []
        for line in path.read_text().splitlines():
            if line.startswith("## "):
                if heading:
                    sections.append((path.name, heading, "\n".join(body).strip()))
                heading, body = line[3:].strip(), []
            elif heading:
                body.append(line)
        if heading:
            sections.append((path.name, heading, "\n".join(body).strip()))
    return sections


def words(text: str) -> set[str]:
    """Lower-case words in the text, without common filler words."""
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP_WORDS}


def search_policy(args: SearchPolicyArgs) -> PolicySearchOut:
    """Top passages from plan and policy documents, with document and section."""
    query_words = words(args.query)
    if not query_words:
        raise ToolError("The query is empty. Say what to look for, like 'Silver physical therapy limit'.")
    scored = []
    for document, section, text in load_sections():
        # A word in the file name or heading counts double: it says what the section is about.
        label_words = words(document.replace("_", " ") + " " + section)
        score = len(query_words & words(text)) + 2 * len(query_words & label_words)
        if score > 0:
            scored.append(PolicyPassage(document=document, section=section, text=text, score=score))
    scored.sort(key=lambda p: p.score, reverse=True)
    return PolicySearchOut(query=args.query, passages=scored[:TOP_K])


SEARCH_POLICY = ToolSpec(name="search_policy", description="Top passages from plan and policy documents, with document and section.", args_model=SearchPolicyArgs, func=search_policy)
````

### `src/copilot/tools/prior_auth.py`

````python
"""Prior authorization tools: is auth needed, what are the criteria, and
submit a request to the auth queue.

submit_prior_auth is the only tool in the project that writes to the
database. In milestone 5 the graph pauses for a person to approve before it
is ever called; this file only does the write itself.
"""

from datetime import date

from copilot.schemas import (
    AuthCriteriaOut,
    AuthRequiredOut,
    CheckAuthRequiredArgs,
    GetAuthCriteriaArgs,
    SubmitPriorAuthArgs,
    SubmitPriorAuthOut,
    ToolSpec,
)
from copilot.tools.common import ToolError, check_id, connect, today


def _procedure_name(con, code: str) -> str:
    """Description of a procedure code, or a ToolError if it's unknown."""
    row = con.execute("SELECT description FROM procedures WHERE procedure_code = ?", (code,)).fetchone()
    if row is None:
        raise ToolError(f"Procedure code {code} not found.")
    return row["description"]


def check_auth_required(args: CheckAuthRequiredArgs) -> AuthRequiredOut:
    """Whether a procedure code needs prior auth on a given plan."""
    code = args.procedure_code.strip().upper()
    with connect() as con:
        name = _procedure_name(con, code)
        rule = con.execute(
            "SELECT auth_required, policy_document FROM auth_rules WHERE procedure_code = ? AND plan_id = ?",
            (code, args.plan),
        ).fetchone()
    # A procedure with no rule row never needs prior auth.
    return AuthRequiredOut(
        procedure_code=code,
        procedure=name,
        plan=args.plan,
        auth_required=bool(rule["auth_required"]) if rule else False,
        policy_document=rule["policy_document"] if rule else None,
    )


def get_auth_criteria(args: GetAuthCriteriaArgs) -> AuthCriteriaOut:
    """The checklist of criteria for a procedure."""
    code = args.procedure_code.strip().upper()
    with connect() as con:
        name = _procedure_name(con, code)
        rows = con.execute(
            "SELECT criterion FROM auth_criteria WHERE procedure_code = ? ORDER BY item_no", (code,)
        ).fetchall()
        doc = con.execute(
            "SELECT policy_document FROM auth_rules WHERE procedure_code = ? LIMIT 1", (code,)
        ).fetchone()
    if not rows:
        raise ToolError(f"Procedure {code} has no prior auth criteria; it does not need prior auth.")
    return AuthCriteriaOut(procedure_code=code, procedure=name,
                           criteria=[r["criterion"] for r in rows], policy_document=doc["policy_document"])


def submit_prior_auth(args: SubmitPriorAuthArgs) -> SubmitPriorAuthOut:
    """Writes a request with the recommendation to the auth queue. Needs human approval."""
    member_id = check_id(args.member_id, "M-", "M-00217")
    code = args.procedure_code.strip().upper()
    with connect() as con:
        _procedure_name(con, code)
        member = con.execute("SELECT eligibility_end FROM members WHERE member_id = ?", (member_id,)).fetchone()
        if member is None:
            raise ToolError(f"Member {member_id} not found.")
        end = member["eligibility_end"]
        if end is not None and date.fromisoformat(end) < today():
            raise ToolError(f"Member {member_id} is not eligible (coverage ended {end}); nothing submitted.")
        last = con.execute("SELECT MAX(auth_id) FROM prior_auth_requests").fetchone()[0] or "PA-0000"
        auth_id = f"PA-{int(last.split('-')[1]) + 1:04d}"
        con.execute(
            """INSERT INTO prior_auth_requests
               (auth_id, member_id, procedure_code, request_date, status, recommendation,
                rationale, decided_by, is_synthetic)
               VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, 1)""",
            (auth_id, member_id, code, today().isoformat(), args.recommendation, args.rationale),
        )
    # "with connect()" commits the insert when the block ends without an error.
    return SubmitPriorAuthOut(auth_id=auth_id, member_id=member_id, procedure_code=code,
                              status="pending", recommendation=args.recommendation)


CHECK_AUTH_REQUIRED = ToolSpec(name="check_auth_required", description="Whether a procedure code needs prior auth on a given plan.", args_model=CheckAuthRequiredArgs, func=check_auth_required)
GET_AUTH_CRITERIA = ToolSpec(name="get_auth_criteria", description="The checklist of criteria for a procedure.", args_model=GetAuthCriteriaArgs, func=get_auth_criteria)
SUBMIT_PRIOR_AUTH = ToolSpec(name="submit_prior_auth", description="Writes a request with the recommendation to the auth queue. Needs human approval.", args_model=SubmitPriorAuthArgs, func=submit_prior_auth)
````

### `src/copilot/tools/letters.py`

````python
"""Letter tool: fill an appeal or member letter template with claim facts.

The facts come from the database, not from the model, so a letter can't
contain an invented amount or code. The letter is saved as a Markdown file
in the outbox folder for a person to review; nothing is sent anywhere.
"""

from copilot.schemas import DraftLetterArgs, GetClaimArgs, GetMemberArgs, LetterOut, ToolSpec
from copilot.tools import common
from copilot.tools.claims import get_claim, get_member
from copilot.tools.common import ToolError, check_id, connect

APPEAL_TEMPLATE = """# Appeal of claim {claim_id}

SYNTHETIC DRAFT FOR REVIEW. NOT SENT.

Date: {today}
To: Acme Health Plan, Appeals Department
Member: {member_name} ({member_id}), {plan} plan
Claim: {claim_id}, date of service {service_date}
Service: {services}
Amount billed: ${billed:,.2f}

## Reason for appeal

The claim was denied with code {denial_code} ({denial_name}): {denial_meaning}

We ask the plan to review this decision. {next_step}

## Enclosed

- Copy of the denial notice
- Supporting records, such as office notes or a letter of medical necessity

This appeal is filed within the plan's appeal deadline. See the Appeals Procedure.
"""

MEMBER_TEMPLATE = """# About your claim {claim_id}

SYNTHETIC DRAFT FOR REVIEW. NOT SENT.

Date: {today}
Dear {member_name},

We have an update on claim {claim_id} for {services} on {service_date}.

Status: {status}.
{status_detail}

If you have questions, call the member services number on your ID card.

Acme Health Plan
"""


def draft_letter(args: DraftLetterArgs) -> LetterOut:
    """Fills an appeal or member letter template for a claim."""
    claim = get_claim(GetClaimArgs(claim_id=check_id(args.claim_id, "CLM-", "CLM-10482")))
    member = get_member(GetMemberArgs(member_id=claim.member_id))
    services = ", ".join(f"{line.procedure} ({line.procedure_code})" for line in claim.lines)
    facts = {
        "claim_id": claim.claim_id, "today": common.today().isoformat(),
        "member_name": member.name, "member_id": member.member_id, "plan": member.plan,
        "service_date": claim.service_date, "services": services, "billed": claim.billed_amount,
        "status": claim.status,
    }
    denial = None
    if claim.denial_code:
        with connect() as con:
            denial = con.execute("SELECT * FROM denial_codes WHERE code = ?", (claim.denial_code,)).fetchone()

    if args.letter_type == "appeal":
        if denial is None:
            raise ToolError(f"Claim {claim.claim_id} is {claim.status}, not denied; there is nothing to appeal.")
        text = APPEAL_TEMPLATE.format(**facts, denial_code=denial["code"], denial_name=denial["name"],
                                      denial_meaning=denial["meaning"], next_step=denial["next_step"])
    else:
        if denial is not None:
            detail = f"The claim was denied: {denial['meaning']} {denial['next_step']}"
        elif claim.status == "paid":
            detail = f"The plan paid ${claim.paid_amount:,.2f}. Your share is ${claim.member_owes:,.2f}."
        else:
            detail = "We are still processing it."
        text = MEMBER_TEMPLATE.format(**facts, status_detail=detail)

    folder = common.outbox_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{claim.claim_id}_{args.letter_type}.md"
    path.write_text(text)
    return LetterOut(letter_type=args.letter_type, claim_id=claim.claim_id, path=str(path), text=text)


DRAFT_LETTER = ToolSpec(name="draft_letter", description="Fills an appeal or member letter template for a claim.", args_model=DraftLetterArgs, func=draft_letter)
````

### `src/copilot/tools/__init__.py`

````python
"""The nine tools, and run_tool(), the one safe way to call any of them.

run_tool checks the arguments before the tool runs. If something is wrong
(a bad argument, an unknown ID) it returns {"error": "..."} instead of
crashing, so an agent can read the message and try again.
"""

from typing import Any

from pydantic import ValidationError

from copilot.schemas import ToolSpec
from copilot.tools.claims import EXPLAIN_DENIAL_CODE, GET_CLAIM, GET_MEMBER, SEARCH_CLAIMS
from copilot.tools.common import ToolError
from copilot.tools.letters import DRAFT_LETTER
from copilot.tools.policy import SEARCH_POLICY
from copilot.tools.prior_auth import CHECK_AUTH_REQUIRED, GET_AUTH_CRITERIA, SUBMIT_PRIOR_AUTH

ALL_TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [GET_MEMBER, GET_CLAIM, SEARCH_CLAIMS, EXPLAIN_DENIAL_CODE, SEARCH_POLICY,
                 CHECK_AUTH_REQUIRED, GET_AUTH_CRITERIA, SUBMIT_PRIOR_AUTH, DRAFT_LETTER]
}


def run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate the arguments, run the tool, and return its result as a dict."""
    spec = ALL_TOOLS.get(name)
    if spec is None:
        return {"error": f"Unknown tool {name!r}. Known tools: {', '.join(ALL_TOOLS)}."}
    try:
        args = spec.args_model.model_validate(arguments)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
        return {"error": f"Bad arguments for {name}: {problems}"}
    try:
        return spec.func(args).model_dump()
    except ToolError as e:
        return {"error": str(e)}
````

### `src/copilot/tools/__main__.py`

````python
"""Call any tool from the terminal.

    uv run python -m copilot.tools                      # list the tools
    uv run python -m copilot.tools get_claim '{"claim_id": "CLM-10482"}'
"""

import json
import sys

from copilot.tools import ALL_TOOLS, run_tool


def main() -> None:
    if len(sys.argv) < 2:
        for spec in ALL_TOOLS.values():
            print(f"{spec.name:<20} {spec.description}")
            print(f"{'':<20} arguments: {', '.join(spec.args_model.model_fields)}")
        return
    name = sys.argv[1]
    arguments = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    print(json.dumps(run_tool(name, arguments), indent=2))


if __name__ == "__main__":
    main()
````

### `tests/test_tools.py`

````python
"""Unit tests for the nine tools. No model needed; runs in a few seconds.

Each test works on a temporary copy of payer.db and a temporary outbox, so
running the tests never changes your real data.

Run:  uv run pytest tests/test_tools.py -v
"""

import shutil
import sqlite3

import pytest

from copilot.tools import common, run_tool

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


def test_search_claims_bad_inputs():
    assert "2026-09-12" in run_tool("search_claims", {"member_id": "M-00217", "start_date": "Oct 1"})["error"]
    assert "Bad arguments" in run_tool("search_claims", {"member_id": "M-00217", "status": "Denied"})["error"]


# ---------- explain_denial_code ----------

def test_explain_denial_code():
    out = run_tool("explain_denial_code", {"code": "co-197"})
    assert out["name"] == "No prior authorization"


def test_explain_denial_code_unknown():
    assert "Known codes" in run_tool("explain_denial_code", {"code": "XX-1"})["error"]


# ---------- search_policy ----------

def test_search_policy_finds_silver_pt():
    out = run_tool("search_policy", {"query": "Silver plan physical therapy visit limit"})
    found = [(p["document"], p["section"]) for p in out["passages"]]
    assert ("silver_coverage_summary.md", "Physical therapy") in found


def test_search_policy_silent_topic():
    assert run_tool("search_policy", {"query": "acupuncture"})["passages"] == []


def test_silver_pt_limit_matches_table_and_document():
    """Design rule: the plans table and the Silver document must agree."""
    limit = run_tool("get_member", {"member_id": "M-00217"})["pt_visit_limit"]
    passages = run_tool("search_policy", {"query": "Silver physical therapy"})["passages"]
    silver = [p for p in passages if p["document"] == "silver_coverage_summary.md"]
    assert limit == 30 and f"up to {limit} visits" in silver[0]["text"]


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

def test_submit_prior_auth_writes_one_row(temp_data):
    args = {"member_id": "M-00217", "procedure_code": "73721",
            "recommendation": "approve", "rationale": "All 5 criteria met."}
    out = run_tool("submit_prior_auth", args)
    assert out["auth_id"] == "PA-0061" and out["status"] == "pending"
    con = sqlite3.connect(temp_data)
    assert con.execute("SELECT COUNT(*) FROM prior_auth_requests").fetchone()[0] == 61
    assert con.execute("SELECT member_id FROM prior_auth_requests WHERE auth_id = 'PA-0061'").fetchone()[0] == "M-00217"


def test_submit_prior_auth_refuses_lapsed_member(temp_data):
    args = {"member_id": "M-00250", "procedure_code": "73721",
            "recommendation": "approve", "rationale": "x"}
    assert "not eligible" in run_tool("submit_prior_auth", args)["error"]
    con = sqlite3.connect(temp_data)
    assert con.execute("SELECT COUNT(*) FROM prior_auth_requests").fetchone()[0] == 60


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
