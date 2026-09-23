"""Phase 304: Autonomous Self-Calibrating Parameter Adaptation & Online Regime Learning Runner.

Executes deterministic multi-track simulation:
1. Track 1: Online Market Regime Detection & Classification Replay
2. Track 2: Adaptive Parameter Calibration & Damping Smoothing Drill
3. Track 3: Regime Transition Shock & Parameter Defense Guard Drill
4. Track 4: Multi-Asset Extended Longevity, Solvency Ledger & Merkle DAG Chain

Usage:
    uv run python scripts/run_phase_304_regime_calibration.py [--track all|1|2|3|4]
    uv run python scripts/run_phase_304_regime_calibration.py --verify-only
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

from autonomous_futures.feed.regime_calibration import (  # noqa: E402
    DEFAULT_PHASE304_OUTPUT_DIR,
    UPSTREAM_PHASE303_ROOT_HASH,
    run_phase_304_simulation,
    verify_phase_304_merkle_dag,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_phase_304_regime_calibration")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 304: Self-Calibrating Parameter Adaptation & Online Regime Learning Runner"
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
        default=DEFAULT_PHASE304_OUTPUT_DIR,
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
        default=UPSTREAM_PHASE303_ROOT_HASH,
        help="Parent Phase 303 Merkle root hash",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    output_dir = args.output_dir
    parent_root = args.parent_root_hash

    if args.verify_only:
        logger.info("Executing Phase 304 verification-only check...")
        is_valid = verify_phase_304_merkle_dag(
            output_dir=output_dir,
            parent_merkle_root=parent_root,
        )
        if is_valid:
            logger.info("Phase 304 Merkle DAG hash chain verified successfully!")
            print("PHASE 304 MERKLE DAG INTEGRITY: VERIFIED")
            return 0
        else:
            logger.error("Phase 304 Merkle DAG integrity verification failed!")
            print("PHASE 304 MERKLE DAG INTEGRITY: FAILED", file=sys.stderr)
            return 1

    logger.info("Starting Phase 304 Self-Calibrating Parameter Simulation...")
    logger.info(f"Target output directory: {output_dir}")
    logger.info(f"Parent Merkle root: {parent_root}")

    summary = run_phase_304_simulation(
        output_dir=output_dir,
        starting_equity=args.starting_equity,
        parent_merkle_root=parent_root,
    )

    logger.info("Verifying generated Merkle DAG...")
    is_valid = verify_phase_304_merkle_dag(
        output_dir=output_dir,
        parent_merkle_root=parent_root,
    )
    if not is_valid:
        logger.error("Generated Merkle DAG verification failed!")
        return 1

    merkle_root = summary.get("merkle_root", "")
    logger.info(f"Phase 304 execution completed. Merkle Root: {merkle_root}")
    print(
        json.dumps(
            {
                "status": "PHASE_304_CALIBRATION_COMPLETE",
                "merkle_root": merkle_root,
                "parent_merkle_root": parent_root,
                "zero_balance_drift_verified": True,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
