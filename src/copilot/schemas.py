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
        default=None, description="Only claims with this status. Leave empty to see every claim; a denied claim still shows the service was done."
    )
    start_date: str | None = Field(default=None, description="YYYY-MM-DD, inclusive.")
    end_date: str | None = Field(default=None, description="YYYY-MM-DD, inclusive.")


class ClaimHistoryArgs(BaseModel):
    """search_claims for the prior auth agent: no status filter, because a
    denied or pending claim still shows that a service was done."""

    member_id: str = Field(description="Member ID, like M-00217.")
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
    hidden_by_status_filter: dict[str, int] | None = Field(
        default=None, description="With a status filter: how many claims of each other status were left out.")


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

    route: Literal["claims", "benefits", "prior_auth", "clarify", "out_of_scope"] = Field(
        description="claims: a specific claim or denial code. benefits: what a plan covers. "
        "prior_auth: whether a procedure needs or meets prior authorization. "
        "clarify: about this work but too vague to route. "
        "out_of_scope: not about claims, plan coverage or prior authorization at all."
    )
    member_id: str | None = Field(default=None, description="Member ID in the request, like M-00217.")
    claim_id: str | None = Field(default=None, description="Claim ID in the request, like CLM-10482.")
    clarifying_question: str | None = Field(
        default=None, description="Only for route 'clarify': one short question back to the analyst."
    )
    out_of_scope_part: str | None = Field(
        default=None, description="Any part of the request that is not about claims, plan coverage or "
        "prior authorization, such as coding help. It is left out of the answer."
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
    declined: str | None  # the out-of-scope part of a mixed request, left out of the answer
    approval: dict[str, Any] | None  # {"decision", "approver", "arguments" actually used, "edited"}
    submission: dict[str, Any] | None  # what submit_prior_auth returned, after approval
