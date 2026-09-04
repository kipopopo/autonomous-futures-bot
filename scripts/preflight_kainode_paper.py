"""Standalone operator CLI preflight check for Kainode paper daemon environment."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.paper_preflight import (  # noqa: E402
    DEFAULT_BARS,
    DEFAULT_STARTING_EQUITY,
    DEFAULT_STORAGE_DIR,
    _sanitize_error_text,
    validate_paper_preflight,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify Kainode paper daemon host, storage directory, and execute smoke test."
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=DEFAULT_STORAGE_DIR,
        help=f"Directory for SQLite paper databases and artifacts (default: {DEFAULT_STORAGE_DIR})",
    )
    parser.add_argument(
        "--starting-equity",
        type=Decimal,
        default=DEFAULT_STARTING_EQUITY,
        help=f"Shared portfolio margin baseline in USDT (default: {DEFAULT_STARTING_EQUITY})",
    )
    parser.add_argument(
        "--bars",
        type=int,
        default=DEFAULT_BARS,
        help=f"Number of synthetic 5m bars for smoke test simulation (default: {DEFAULT_BARS})",
    )
    parser.add_argument(
        "--smoke-test",
        dest="smoke_test",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Execute bounded synthetic bar simulation smoke test (default: enabled)",
    )
    parser.add_argument(
        "--skip-host-check",
        action="store_true",
        default=False,
        help="Skip Linux OS and UID verification checks for cross-platform/local testing",
    )
    parser.add_argument(
        "--credentials-dir",
        type=Path,
        default=None,
        help="Optional credentials directory to scan for forbidden exchange credentials",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to save structured JSON report",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code != 0 else 0

    if args.starting_equity <= Decimal("0"):
        print(
            json.dumps(
                {
                    "error_code": "invalid_input",
                    "message": f"starting_equity must be positive, got {args.starting_equity}",
                }
            )
        )
        return 2

    if args.bars < 30:
        print(
            json.dumps(
                {
                    "error_code": "invalid_input",
                    "message": f"bars must be at least 30, got {args.bars}",
                }
            )
        )
        return 2

    try:
        report = validate_paper_preflight(
            storage_dir=args.storage_dir,
            starting_equity=args.starting_equity,
            bars=args.bars,
            smoke_test=args.smoke_test,
            skip_host_check=args.skip_host_check,
            credentials_dir=args.credentials_dir,
        )
    except (OSError, ValueError) as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "invalid_input", "message": sanitized}))
        return 2
    except Exception as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "unexpected_error", "message": sanitized}))
        return 2

    report_payload = report.model_dump(mode="json")
    json_output = json.dumps(report_payload, indent=2, sort_keys=True)
    print(json_output)

    if args.output_json is not None:
        try:
            args.output_json.parent.mkdir(parents=True, exist_ok=True)
            args.output_json.write_text(json_output, encoding="utf-8")
        except OSError as exc:
            sanitized = _sanitize_error_text(str(exc))
            del exc
            print(
                json.dumps(
                    {
                        "error_code": "output_write_failure",
                        "message": f"failed to write output json: {sanitized}",
                    }
                )
            )
            return 3

    return 0 if report.ready else 3


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = ["main"]
