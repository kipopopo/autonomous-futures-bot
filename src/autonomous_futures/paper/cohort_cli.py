"""Summarize explicit paper health reports for human review only."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from .cohort import evaluate_paper_cohort_snapshot, summarize_paper_cohort
from .health import PaperHealthReport
from .observation import PaperObservationBinding


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize read-only paper cohort readiness.")
    parser.add_argument(
        "--expected-path", type=Path, default=None, help="Path to expected bindings JSON list"
    )
    parser.add_argument(
        "--reports-path", type=Path, default=None, help="Path to health reports JSON list"
    )
    parser.add_argument(
        "--ledger-path",
        "--ledger-db",
        type=Path,
        default=Path("paper-ledger.sqlite3"),
        help="Path to paper-ledger.sqlite3",
    )
    parser.add_argument(
        "--lifecycle-path",
        "--lifecycle-db",
        type=Path,
        default=Path("paper-lifecycle.sqlite3"),
        help="Path to paper-lifecycle.sqlite3",
    )
    parser.add_argument(
        "--observations-path",
        "--observations-db",
        type=Path,
        default=Path("paper-observations.sqlite3"),
        help="Path to paper-observations.sqlite3",
    )
    parser.add_argument(
        "--manifest-path",
        "--registry-manifest",
        type=Path,
        default=None,
        help="Path to candidate_registry.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to persist cohort readiness report and per-symbol health reports",
    )
    parser.add_argument(
        "--as-of",
        type=str,
        default=None,
        help="ISO timestamp string for evaluation as_of",
    )
    parser.add_argument(
        "--max-mark-age-seconds",
        type=int,
        default=86400,
        help="Max mark age seconds before stale",
    )
    parser.add_argument(
        "--required-days",
        type=int,
        default=7,
        help="Required observation days for maturity",
    )
    return parser


def _load_list(path: Path) -> list[object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON input") from exc
    if not isinstance(payload, list):
        raise ValueError("JSON input must be a list")
    return payload


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.expected_path is not None and args.reports_path is not None:
        try:
            expected = tuple(
                PaperObservationBinding.model_validate(item)
                for item in _load_list(args.expected_path)
            )
            reports = tuple(
                PaperHealthReport.model_validate(item) for item in _load_list(args.reports_path)
            )
            report = summarize_paper_cohort(reports, expected)
        except (OSError, ValidationError, ValueError, TypeError, sqlite3.Error) as exc:
            del exc
            _print_json({"error_code": "invalid_input", "status": "error"})
            return 2
        payload = report.model_dump(mode="json")
        payload["status"] = report.cohort_status
        _print_json(payload)
        return 0

    try:
        as_of_dt = (
            datetime.fromisoformat(args.as_of.replace("Z", "+00:00")).astimezone(UTC)
            if args.as_of
            else None
        )
        health_reports, report = evaluate_paper_cohort_snapshot(
            ledger_db=args.ledger_path,
            lifecycle_db=args.lifecycle_path,
            observations_db=args.observations_path,
            manifest=args.manifest_path,
            as_of=as_of_dt,
            max_mark_age_seconds=args.max_mark_age_seconds,
            required_days=args.required_days,
            output_dir=args.output_dir,
        )
    except (OSError, ValidationError, ValueError, TypeError, sqlite3.Error) as exc:
        _print_json({"error_code": "invalid_input", "error": str(exc), "status": "error"})
        return 2

    payload = report.model_dump(mode="json")
    payload["status"] = report.cohort_status
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
