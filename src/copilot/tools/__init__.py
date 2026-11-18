"""The nine tools, and run_tool(), the one safe way to call any of them.

run_tool checks the arguments before the tool runs. If something is wrong
(a bad argument, an unknown ID) it returns {"error": "..."} instead of
crashing, so an agent can read the message and try again.
"""

from typing import Any

from pydantic import ValidationError

from copilot.schemas import ToolSpec
from copilot.tools.claims import EXPLAIN_DENIAL_CODE, GET_CLAIM, GET_MEMBER, SEARCH_CLAIMS
from copilot.common import ToolError
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
