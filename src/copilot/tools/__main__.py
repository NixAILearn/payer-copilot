"""Call any tool from the terminal.

    uv run python -m copilot.tools                      # list the tools
    uv run python -m copilot.tools get_claim '{"claim_id": "CLM-10482"}'
"""

import json
import sys

from copilot.tools import ALL_TOOLS, run_tool


def main() -> None:
    if len(sys.argv) < 2:
        for spec in ALL_TOOLS.values():
            print(f"{spec.name:<20} {spec.description}")
            print(f"{'':<20} arguments: {', '.join(spec.args_model.model_fields)}")
        return
    name = sys.argv[1]
    arguments = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    print(json.dumps(run_tool(name, arguments), indent=2))


if __name__ == "__main__":
    main()
