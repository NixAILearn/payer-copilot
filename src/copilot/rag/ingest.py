"""Build the vector index of the policy documents.

Run it whenever the documents change:
    uv run python -m copilot.rag.ingest

Each '## ' section of each document becomes one chunk. A chunk keeps its
document name and section heading; that pair is the citation. The text is
turned into a vector by the embedding model in LM Studio and stored, with
the text and citation, in a Chroma index on disk (data/chroma).
"""

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings

from copilot.llm import embed
from copilot.common import chroma_dir, policies_dir

COLLECTION = "policies"


def open_collection(create: bool = False) -> Collection | None:
    """Open the index. With create=True, delete any old one and start fresh.
    Returns None if there is no index yet."""
    client = chromadb.PersistentClient(path=str(chroma_dir()),
                                       settings=Settings(anonymized_telemetry=False))
    if create:
        if COLLECTION in [c.name for c in client.list_collections()]:
            client.delete_collection(COLLECTION)
        # embedding_function=None: we always supply our own vectors from LM Studio.
        return client.create_collection(COLLECTION, embedding_function=None,
                                        metadata={"hnsw:space": "cosine"})
    if COLLECTION not in [c.name for c in client.list_collections()]:
        return None
    return client.get_collection(COLLECTION, embedding_function=None)


def load_sections() -> list[dict[str, str]]:
    """Split every policy document at its '## ' headings.

    Returns one dict per section: document (file name), title (the '# '
    heading), section (the '## ' heading) and text.
    """
    sections = []
    for path in sorted(policies_dir().glob("*.md")):
        title, heading, body = path.stem, "", []
        for line in path.read_text().splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
            elif line.startswith("## "):
                if heading:  # a new heading closes the previous section
                    sections.append(_section(path.name, title, heading, body))
                heading, body = line[3:].strip(), []
            elif heading:
                body.append(line)
        if heading:  # the last section ends with the file
            sections.append(_section(path.name, title, heading, body))
    return sections


def _section(document: str, title: str, heading: str, body: list[str]) -> dict[str, str]:
    """One section as a dict."""
    return {"document": document, "title": title, "section": heading, "text": "\n".join(body).strip()}


def build_index() -> int:
    """Embed every section and store it in a fresh index. Returns the chunk count."""
    sections = load_sections()
    # The title and heading go into the embedded text too, so a question that
    # names the Silver plan lands on Silver's sections, not Gold's.
    texts = [f"{s['title']}\n{s['section']}\n{s['text']}" for s in sections]
    collection = open_collection(create=True)
    collection.add(
        ids=[f"{s['document']}#{i}" for i, s in enumerate(sections)],
        embeddings=embed(texts, kind="document"),
        documents=[s["text"] for s in sections],
        metadatas=[{"document": s["document"], "section": s["section"]} for s in sections],
    )
    return len(sections)


def main() -> None:
    count = build_index()
    documents = {s["document"] for s in load_sections()}
    print(f"Indexed {count} sections from {len(documents)} documents into {chroma_dir()}")


if __name__ == "__main__":
    main()
