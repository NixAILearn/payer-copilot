"""Policy search tool. Since milestone 4 it uses vector search over the
policy documents (rag/retrieve.py). Its input and output are unchanged
from milestone 2, so the agents and tests didn't need to change."""

from copilot.rag.retrieve import retrieve
from copilot.schemas import PolicySearchOut, SearchPolicyArgs, ToolSpec
from copilot.common import ToolError


def search_policy(args: SearchPolicyArgs) -> PolicySearchOut:
    """Top passages from plan and policy documents, with document and section."""
    if not args.query.strip():
        raise ToolError("The query is empty. Say what to look for, like 'Silver physical therapy limit'.")
    return PolicySearchOut(query=args.query, passages=retrieve(args.query))


SEARCH_POLICY = ToolSpec(name="search_policy", description="Top passages from plan and policy documents, with document and section.", args_model=SearchPolicyArgs, func=search_policy)
