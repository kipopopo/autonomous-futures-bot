"""Inspect aggregate paper health from caller-owned observation journals."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from .health import aggregate_paper_health
from .observation import PaperObservationBinding
from .sqlite_lifecycle import SqlitePaperLifecycle
from .sqlite_observation import SqlitePaperObservations


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect read-only aggregate paper health.")
    parser.add_argument("--observation-path", type=Path, required=True)
    parser.add_argument("--lifecycle-path", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--candidate-artifact-hash", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--max-mark-age-seconds", type=int, required=True)
    parser.add_argument("--required-days", type=int, default=7)
    return parser


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValueError("invalid as-of timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("as-of must be timezone-aware UTC")
    return parsed.astimezone(UTC)


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
        lifecycle_marks = SqlitePaperLifecycle(args.lifecycle_path).read_candidate(
            candidate_id=binding.candidate_id,
            candidate_artifact_hash=binding.candidate_artifact_hash,
        )
        report = aggregate_paper_health(
            observations,
            lifecycle_marks,
            candidate_id=binding.candidate_id,
            candidate_artifact_hash=binding.candidate_artifact_hash,
            as_of=_parse_utc(args.as_of),
            max_mark_age_seconds=args.max_mark_age_seconds,
            required_days=args.required_days,
        )
    except (OSError, ValidationError, ValueError) as exc:
        del exc
        _print_json({"error_code": "invalid_input", "status": "error"})
        return 2
    payload = report.model_dump(mode="json")
    payload["status"] = report.health_status
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
