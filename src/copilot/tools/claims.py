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
from copilot.common import ToolError, check_id, connect, today

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
            """SELECT c.claim_id, c.service_date, c.status, c.billed_amount, c.paid_amount, c.denial_code,
                      GROUP_CONCAT(l.procedure_code || ' ' || p.description, '; ') AS services
               FROM claims c
               JOIN claim_lines l USING (claim_id)
               JOIN procedures p USING (procedure_code)
               WHERE c.member_id = ?
                 AND (? IS NULL OR c.status = ?)
                 AND (? IS NULL OR c.service_date >= ?)
                 AND (? IS NULL OR c.service_date <= ?)
               GROUP BY c.claim_id
               ORDER BY c.service_date DESC""",
            params,
        ).fetchall()
        hidden = None
        if args.status:
            # Say what the filter left out, so a "paid only" search can't hide a denied MRI unnoticed.
            others = con.execute(
                """SELECT status, COUNT(*) AS n FROM claims
                   WHERE member_id = ? AND status != ?
                     AND (? IS NULL OR service_date >= ?) AND (? IS NULL OR service_date <= ?)
                   GROUP BY status""",
                (member_id, args.status, args.start_date, args.start_date, args.end_date, args.end_date),
            ).fetchall()
            hidden = {r["status"]: r["n"] for r in others} or None
    return ClaimSearchOut(
        member_id=member_id,
        total_found=len(rows),
        claims=[ClaimSummary(**dict(r)) for r in rows[:MAX_SEARCH_RESULTS]],
        hidden_by_status_filter=hidden,
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
