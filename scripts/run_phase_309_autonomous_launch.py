"""CLI runner for Phase 309: Autonomous Live Production Launch Verification.

Validates upstream Phase 308 Merkle Root, zero balance drift, and Phase 309 artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

# Add project root and src to path
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.production.self_driving import (  # noqa: E402
    UPSTREAM_PHASE_308_MERKLE_ROOT,
)
from scripts.run_phase_309_production_launch import (  # noqa: E402
    run_phase_309_simulation,
    verify_phase_309_artifacts,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_phase_309_autonomous_launch")

EXPECTED_UPSTREAM_MERKLE_ROOT = "65c2e7d2b3dc5d0f63773ef531c700a0fa2f6e73bdc094c7fad1105fc675e31e"


def verify_phase_309_autonomous_launch(target_dir: Path) -> bool:
    """Verifies Phase 309 autonomous launch artifacts, upstream Merkle root, and solvency drift."""
    logger.info("Verifying Phase 309 autonomous launch artifacts in %s...", target_dir)

    # 1. First run the standard artifact verification
    if not verify_phase_309_artifacts(target_dir):
        logger.error("Phase 309 artifact verification failed.")
        return False

    summary_file = target_dir / "production-summary.json"
    summary_data: dict[str, Any] = json.loads(summary_file.read_text(encoding="utf-8"))

    # 2. Explicitly verify upstream Phase 308 Merkle Root
    upstream_hash = summary_data.get("upstream_hash")
    if (
        upstream_hash != EXPECTED_UPSTREAM_MERKLE_ROOT
        or upstream_hash != UPSTREAM_PHASE_308_MERKLE_ROOT
    ):
        logger.error(
            "Upstream Phase 308 Merkle root mismatch: expected %s, found %s",
            EXPECTED_UPSTREAM_MERKLE_ROOT,
            upstream_hash,
        )
        return False

    # 3. Verify zero balance drift (|drift| < 1e-15 USDT)
    solvency = summary_data.get("solvency", {})
    drift = Decimal(str(solvency.get("drift", "0.0")))
    if abs(drift) >= Decimal("1e-15"):
        logger.error("Solvency zero-drift invariant breached: drift %s", drift)
        return False

    # 4. Verify artifact files exist and match hashes
    artifact_hashes = summary_data.get("artifact_hashes", {})
    expected_files = {
        "sqlite3": target_dir / "canary-production-telemetry.sqlite3",
        "events_jsonl": target_dir / "canary-production-events.jsonl",
        "report_json": target_dir / "canary-production-report.json",
        "execution_json": target_dir / "canary-production-execution.json",
    }

    for key, fpath in expected_files.items():
        if not fpath.is_file():
            logger.error("Missing expected artifact file: %s", fpath)
            return False
        computed_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
        if computed_hash != artifact_hashes.get(key):
            logger.error(
                "Hash mismatch for %s: computed %s, recorded %s",
                key,
                computed_hash,
                artifact_hashes.get(key),
            )
            return False

    logger.info("All Phase 309 autonomous launch verification checks passed successfully!")
    print("PHASE 309 AUTONOMOUS LAUNCH: VERIFIED")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 309 Autonomous Launch Verification Runner")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/research/phase309"),
        help="Target artifacts directory (default: artifacts/research/phase309)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing Phase 309 artifacts without running simulation",
    )
    args = parser.parse_args()

    if args.verify_only:
        logger.info("Executing Phase 309 autonomous launch verification-only check...")
        if not verify_phase_309_autonomous_launch(args.output_dir):
            sys.exit(1)
        sys.exit(0)

    # Standard execution: run simulation if artifacts need to be produced, then verify
    logger.info("Executing Phase 309 simulation and full autonomous launch verification...")
    run_phase_309_simulation(args.output_dir)
    if not verify_phase_309_autonomous_launch(args.output_dir):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
