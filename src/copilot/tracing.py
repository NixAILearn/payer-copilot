"""JSONL trace writer: one line per agent step, in traces/trace.jsonl.

Each line records what the model saw (prompt), what it said (raw output),
the action it chose, the tool's result, tokens and time taken. Reading the
trace is the fastest way to learn why an agent did what it did.

    uv run python -m copilot.tracing            # show the latest run
    uv run python -m copilot.tracing <run_id>   # show one run
"""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

TRACE_FILE = Path(__file__).resolve().parents[2] / "traces" / "trace.jsonl"


def new_run_id() -> str:
    """A short unique ID for one question, like 20261118-091502-3fa1."""
    return f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"


def write_step(run_id: str, agent: str, step: int, **fields: Any) -> None:
    """Append one JSON line for one step of one run."""
    TRACE_FILE.parent.mkdir(exist_ok=True)
    line = {"run_id": run_id, "time": datetime.now().isoformat(timespec="seconds"),
            "agent": agent, "step": step, **fields}
    with open(TRACE_FILE, "a") as f:
        f.write(json.dumps(line, default=str) + "\n")


def read_run(run_id: str | None = None) -> list[dict[str, Any]]:
    """All steps of one run. With no run_id, the most recent run."""
    if not TRACE_FILE.exists():
        return []
    lines = [json.loads(line) for line in TRACE_FILE.read_text().splitlines() if line.strip()]
    if run_id is None and lines:
        run_id = lines[-1]["run_id"]
    return [line for line in lines if line["run_id"] == run_id]


def format_step(step: dict[str, Any]) -> str:
    """One step as a short readable block."""
    tokens = f"{step.get('input_tokens')}->{step.get('output_tokens')} tokens"
    head = f"step {step['step']} [{step['agent']}] {step.get('latency_s') or 0:.1f}s {tokens}"
    if step.get("error"):
        return f"{head}\n  ERROR: {step['error']}\n  raw: {str(step.get('raw_output'))[:200]}"
    body = f"  action: {step.get('action')} {json.dumps(step.get('arguments'))}"
    if "tool_result" in step:
        body += f"\n  result: {json.dumps(step['tool_result'])[:300]}"
    return f"{head}\n{body}"


def main() -> None:
    steps = read_run(sys.argv[1] if len(sys.argv) > 1 else None)
    if not steps:
        print("No trace found. Ask the agent a question first.")
        return
    print(f"run {steps[0]['run_id']}")
    for step in steps:
        print(format_step(step))


if __name__ == "__main__":
    main()
