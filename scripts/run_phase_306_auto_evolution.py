"""Phase 306: Continuous Self-Learning Loop, Strategy Autopsy & Auto-Evolution Runner.

Executes deterministic multi-track simulation:
1. Track 1: Strategy Autopsy & Multi-Factor Trade Attribution Decomposition
2. Track 2: Continuous Rolling Performance & Health Tier Classification
3. Track 3: Genetic/Bayesian Mutation Generation & Safe Parameter Clamping
4. Track 4: Shadow Staging Promotion Evaluation, Solvency Zero-Drift, and Merkle DAG Proof Chain

Usage:
    uv run python scripts/run_phase_306_auto_evolution.py [--track all|1|2|3|4]
    uv run python scripts/run_phase_306_auto_evolution.py --verify-only
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

from autonomous_futures.feed.auto_evolution import (  # noqa: E402
    DEFAULT_PHASE306_OUTPUT_DIR,
    UPSTREAM_PHASE305_ROOT_HASH,
    run_phase_306_simulation,
    verify_phase_306_merkle_dag,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_phase_306_auto_evolution")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 306: Continuous Self-Learning Loop, Strategy Autopsy & Auto-Evolution Runner"
        )
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
        default=DEFAULT_PHASE306_OUTPUT_DIR,
        help="Directory to persist research artifacts and telemetry",
    )
    parser.add_argument(
        "--starting-equity",
        type=float,
        default=100.0,
        help="Starting equity in USDT for double-entry ledger (default: 100.00)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify cryptographic Merkle DAG hash chain of existing artifacts only",
    )
    parser.add_argument(
        "--parent-root-hash",
        type=str,
        default=UPSTREAM_PHASE305_ROOT_HASH,
        help="Parent Phase 305 Merkle root hash",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    output_dir = args.output_dir
    parent_root = args.parent_root_hash

    if args.verify_only:
        logger.info("Executing Phase 306 verification-only check...")
        is_valid = verify_phase_306_merkle_dag(
            output_dir=output_dir,
            parent_merkle_root=parent_root,
        )
        if is_valid:
            logger.info("Phase 306 Merkle DAG hash chain verified successfully!")
            print("PHASE 306 MERKLE DAG INTEGRITY: VERIFIED")
            return 0
        else:
            logger.error("Phase 306 Merkle DAG integrity verification failed!")
            print("PHASE 306 MERKLE DAG INTEGRITY: FAILED")
            return 1

    logger.info(f"Starting Phase 306 Auto-Evolution Simulation (Output: {output_dir})...")
    summary = run_phase_306_simulation(
        output_dir=output_dir,
        starting_equity=args.starting_equity,
        parent_merkle_root=parent_root,
    )

    logger.info("Simulation completed. Validating Merkle DAG integrity...")
    is_valid = verify_phase_306_merkle_dag(
        output_dir=output_dir,
        parent_merkle_root=parent_root,
    )
    if not is_valid:
        logger.error("Cryptographic verification failed after generation!")
        return 1

    solvency = summary.get("solvency", {})
    perf = summary.get("performance", {})
    merkle_root = summary.get("merkle_root", "")

    logger.info("==================================================================")
    logger.info("Phase 306 Auto-Evolution Simulation Succeeded")
    logger.info("==================================================================")
    logger.info(f"Merkle Root: {merkle_root}")
    logger.info(f"Parent Root: {parent_root}")
    logger.info(f"Autopsies Conducted: {perf.get('total_autopsies_conducted')}")
    logger.info(f"Mean Timing Error: {perf.get('mean_entry_timing_error_bps')} bps")
    logger.info(f"Mean Hawkes Slip Drag: {perf.get('mean_hawkes_slip_drag_bps')} bps")
    logger.info(f"Mean Adverse Selection: {perf.get('mean_adverse_selection_bps')} bps")
    logger.info(f"Mean Realized Edge: {perf.get('mean_realized_edge_bps')} bps")
    logger.info(f"Staged Mutations: {perf.get('staged_mutations_count')}")
    logger.info(f"Promoted Candidates: {perf.get('promoted_candidates_count')}")
    logger.info(f"Cash Balance: {solvency.get('cash_balance_usdt')} USDT")
    logger.info(f"Realized PnL: {solvency.get('realized_pnl_usdt')} USDT")
    logger.info(f"Solvency Drift: {solvency.get('drift_usdt')} USDT")
    logger.info(f"Zero Drift Valid: {solvency.get('zero_drift_valid')}")
    logger.info("==================================================================")

    # Print summary JSON
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
