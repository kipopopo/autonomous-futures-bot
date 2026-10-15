"""Safe non-executing pre-cutover preparation CLI for the qualified portfolio runtime.

Supports:
1. Read-only inspection of live Binance Futures Testnet flat-account status and leverage.
2. `--apply-leverage`: Normalizes `AVAXUSDT`, `ETHUSDT`, and `SOLUSDT` leverage to `1x`
   via `POST /fapi/v1/leverage` after verifying the account is flat with 0 open orders.
3. `--bootstrap-daily-risk`: Reconstructs authentic UTC midnight equity when the account
   is flat with zero intraday trading income ambiguity, initializes `daily-risk.json`,
   captures fresh `exchange-account.json` evidence, and verifies `remaining_daily_budget`
   and `verify_execution_domain`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from autonomous_futures.execution.pre_cutover_preparation import (  # noqa: E402
    prepare_portfolio_cutover,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--storage-dir", type=Path, required=True)
    parser.add_argument("--equity-basis", default="ACCOUNT", choices=["ACCOUNT"])
    parser.add_argument(
        "--apply-leverage",
        action="store_true",
        help="Normalize portfolio symbol leverages to match the researched execution domain (1x).",
    )
    parser.add_argument(
        "--bootstrap-daily-risk",
        action="store_true",
        help="Bootstrap daily-risk.json and refresh exchange-account.json on a flat account.",
    )
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(
            prepare_portfolio_cutover(
                repo=args.repo,
                storage_dir=args.storage_dir,
                equity_basis=args.equity_basis,
                apply_leverage=args.apply_leverage,
                bootstrap_daily_risk=args.bootstrap_daily_risk,
            )
        )
    except Exception as exc:
        # Never print signed request URLs or credential-bearing transport exceptions.
        print(
            json.dumps(
                {
                    "preparation_failed": True,
                    "error_type": type(exc).__name__,
                    "reason": str(exc) if isinstance(exc, ValueError) else "transport_or_api_error",
                },
                indent=2,
                sort_keys=True,
            ),
            flush=True,
        )
        return 1
    print(json.dumps(report, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
