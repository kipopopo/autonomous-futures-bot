#!/usr/bin/env python3
"""Phase 311: Binance Futures Testnet Execution Drill CLI Harness.

Dedicated, non-disruptive execution drill CLI triggering authentic signed
micro maker limit orders, automated +2.0x ATR TP and -1.2x ATR SL brackets,
and mathematical zero-drift balance governance without interfering with the
24/7 background trader daemon.

Usage:
    python scripts/run_testnet_execution_drill.py --symbol SOLUSDT --dry-run
    python scripts/run_testnet_execution_drill.py --symbol SOLUSDT --side BUY --notional 5.00
    python scripts/run_testnet_execution_drill.py --verify-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.feed.execution_drill import (  # noqa: E402
    DEFAULT_CHILD_CAP_USDT,
    ExecutionDrillConfig,
    ExecutionDrillEngine,
    verify_phase_311_artifacts,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("scripts.run_testnet_execution_drill")


def parse_arguments() -> argparse.Namespace:
    """Parses command-line arguments for the testnet execution drill."""
    parser = argparse.ArgumentParser(
        description="Phase 311 Testnet Execution Drill CLI Harness",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="SOLUSDT",
        help="Target trading pair (e.g. SOLUSDT, ETHUSDT)",
    )
    parser.add_argument(
        "--side",
        type=str,
        choices=["BUY", "SELL"],
        default="BUY",
        help="Order entry side",
    )
    parser.add_argument(
        "--notional",
        type=float,
        default=5.00,
        help="Target order notional in USDT (capped at <= 5.00 USDT)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute in authentic signed offline mock mode without wire dispatch",
    )
    parser.add_argument(
        "--auto-close",
        "--cleanup",
        dest="cleanup",
        action="store_true",
        default=True,
        help="Automatically cancel drill brackets and flatten drill position",
    )
    parser.add_argument(
        "--no-cleanup",
        dest="cleanup",
        action="store_false",
        help="Do not automatically cancel brackets or flatten position",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify Merkle DAG and zero-drift balance invariant of existing artifacts",
    )
    parser.add_argument(
        "--storage-dir",
        type=str,
        default="artifacts/research/phase311",
        help="Directory for SQLite telemetry, JSONL logs, and Merkle reports",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output execution summary strictly as JSON",
    )
    return parser.parse_args()


def print_cli_summary(summary: dict[str, Any]) -> None:
    """Formats and prints executive summary report to terminal."""
    solvency = summary.get("solvency", {})
    hashes = summary.get("artifact_hashes", {})
    zd_status = "PASS (0.00 drift)" if solvency.get("zero_balance_drift") else "FAIL"

    print("\n" + "=" * 70)
    print("    PHASE 311: TESTNET EXECUTION CANARY DRILL REPORT")
    print("=" * 70)
    print(f"  Phase Identifier : {summary.get('phase', 'phase_311')}")
    print(f"  Upstream Parent  : {summary.get('upstream_hash')}")
    print(f"  Merkle Root      : {summary.get('merkle_root')}")
    print(f"  Phase Hash       : {summary.get('phase_hash')}")
    print("-" * 70)
    print("  DOUBLE-ENTRY SOLVENCY RECONCILIATION:")
    print(f"    Starting Equity : ${solvency.get('starting_equity', 0.0):.2f} USDT")
    print(f"    Available Cash  : ${solvency.get('cash', 0.0):.2f} USDT")
    print(f"    Allocated Margin: ${solvency.get('allocated_margin', 0.0):.2f} USDT")
    print(f"    Realized PnL    : ${solvency.get('realized_pnl', 0.0):.4f} USDT")
    print(f"    Total Fees      : ${solvency.get('total_fees', 0.0):.5f} USDT")
    print(f"    Drift (|Delta|) : {solvency.get('drift', 0.0):.1e} USDT")
    print(f"    Zero-Drift OK   : {zd_status}")
    print("-" * 70)
    print("  CRYPTOGRAPHIC ARTIFACT HASHES:")
    for name, hval in hashes.items():
        print(f"    {name:<15}: {hval}")
    print("=" * 70 + "\n")


async def async_main() -> int:
    """Asynchronous entry point for execution drill runner."""
    args = parse_arguments()
    storage_path = Path(args.storage_dir)

    # 1. Verification Mode
    if args.verify_only:
        logger.info("Executing verification on artifacts in %s...", storage_path)
        is_valid = verify_phase_311_artifacts(storage_path)
        if is_valid:
            print("\n[SUCCESS] Phase 311 Merkle DAG and Solvency Invariant: VERIFIED\n")
            return 0
        print("\n[FAILED] Phase 311 Verification FAILED.\n")
        return 1

    # 2. Execution Drill Mode
    capped_notional = min(Decimal(str(args.notional)), DEFAULT_CHILD_CAP_USDT)
    config = ExecutionDrillConfig(
        symbol=args.symbol.upper(),
        side=args.side.upper(),
        requested_notional=capped_notional,
        dry_run=args.dry_run,
        cleanup=args.cleanup,
        auto_close=args.cleanup,
        storage_dir=storage_path,
    )

    engine = ExecutionDrillEngine(config=config)
    try:
        summary = await engine.execute_drill()
    except Exception as exc:
        logger.error("Execution drill halted with error: %s", exc, exc_info=True)
        return 1

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print_cli_summary(summary)

    return 0


def main() -> None:
    """Synchronous entry point."""
    code = asyncio.run(async_main())
    sys.exit(code)


if __name__ == "__main__":
    main()
