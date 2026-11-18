"""Letter tool: fill an appeal or member letter template with claim facts.

The facts come from the database, not from the model, so a letter can't
contain an invented amount or code. The letter is saved as a Markdown file
in the outbox folder for a person to review; nothing is sent anywhere.
"""

from copilot.schemas import DraftLetterArgs, GetClaimArgs, GetMemberArgs, LetterOut, ToolSpec
from copilot import common
from copilot.tools.claims import get_claim, get_member
from copilot.common import ToolError, check_id, connect

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
