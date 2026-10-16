"""Verify an execution event evidence journal without acquiring a writer lease."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from autonomous_futures.execution.execution_event_evidence import (  # noqa: E402
    verify_execution_event_evidence,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path, help="Path to exchange-user-events.jsonl")
    args = parser.parse_args()
    try:
        summary = verify_execution_event_evidence(args.ledger)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Invalid execution event evidence: {exc}\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
