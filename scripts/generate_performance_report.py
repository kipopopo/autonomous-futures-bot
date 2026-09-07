#!/usr/bin/env python3
"""Autonomous Futures Bot: Institutional Performance Analytics & Daily Report CLI.

Generates structured JSON performance reports and MarkdownV2 summaries from
read-only SQLite ledgers, with optional Telegram dispatch.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Ensure src/ is on sys.path
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.analytics import (  # noqa: E402
    format_daily_performance_report,
    generate_daily_performance_report,
)
from autonomous_futures.notify.telegram import (  # noqa: E402
    TelegramNotifierClient,
    resolve_telegram_credentials,
)

logger = logging.getLogger("generate_performance_report")


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for performance report generator."""
    parser = argparse.ArgumentParser(
        prog="generate_performance_report.py",
        description=(
            "Autonomous Futures Bot: Institutional Performance Analytics & Daily Report CLI"
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=Path(os.environ.get("AUTONOMOUS_FUTURES_STORAGE_DIR", "artifacts/paper_live")),
        help="Path to storage directory containing SQLite ledgers and health checkpoints",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date for evaluation (YYYY-MM-DD, defaults to current UTC date)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Evaluation lookback window in days (e.g. 1 for daily, 7 for weekly rolling)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output serialized JSON report payload to stdout",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        default=False,
        help="Output escaped Telegram MarkdownV2 formatted report to stdout",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Custom destination path for JSON report persistence "
            "(defaults to storage_dir/reports/daily-performance-<date>.json)"
        ),
    )
    parser.add_argument(
        "--dispatch-telegram",
        action="store_true",
        default=False,
        help="Immediately dispatch MarkdownV2 report to configured Telegram chat",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help=(
            "Evaluate and format report in memory without writing to disk "
            "or making live Telegram HTTP calls"
        ),
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT",
        help="Comma-separated list of symbols to include in attribution",
    )
    return parser


def main() -> int:
    """CLI runner entrypoint."""
    if sys.platform == "win32":
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
        if hasattr(sys.stderr, "reconfigure"):
            try:
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    parser = build_arg_parser()
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 1. Validate date format if provided
    eval_date_str = args.date
    if eval_date_str is not None:
        try:
            datetime.strptime(eval_date_str, "%Y-%m-%d")
        except ValueError:
            logger.error("Invalid date format: '%s'. Expected YYYY-MM-DD.", eval_date_str)
            return 1
    else:
        eval_date_str = datetime.now(UTC).date().isoformat()

    # 2. Validate storage dir
    storage_dir = Path(args.storage_dir)
    if not storage_dir.exists():
        logger.error("Storage directory does not exist: %s", storage_dir)
        return 2

    # Parse symbols
    symbol_list = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    # 3. Generate Report
    try:
        report = generate_daily_performance_report(
            storage_dir=storage_dir,
            report_date=eval_date_str,
            days=args.days,
            symbols=symbol_list,
        )
        report_dict = report.to_dict()
    except Exception as exc:
        logger.error("Failed to generate performance report: %s", exc, exc_info=True)
        return 2

    # 4. Format MarkdownV2
    markdown_text = format_daily_performance_report(report_dict)

    # 5. Output handling
    if args.json:
        print(json.dumps(report_dict, indent=2))
    elif args.markdown:
        print(markdown_text)
    else:
        # Default: print MarkdownV2 representation
        print(markdown_text)

    # 6. Disk persistence (unless dry-run)
    if not args.dry_run:
        out_path = args.output or (
            storage_dir / "reports" / f"daily-performance-{eval_date_str}.json"
        )
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = out_path.with_name(
                f"{out_path.name}.tmp.{os.getpid()}_{uuid.uuid4().hex[:8]}"
            )
            try:
                tmp_path.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")
                tmp_path.replace(out_path)
                logger.info("Saved performance report to %s", out_path)
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
        except OSError as exc:
            logger.error("Failed to save report to %s: %s", out_path, exc)
            return 2

    # 7. Telegram dispatch if requested
    if args.dispatch_telegram:
        try:
            config = resolve_telegram_credentials(
                dry_run=args.dry_run,
                storage_dir=storage_dir,
            )
            client = TelegramNotifierClient(config)
            success = client.send_message(markdown_text)
            client.close()
            if not success and not config.dry_run:
                logger.error("Telegram dispatch failed.")
                return 3
            logger.info("Successfully dispatched report to Telegram.")
        except Exception as exc:
            logger.error("Telegram dispatch encountered an exception: %s", exc, exc_info=True)
            return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
