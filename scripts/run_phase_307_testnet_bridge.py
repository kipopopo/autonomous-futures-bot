"""Phase 307: Binance Futures Testnet Live API Integration & Order Dispatch Bridge Runner.

Executes deterministic multi-track certification:
1. Track 1: REST API Connection Handshake, HMAC-SHA256 Signer & Clock Drift Sync
2. Track 2: Exchange Filter Validation, Micro Child Order Slicing (<= 5.00 USDT, ROUND_DOWN)
3. Track 3: Order Dispatch Lifecycle, User Data Stream Events & listenKey Keepalive
4. Track 4: Centralized Solvency Double-Entry Zero-Drift & SHA-256 Merkle DAG Chain Linking

Usage:
    python scripts/run_phase_307_testnet_bridge.py
    python scripts/run_phase_307_testnet_bridge.py --verify-only
"""

from __future__ import annotations

import argparse
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

from autonomous_futures.feed.testnet_bridge import (  # noqa: E402
    DEFAULT_PHASE307_OUTPUT_DIR,
    UPSTREAM_PHASE306_ROOT_HASH,
    run_phase_307_simulation,
    verify_phase_307_merkle_dag,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_phase_307_testnet_bridge")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 307: Binance Futures Testnet Live API Integration & Order Dispatch Bridge Runner"
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PHASE307_OUTPUT_DIR,
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
        default=UPSTREAM_PHASE306_ROOT_HASH,
        help="Parent Phase 306 Merkle root hash",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    output_dir = args.output_dir
    parent_root = args.parent_root_hash

    if args.verify_only:
        logger.info("Executing Phase 307 verification-only check...")
        is_valid = verify_phase_307_merkle_dag(
            output_dir=output_dir,
            parent_merkle_root=parent_root,
        )
        if is_valid:
            logger.info("Phase 307 Merkle DAG hash chain verified successfully!")
            print("PHASE 307 MERKLE DAG INTEGRITY: VERIFIED")
            return 0
        else:
            logger.error("Phase 307 Merkle DAG integrity verification failed!")
            print("PHASE 307 MERKLE DAG INTEGRITY: FAILED")
            return 1

    logger.info("Starting Phase 307 simulation runner...")
    logger.info(f"Target Output Directory: {output_dir}")
    logger.info(f"Parent Merkle Root Hash: {parent_root}")

    results = run_phase_307_simulation(
        output_dir=output_dir,
        starting_equity=args.starting_equity,
        parent_merkle_root=parent_root,
    )

    logger.info(
        f"Phase 307 Simulation Completed: Status={results.get('status')}, "
        f"Orders Dispatched={results.get('performance', {}).get('total_orders_dispatched')}, "
        f"Merkle Root={results.get('merkle_root')}"
    )

    # Verification post-run
    is_valid = verify_phase_307_merkle_dag(
        output_dir=output_dir,
        parent_merkle_root=parent_root,
    )
    if is_valid:
        logger.info("Phase 307 Merkle DAG hash chain self-verification PASSED!")
        print(f"PHASE 307 MERKLE ROOT: {results.get('merkle_root')}")
        return 0
    else:
        logger.error("Phase 307 self-verification FAILED!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
