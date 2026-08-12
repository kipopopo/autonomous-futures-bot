"""Capture one caller-input paper observation without market or execution access."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import ValidationError

from .observation import PaperObservationBinding, observe_paper_ledger
from .sqlite_ledger import SqlitePaperLedger
from .sqlite_observation import SqlitePaperObservations


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture one explicit read-only paper observation."
    )
    parser.add_argument("--ledger-path", type=Path, required=True)
    parser.add_argument("--observation-path", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--candidate-artifact-hash", required=True)
    parser.add_argument("--starting-equity", required=True)
    parser.add_argument("--previous-peak-equity", required=True)
    parser.add_argument("--marks-path", type=Path, required=True)
    parser.add_argument("--observed-at", required=True)
    return parser


def _parse_decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal input") from exc
    if not parsed.is_finite():
        raise ValueError("invalid decimal input")
    return parsed


def _parse_utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValueError("invalid observed-at timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("observed-at must be timezone-aware UTC")
    return parsed.astimezone(UTC)


def _load_marks(path: Path) -> dict[str, Decimal]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid marks input") from exc
    if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
        raise ValueError("invalid marks input")
    try:
        return {key: _parse_decimal(str(value)) for key, value in payload.items()}
    except ValueError as exc:
        raise ValueError("invalid marks input") from exc


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        binding = PaperObservationBinding(
            candidate_id=args.candidate_id,
            candidate_artifact_hash=args.candidate_artifact_hash,
        )
        snapshot = observe_paper_ledger(
            SqlitePaperLedger(args.ledger_path).load(),
            candidate_id=binding.candidate_id,
            candidate_artifact_hash=binding.candidate_artifact_hash,
            starting_equity=_parse_decimal(args.starting_equity),
            previous_peak_equity=_parse_decimal(args.previous_peak_equity),
            mark_prices=_load_marks(args.marks_path),
            observed_at=_parse_utc_timestamp(args.observed_at),
        )
        SqlitePaperObservations(args.observation_path).append(snapshot)
    except (OSError, ValidationError, ValueError) as exc:
        del exc
        _print_json({"error_code": "invalid_input", "status": "error"})
        return 2
    payload = snapshot.model_dump(mode="json")
    payload["status"] = "captured"
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
