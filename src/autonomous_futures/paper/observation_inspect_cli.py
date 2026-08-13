"""Inspect the latest bound paper observation without mutating durable state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from .observation import PaperObservationBinding
from .sqlite_observation import SqlitePaperObservations


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect the latest read-only paper observation.")
    parser.add_argument("--observation-path", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--candidate-artifact-hash", required=True)
    return parser


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        binding = PaperObservationBinding(
            candidate_id=args.candidate_id,
            candidate_artifact_hash=args.candidate_artifact_hash,
        )
        observations = SqlitePaperObservations(args.observation_path).read(
            binding.candidate_id, binding.candidate_artifact_hash
        )
    except (OSError, ValidationError, ValueError) as exc:
        del exc
        _print_json({"error_code": "invalid_input", "status": "error"})
        return 2
    if not observations:
        _print_json({"status": "unavailable"})
        return 0
    payload = observations[-1].model_dump(mode="json")
    payload["status"] = "available"
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
