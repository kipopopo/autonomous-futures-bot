"""Read-only CLI health and daily risk watchdog for the qualified portfolio runtime.

Audits the durable runtime directory (`exchange-account.json`, `daily-risk.json`,
`runtime-health.json`, and `portfolio-scanner-state.json`) and optional systemd
service status without touching the active writer lease or mutating trading state.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from autonomous_futures.execution.runtime_watchdog import (  # noqa: E402
    dispatch_watchdog_alerts,
    evaluate_runtime_watchdog,
    send_watchdog_test_alert,
    write_watchdog_report,
)

DEFAULT_STORAGE_DIR = Path("/opt/autonomous-futures-bot/runtime/qualified-testnet")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-dir", type=Path, default=DEFAULT_STORAGE_DIR)
    parser.add_argument("--max-account-age-ms", type=int, default=30_000)
    parser.add_argument("--max-health-age-ms", type=int, default=30_000)
    parser.add_argument("--max-scanner-age-ms", type=int, default=1_200_000)
    parser.add_argument("--check-systemd", action="store_true")
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Atomically write watchdog-report.json inside --storage-dir.",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Evaluate state transitions & cooldowns and send Telegram/Webhook alerts.",
    )
    parser.add_argument(
        "--send-test-alert",
        action="store_true",
        help="Send a one-shot verification test alert without mutating watchdog-alert-state.json.",
    )
    parser.add_argument(
        "--alert-cooldown-seconds",
        type=int,
        default=900,
        help="Minimum cooldown in seconds between repeated alerts of the same severity.",
    )
    parser.add_argument(
        "--min-warning-consecutive",
        type=int,
        default=2,
        help="Minimum consecutive WARNING ticks required before sending a warning alert.",
    )
    parser.add_argument(
        "--webhook-url",
        type=str,
        default=None,
        help="Optional webhook URL override for watchdog alert notifications.",
    )
    parser.add_argument(
        "--dry-run-notify",
        action="store_true",
        help="Run the alert state machine without making external HTTP requests.",
    )
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Return exit code 1 when watchdog status is WARNING as well as CRITICAL.",
    )
    args = parser.parse_args(argv)

    report = evaluate_runtime_watchdog(
        args.storage_dir,
        max_account_age_ms=args.max_account_age_ms,
        max_health_age_ms=args.max_health_age_ms,
        max_scanner_age_ms=args.max_scanner_age_ms,
        check_systemd=args.check_systemd,
    )
    if args.notify:
        dispatch_watchdog_alerts(
            args.storage_dir,
            report,
            cooldown_seconds=args.alert_cooldown_seconds,
            min_warning_consecutive=args.min_warning_consecutive,
            webhook_url=args.webhook_url,
            dry_run=args.dry_run_notify,
        )
    if args.send_test_alert:
        test_res = send_watchdog_test_alert(
            report,
            webhook_url=args.webhook_url,
            dry_run=args.dry_run_notify,
        )
        if not test_res.get("delivery_ok", False):
            print(json.dumps(report, indent=2, sort_keys=True))
            return 1
    if args.write_report and args.storage_dir.is_dir():
        report_path = write_watchdog_report(args.storage_dir, report)
        report["persisted_report_path"] = str(report_path)

    print(json.dumps(report, indent=2, sort_keys=True))

    if report["status"] == "CRITICAL":
        return 1
    if args.fail_on_warning and report["status"] == "WARNING":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
