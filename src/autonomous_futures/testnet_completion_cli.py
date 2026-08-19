"""Inspect persisted bounded testnet evidence completion without mutation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .testnet_audit import SqliteTestnetLifecycleEvidence
from .testnet_completion import summarize_testnet_completion
from .testnet_freeze import SqliteTestnetEvidenceReviews
from .testnet_observation import SqliteTestnetObservations


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect frozen testnet evidence completion.")
    parser.add_argument("--audit-path", type=Path, required=True)
    parser.add_argument("--observation-path", type=Path, required=True)
    parser.add_argument("--review-path", type=Path, required=True)
    return parser


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = summarize_testnet_completion(
            SqliteTestnetLifecycleEvidence(args.audit_path).read(),
            SqliteTestnetObservations(args.observation_path).read(),
            SqliteTestnetEvidenceReviews(args.review_path).read(),
        )
    except (OSError, ValueError) as exc:
        del exc
        _print_json({"error_code": "invalid_input", "status": "error"})
        return 2
    payload = summary.model_dump(mode="json")
    payload["status"] = summary.status
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
