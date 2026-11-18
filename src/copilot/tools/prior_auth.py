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
from copilot.common import ToolError, check_id, connect, today


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
