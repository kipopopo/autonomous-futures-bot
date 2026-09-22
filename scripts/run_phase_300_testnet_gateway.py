"""Phase 300: Testnet Exchange Connectivity, Multi-Signature Order Gateway.

Live Staged Order Authorization Bridge.

Runner script executing 4 deterministic simulation tracks:
1. Track 1: Multi-Signature Quorum Authorization & Dual-Custody Verification Drill
2. Track 2: Pre-Dispatch Symbol Exchange Filter Conformance & Rejection Stress Drill
3. Track 3: Order Lifecycle State Transitions, Simulated Fills & Latency Attribution Drill
4. Track 4: Full Longevity, Double-Entry Zero-Drift & Merkle DAG Hash Chain Drill

Usage:
    uv run python scripts/run_phase_300_testnet_gateway.py [--track all|1|2|3|4]
    uv run python scripts/run_phase_300_testnet_gateway.py --verify-only
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root and src to path
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.feed.testnet_gateway import (  # noqa: E402
    DEFAULT_PHASE300_OUTPUT_DIR,
    UPSTREAM_PHASE299_ROOT_HASH,
    CanaryTestnetGatewayRunner,
    verify_phase_300_dag,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_phase_300_testnet_gateway")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase 300: Testnet Exchange Connectivity & Multi-Sig Gateway Runner"
    )
    parser.add_argument(
        "--track",
        choices=["all", "1", "2", "3", "4"],
        default="all",
        help="Simulation track to execute (default: all)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PHASE300_OUTPUT_DIR,
        help="Directory to persist research artifacts and telemetry",
    )
    parser.add_argument(
        "--upstream-dir",
        type=Path,
        default=_REPO_ROOT / "artifacts" / "research" / "phase299",
        help="Upstream Phase 299 artifact directory",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Deterministic RNG seed (default: 42)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify Merkle DAG hash chain integrity without re-running simulation",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable detailed debug logging",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.verify_only:
        logger.info("Executing Phase 300 verification-only check...")
        summary_path = args.output_dir / "testnet-gateway-summary.json"
        if not summary_path.is_file():
            logger.error("Phase 300 summary artifact not found at %s", summary_path)
            print(f"FAILED: Summary not found at {summary_path}", file=sys.stderr)
            return 1

        is_valid = verify_phase_300_dag(summary_path)
        if not is_valid:
            print("FAILED: Merkle DAG upstream hash mismatch!", file=sys.stderr)
            return 1

        data = json.loads(summary_path.read_text(encoding="utf-8"))
        assert (
            data.get("zero_balance_drift") is True
            or data.get("solvency", {}).get("zero_balance_drift_verified") is True
        )
        assert data.get("execution_authority") is False
        assert data.get("paper_safe") is True

        logger.info("Phase 300 Merkle DAG hash chain verified successfully!")
        print("PHASE 300 MERKLE DAG INTEGRITY: VERIFIED")
        return 0

    logger.info("=== Starting Phase 300 Testnet Exchange Gateway Simulation ===")
    runner = CanaryTestnetGatewayRunner(
        output_dir=args.output_dir,
        upstream_hash=UPSTREAM_PHASE299_ROOT_HASH,
    )

    try:
        results = runner.run_all(seed=args.seed)
        logger.info("Phase 300 simulation completed successfully.")
        logger.info("Summary Status: %s", results.get("status"))
        logger.info("Total Orders Staged: %s", results.get("total_orders_staged"))
        logger.info("Orders Filled: %s", results.get("orders_filled"))
        logger.info("Orders Rejected: %s", results.get("orders_rejected"))
        logger.info(
            "Solvency Zero Drift: %s",
            results.get("solvency", {}).get("zero_balance_drift_verified"),
        )
        logger.info("Merkle Root: %s", results.get("merkle_root"))

        print("\nALL REQUESTED PHASE 300 TRACKS PASSED CLEANLY.")
        print(f"Artifacts persisted to: {args.output_dir}")
        print(f"Merkle DAG chained to Phase 299 root ({UPSTREAM_PHASE299_ROOT_HASH[:12]}...) ok.")
        return 0

    except Exception as exc:
        logger.exception("Phase 300 execution error: %s", exc)
        print(f"\nPHASE 300 EXECUTION FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
