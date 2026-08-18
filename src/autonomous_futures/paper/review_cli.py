"""Record one explicit human paper-review checkpoint."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from .cohort import PaperCohortReadinessReport
from .review import create_paper_review_checkpoint
from .sqlite_review import SqlitePaperReviews


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record a paper human-review checkpoint.")
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--review-path", type=Path, required=True)
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--reviewed-at", required=True)
    parser.add_argument(
        "--decision",
        choices=("accept_paper_observation", "needs_attention", "reject"),
        required=True,
    )
    parser.add_argument("--review-notes", required=True)
    return parser


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValueError("invalid reviewed-at timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("reviewed-at must be timezone-aware UTC")
    return parsed.astimezone(UTC)


def _load_report(path: Path) -> PaperCohortReadinessReport:
    try:
        return PaperCohortReadinessReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("invalid cohort report") from exc


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = _load_report(args.report_path)
        decision = args.decision
        checkpoint = create_paper_review_checkpoint(
            report,
            review_id=args.review_id,
            reviewer_id=args.reviewer_id,
            reviewed_at=_parse_utc(args.reviewed_at),
            decision=decision,
            review_notes=args.review_notes,
        )
        SqlitePaperReviews(args.review_path).append(checkpoint)
    except (OSError, ValidationError, ValueError) as exc:
        del exc
        _print_json({"error_code": "invalid_input", "status": "error"})
        return 2
    payload = checkpoint.model_dump(mode="json")
    payload["status"] = "recorded"
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
