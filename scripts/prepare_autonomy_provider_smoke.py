"""Prepare one non-authorizing autonomous provider smoke request."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.research.provider_smoke import (  # noqa: E402
    build_provider_smoke_preparation,
    write_provider_smoke_preparation,
)
from autonomous_futures.research_lab.model_policy import ResearchModelPolicy  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare one offline, non-authorizing provider smoke artifact."
    )
    parser.add_argument("--policy-file", type=Path, required=True)
    parser.add_argument(
        "--role",
        choices=("failure_analyst", "hypothesis_generator"),
        required=True,
    )
    parser.add_argument("--research-run-id", required=True)
    parser.add_argument("--input-evidence-ref", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        policy = ResearchModelPolicy.model_validate_json(
            args.policy_file.read_text(encoding="utf-8")
        )
        preparation = build_provider_smoke_preparation(
            research_run_id=args.research_run_id,
            role=args.role,
            policy=policy,
            input_evidence_refs=tuple(args.input_evidence_ref),
            prepared_at=datetime.now(UTC),
        )
        persisted = write_provider_smoke_preparation(args.output, preparation)
    except OSError:
        print(json.dumps({"status": "blocked", "error_code": "invalid_preparation_input"}))
        return 2
    except TypeError:
        print(json.dumps({"status": "blocked", "error_code": "invalid_preparation_input"}))
        return 2
    except ValueError:
        print(json.dumps({"status": "blocked", "error_code": "invalid_preparation_input"}))
        return 2

    print(
        json.dumps(
            {
                "status": "prepared",
                "preparation_id": persisted.preparation_id,
                "preparation_hash": persisted.preparation_hash,
                "research_run_id": persisted.research_run_id,
                "role": persisted.role,
                "provider": persisted.provider,
                "model_id": persisted.model_id,
                "request_count": persisted.request_count,
                "max_retries": persisted.max_retries,
                "fallback_provider": persisted.fallback_provider,
                "network_call_allowed": persisted.network_call_allowed,
                "runtime_mutation": persisted.runtime_mutation,
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
