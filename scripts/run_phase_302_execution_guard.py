"""Phase 302: Real-Time Toxic Flow Defense, Adverse Selection Guard & Dynamic

Microstructure Slippage Attribution Engine.

Runner script executing 4 deterministic simulation tracks:
1. Track 1: Toxicity & Adverse Selection Guard Drill (VPIN, Avellaneda-Stoikov, Toxic Quote Pull)
2. Track 2: Causal Slippage Decomposition Drill (Almgren-Chriss 4-component attribution)
3. Track 3: Execution Risk Coordination & Circuit Breakers Drill
4. Track 4: Full Longevity, Double-Entry Zero-Drift & Merkle DAG Chaining Drill

Usage:
    uv run python scripts/run_phase_302_execution_guard.py [--track all|1|2|3|4]
    uv run python scripts/run_phase_302_execution_guard.py --verify-only
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

from autonomous_futures.feed.execution_guard import (  # noqa: E402
    DEFAULT_PHASE302_OUTPUT_DIR,
    UPSTREAM_PHASE301_ROOT_HASH,
    CanaryExecutionGuardRunner,
    verify_phase_302_dag,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_phase_302_execution_guard")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase 302: Toxic Flow Defense & Slippage Attribution Runner"
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
        default=DEFAULT_PHASE302_OUTPUT_DIR,
        help="Directory to persist research artifacts and telemetry",
    )
    parser.add_argument(
        "--upstream-dir",
        type=Path,
        default=_REPO_ROOT / "artifacts" / "research" / "phase301",
        help="Upstream Phase 301 artifact directory",
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
        logger.info("Executing Phase 302 verification-only check...")
        summary_path = args.output_dir / "execution-guard-summary.json"
        if not summary_path.is_file():
            logger.error("Phase 302 summary artifact not found at %s", summary_path)
            print(f"FAILED: Summary not found at {summary_path}", file=sys.stderr)
            return 1

        upstream_hash = UPSTREAM_PHASE301_ROOT_HASH
        phase301_summary = args.upstream_dir / "bracket-position-summary.json"
        if phase301_summary.is_file():
            upstream_data = json.loads(phase301_summary.read_text(encoding="utf-8"))
            upstream_hash = upstream_data.get("merkle_root", UPSTREAM_PHASE301_ROOT_HASH)

        verified, reason, hashes = verify_phase_302_dag(args.output_dir, upstream_hash)
        if not verified:
            logger.error("Phase 302 DAG verification failed: %s", reason)
            print(f"FAILED: {reason}", file=sys.stderr)
            return 1

        print("PHASE 302 MERKLE DAG INTEGRITY: VERIFIED")
        logger.info("Phase 302 Merkle DAG hash chain verified successfully!")
        return 0

    logger.info("Initializing Phase 302 Execution Guard Runner...")
    upstream_hash = UPSTREAM_PHASE301_ROOT_HASH
    phase301_summary = args.upstream_dir / "bracket-position-summary.json"
    if phase301_summary.is_file():
        upstream_data = json.loads(phase301_summary.read_text(encoding="utf-8"))
        upstream_hash = upstream_data.get("merkle_root", UPSTREAM_PHASE301_ROOT_HASH)
        logger.info("Linked to parent Phase 301 Merkle root: %s", upstream_hash)

    runner = CanaryExecutionGuardRunner(
        output_dir=args.output_dir,
        upstream_hash=upstream_hash,
    )
    results = runner.run_all_tracks()
    logger.info(
        "Phase 302 completed successfully. Status=%s MerkleRoot=%s",
        results["status"],
        results["merkle_root"],
    )

    verified, reason, hashes = verify_phase_302_dag(args.output_dir, upstream_hash)
    if not verified:
        logger.error("Post-run verification failed: %s", reason)
        print(f"FAILED: {reason}", file=sys.stderr)
        return 1

    print("PHASE 302 EXECUTION & MERKLE DAG: VERIFIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
