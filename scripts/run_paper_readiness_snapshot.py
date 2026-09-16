#!/usr/bin/env python3
"""Phase 265: Autonomous Paper Cohort Readiness Snapshot CLI.

Executes automated cohort readiness evaluation combining aggregate_paper_health
and summarize_paper_cohort directly from isolated paper SQLite stores.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from autonomous_futures.paper.cohort import evaluate_paper_cohort_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate paper cohort readiness report snapshot from SQLite stores."
    )
    parser.add_argument(
        "--ledger-db",
        "--ledger-path",
        type=Path,
        default=Path("paper-ledger.sqlite3"),
        help="Path to paper-ledger.sqlite3",
    )
    parser.add_argument(
        "--lifecycle-db",
        "--lifecycle-path",
        type=Path,
        default=Path("paper-lifecycle.sqlite3"),
        help="Path to paper-lifecycle.sqlite3",
    )
    parser.add_argument(
        "--observations-db",
        "--observations-path",
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
        help="Directory to save paper-cohort-readiness-report.json and per-symbol reports",
    )
    parser.add_argument(
        "--as-of",
        type=str,
        default=None,
        help="ISO timestamp string for snapshot evaluation",
    )
    parser.add_argument(
        "--max-mark-age-seconds",
        type=int,
        default=86400,
        help="Maximum allowed age for active lifecycle marks before marking stale",
    )
    parser.add_argument(
        "--required-days",
        type=int,
        default=7,
        help="Minimum required observation days for candidate maturity",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        as_of = (
            datetime.fromisoformat(args.as_of.replace("Z", "+00:00")).astimezone(UTC)
            if args.as_of
            else None
        )

        health_reports, cohort_report = evaluate_paper_cohort_snapshot(
            ledger_db=args.ledger_db,
            lifecycle_db=args.lifecycle_db,
            observations_db=args.observations_db,
            manifest=args.manifest_path,
            as_of=as_of,
            max_mark_age_seconds=args.max_mark_age_seconds,
            required_days=args.required_days,
            output_dir=args.output_dir,
        )
    except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
        err_payload = {
            "error": str(exc),
            "error_code": "invalid_input",
            "status": "error",
        }
        print(json.dumps(err_payload, indent=2, sort_keys=True), file=sys.stderr)
        return 2

    report_payload = cohort_report.model_dump(mode="json")
    report_payload["status"] = cohort_report.cohort_status
    print(json.dumps(report_payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
