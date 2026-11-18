"""Find the policy sections closest in meaning to a question.

Try it:
    uv run python -m copilot.rag.retrieve "Does the Silver plan cover physical therapy?"
"""

import sys

from copilot.llm import embed
from copilot.rag.ingest import open_collection
from copilot.schemas import PolicyPassage
from copilot.common import ToolError, policy_top_k


def retrieve(query: str, k: int | None = None) -> list[PolicyPassage]:
    """The k best sections for the query, best first.

    score is cosine similarity: 1.0 means the same meaning, 0 means unrelated.
    Vector search always returns something, so a low score is the hint that
    the documents may not cover the question.
    """
    collection = open_collection()
    if collection is None:
        raise ToolError("The policy index has not been built. Run: uv run python -m copilot.rag.ingest")
    result = collection.query(query_embeddings=embed([query], kind="query"), n_results=k or policy_top_k())
    return [
        PolicyPassage(document=meta["document"], section=meta["section"], text=text,
                      score=round(1 - distance, 3))
        for meta, text, distance in zip(result["metadatas"][0], result["documents"][0],
                                        result["distances"][0])
    ]


def main() -> None:
    query = " ".join(sys.argv[1:]) or "Does the Silver plan cover physical therapy?"
    print(f"Query: {query}\n")
    for p in retrieve(query, k=5):
        print(f"{p.score:.3f}  {p.document} > {p.section}")
        print(f"       {p.text[:110].replace(chr(10), ' ')}...")


if __name__ == "__main__":
    main()
