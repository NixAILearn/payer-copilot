"""Small helpers shared by the tools and the RAG code: settings from the
data section of config.yaml, the database connection, and ToolError, the
error a tool raises when it can't do its job.

(It lived in tools/ in milestone 2. It moved here in milestone 4 because
the RAG code needs it too, and importing it from inside tools/ created an
import loop.)"""

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]  # the payer-copilot folder


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


def chroma_dir() -> Path:
    """Where the Chroma vector index is stored."""
    return ROOT / data_config()["chroma_dir"]


def checkpoint_db() -> Path:
    """Where LangGraph keeps its checkpoints."""
    return ROOT / data_config()["checkpoint_db"]


def policy_top_k() -> int:
    """How many passages search_policy returns."""
    return int(data_config()["policy_top_k"])


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
