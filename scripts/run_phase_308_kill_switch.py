"""Phase 308: Capital Safety Governance, Multi-Signature & Hardware/OS Kill-Switch Engine Runner.

Executes deterministic multi-tier verification:
1. Track 1: M-of-N Cryptographic Multi-Sig Quorum Pipeline (Nonce Replay & Expire Validation)
2. Track 2: Three-Tier Kill-Switch Containment (Soft Pause, Lockout & Hardware OS Panic)
3. Track 3: Emergency Position Flattening & In-Memory Credential Scrubbing (Zeroization)
4. Track 4: Centralized Solvency Double-Entry Zero-Drift & SHA-256 Merkle DAG Hash Chain Linking

Usage:
    python scripts/run_phase_308_kill_switch.py
    python scripts/run_phase_308_kill_switch.py --verify-only
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

from autonomous_futures.safety.kill_switch import (  # noqa: E402
    PHASE_307_PARENT_MERKLE_ROOT,
    run_phase_308_simulation,
    verify_phase_308_merkle_dag,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_phase_308_kill_switch")

DEFAULT_PHASE308_OUTPUT_DIR = Path("artifacts/research/phase308")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 308: Capital Safety Governance, Multi-Signature & "
            "Hardware/OS Kill-Switch Engine Runner"
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PHASE308_OUTPUT_DIR,
        help="Directory to persist research artifacts and telemetry",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify cryptographic Merkle DAG hash chain of existing artifacts only",
    )
    parser.add_argument(
        "--parent-root-hash",
        type=str,
        default=PHASE_307_PARENT_MERKLE_ROOT,
        help="Parent Phase 307 Merkle root hash",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    output_dir = args.output_dir
    parent_root = args.parent_root_hash

    if args.verify_only:
        logger.info("Executing Phase 308 verification-only check...")
        is_valid = verify_phase_308_merkle_dag(
            output_dir=output_dir,
            parent_merkle_root=parent_root,
        )
        if is_valid:
            logger.info("Phase 308 Merkle DAG hash chain verified successfully!")
            print("PHASE 308 MERKLE DAG INTEGRITY: VERIFIED")
            return 0
        else:
            logger.error("Phase 308 Merkle DAG integrity verification failed!")
            print("PHASE 308 MERKLE DAG INTEGRITY: FAILED")
            return 1

    logger.info("Starting Phase 308 simulation runner...")
    logger.info(f"Target Output Directory: {output_dir}")
    logger.info(f"Parent Merkle Root Hash: {parent_root}")

    results = run_phase_308_simulation(output_dir=output_dir)

    logger.info(
        f"Phase 308 Simulation Completed: Status={results.get('status')}, "
        f"Kill-Switch State={results.get('kill_switch_state')}, "
        f"Merkle Root={results.get('merkle_root')}"
    )

    # Verification post-run
    is_valid = verify_phase_308_merkle_dag(
        output_dir=output_dir,
        parent_merkle_root=parent_root,
    )
    if is_valid:
        logger.info("Phase 308 Merkle DAG hash chain self-verification PASSED!")
        print(f"PHASE 308 MERKLE ROOT: {results.get('merkle_root')}")
        return 0
    else:
        logger.error("Phase 308 self-verification FAILED!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
