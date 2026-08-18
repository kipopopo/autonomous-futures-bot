"""Summarize explicit paper health reports for human review only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from .cohort import summarize_paper_cohort
from .health import PaperHealthReport
from .observation import PaperObservationBinding


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize read-only paper cohort readiness.")
    parser.add_argument("--expected-path", type=Path, required=True)
    parser.add_argument("--reports-path", type=Path, required=True)
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
    try:
        expected = tuple(
            PaperObservationBinding.model_validate(item) for item in _load_list(args.expected_path)
        )
        reports = tuple(
            PaperHealthReport.model_validate(item) for item in _load_list(args.reports_path)
        )
        report = summarize_paper_cohort(reports, expected)
    except (OSError, ValidationError, ValueError, TypeError) as exc:
        del exc
        _print_json({"error_code": "invalid_input", "status": "error"})
        return 2
    payload = report.model_dump(mode="json")
    payload["status"] = report.cohort_status
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
