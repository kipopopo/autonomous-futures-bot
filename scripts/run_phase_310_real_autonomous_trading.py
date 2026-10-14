"""Phase 310 research artifact runner and integrity verifier.

Binds to upstream Phase 309 parent root:
5e3435be2f701021263dbace99d64b2180e03630f10b5356c4aabe96f846c844

This historical artifact bundle is not strategy qualification and does not attest exchange
fills. The synthetic batch runner has been retired.

Verifies this historical Phase 310 research artifact bundle when requested:
1. canary-production-telemetry.sqlite3
2. canary-production-events.jsonl
3. canary-production-report.json
4. canary-production-execution.json
5. production-summary.json

Normal mode starts the legacy continuous service loop. Verification mode checks artifact
integrity only and does not grant execution authority.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import signal
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

# Ensure project root and src are on path
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.execution.self_driving import UPSTREAM_PHASE_309_MERKLE_ROOT  # noqa: E402
from autonomous_futures.feed.kline_sequencer import ACTIVE_PAIRS  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_phase_310_real_autonomous_trading")

UPSTREAM_PHASE_309_PARENT_ROOT = "5e3435be2f701021263dbace99d64b2180e03630f10b5356c4aabe96f846c844"


def verify_phase_310_artifacts(target_dir: Path) -> bool:
    """Verifies artifact integrity and ledger arithmetic, not execution authenticity."""
    summary_file = target_dir / "production-summary.json"
    report_file = target_dir / "canary-production-report.json"
    sqlite_file = target_dir / "canary-production-telemetry.sqlite3"
    events_file = target_dir / "canary-production-events.jsonl"
    execution_file = target_dir / "canary-production-execution.json"

    for f in (summary_file, report_file, sqlite_file, events_file, execution_file):
        if not f.is_file():
            logger.error("Missing required Phase 310 artifact: %s", f)
            return False

    summary_data: dict[str, Any] = json.loads(summary_file.read_text(encoding="utf-8"))
    artifact_hashes = summary_data.get("artifact_hashes", {})

    # 1. Verify individual file hashes
    sq_hash = hashlib.sha256(sqlite_file.read_bytes()).hexdigest()
    ev_hash = hashlib.sha256(events_file.read_bytes()).hexdigest()
    rep_hash = hashlib.sha256(report_file.read_bytes()).hexdigest()
    ex_hash = hashlib.sha256(execution_file.read_bytes()).hexdigest()

    if sq_hash != artifact_hashes.get("sqlite3"):
        logger.error("SQLite3 hash mismatch: %s != %s", sq_hash, artifact_hashes.get("sqlite3"))
        return False
    if ev_hash != artifact_hashes.get("events_jsonl"):
        logger.error(
            "Events JSONL hash mismatch: %s != %s", ev_hash, artifact_hashes.get("events_jsonl")
        )
        return False
    if rep_hash != artifact_hashes.get("report_json"):
        logger.error(
            "Report JSON hash mismatch: %s != %s", rep_hash, artifact_hashes.get("report_json")
        )
        return False
    if ex_hash != artifact_hashes.get("execution_json"):
        logger.error(
            "Execution JSON hash mismatch: %s != %s", ex_hash, artifact_hashes.get("execution_json")
        )
        return False

    # 2. Verify upstream hash chain binding
    upstream_hash = summary_data.get("upstream_hash")
    if (
        upstream_hash != UPSTREAM_PHASE_309_PARENT_ROOT
        or upstream_hash != UPSTREAM_PHASE_309_MERKLE_ROOT
    ):
        logger.error(
            "Upstream Phase 309 hash mismatch: expected %s, found %s",
            UPSTREAM_PHASE_309_PARENT_ROOT,
            upstream_hash,
        )
        return False

    # 3. Verify double-entry zero-drift balance invariant (|drift| < 10^-15 USDT)
    solvency = summary_data.get("solvency", {})
    drift = Decimal(str(solvency.get("drift", "0.0")))
    if abs(drift) >= Decimal("1e-15"):
        logger.error("Double-entry zero-drift balance invariant breached: drift %s", drift)
        return False

    # 4. Verify Phase 310 Merkle root derivation
    drift_str = str(solvency.get("drift", "0.0"))
    combined_payload = (
        f"phase_310:{upstream_hash}:{sq_hash}:{ev_hash}:{rep_hash}:{ex_hash}:{drift_str}"
    )
    expected_phase_hash = hashlib.sha256(combined_payload.encode()).hexdigest()
    expected_merkle_root = hashlib.sha256(
        f"{upstream_hash}:{expected_phase_hash}".encode()
    ).hexdigest()

    if summary_data.get("merkle_root") != expected_merkle_root:
        logger.error(
            "Merkle root mismatch: %s != %s",
            summary_data.get("merkle_root"),
            expected_merkle_root,
        )
        return False

    # 5. Verify SQLite telemetry tables contain persisted activity (> 0 rows).
    # Non-empty internal simulation records do not prove exchange execution.
    conn = sqlite3.connect(sqlite_file)
    cur = conn.cursor()
    for table in ("orders", "trade_autopsies", "candidate_health", "solvency_snapshots"):
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur.fetchone()[0]
        if count == 0:
            logger.error("SQLite table %s is empty (0 rows)", table)
            conn.close()
            return False
    conn.close()

    logger.info("Phase 310 cryptographic Merkle DAG chain verified successfully!")
    print("PHASE 310 ARTIFACT INTEGRITY: VERIFIED")
    print("PHASE 310 EXECUTION AUTHENTICITY: NOT VERIFIED")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 310 Research Artifact Runner")
    parser.add_argument(
        "--output-dir",
        "--storage-dir",
        dest="output_dir",
        type=Path,
        default=Path("artifacts/research/phase310"),
        help="Target artifacts directory (default: artifacts/research/phase310)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify artifact integrity only; this does not attest live exchange execution",
    )
    parser.add_argument(
        "--starting-capital",
        type=Decimal,
        default=Decimal("100.00"),
        help="Starting equity in USDT",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=",".join(ACTIVE_PAIRS),
        help="Comma-separated trading symbols",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=15.0,
        help="Polling interval in seconds for continuous trading loop (default: 15.0)",
    )
    args = parser.parse_args()

    if args.verify_only:
        logger.info("Executing Phase 310 verification-only mode on %s...", args.output_dir)
        if not verify_phase_310_artifacts(args.output_dir):
            sys.exit(1)
        sys.exit(0)

    # Start 24/7 continuous trading daemon
    from autonomous_futures.execution.continuous_trader import ContinuousSelfDrivingTrader

    symbols_list = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    scalper_symbols = [s for s in symbols_list if s != "BTCUSDT"] or ["SOLUSDT", "ETHUSDT"]

    logger.info(
        "Starting 24/7 Continuous Self-Driving Trader on %s (macro filter: BTCUSDT)...",
        scalper_symbols,
    )
    trader = ContinuousSelfDrivingTrader(
        storage_dir=args.output_dir,
        symbols=scalper_symbols,
        starting_capital_usdt=args.starting_capital,
        poll_interval_seconds=args.poll_interval,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, trader.stop)

    try:
        loop.run_until_complete(trader.start())
    except KeyboardInterrupt:
        logger.info("Interrupted by user. Shutting down cleanly...")
        trader.stop()
    finally:
        loop.close()


if __name__ == "__main__":
    main()
