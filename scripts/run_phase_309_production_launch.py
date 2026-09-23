"""CLI runner for Phase 309: Autonomous Live Production Launch.

Micro-Capital Self-Driving Trading Engine.
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
    build_default_self_driving_engine,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_phase_309_production_launch")


def verify_phase_309_artifacts(target_dir: Path) -> bool:
    """Verifies SHA-256 hashes, upstream hash chain, and zero-drift invariant for Phase 309."""
    summary_file = target_dir / "production-summary.json"
    report_file = target_dir / "canary-production-report.json"
    sqlite_file = target_dir / "canary-production-telemetry.sqlite3"
    events_file = target_dir / "canary-production-events.jsonl"
    execution_file = target_dir / "canary-production-execution.json"

    for f in (summary_file, report_file, sqlite_file, events_file, execution_file):
        if not f.is_file():
            logger.error("Missing required artifact: %s", f)
            return False

    summary_data = json.loads(summary_file.read_text(encoding="utf-8"))
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
            "Events JSONL hash mismatch: %s != %s",
            ev_hash,
            artifact_hashes.get("events_jsonl"),
        )
        return False
    if rep_hash != artifact_hashes.get("report_json"):
        logger.error(
            "Report JSON hash mismatch: %s != %s",
            rep_hash,
            artifact_hashes.get("report_json"),
        )
        return False
    if ex_hash != artifact_hashes.get("execution_json"):
        logger.error(
            "Execution JSON hash mismatch: %s != %s",
            ex_hash,
            artifact_hashes.get("execution_json"),
        )
        return False

    # 2. Verify upstream hash chain
    upstream_hash = summary_data.get("upstream_hash")
    if upstream_hash != UPSTREAM_PHASE_308_MERKLE_ROOT:
        logger.error(
            "Upstream hash mismatch: %s != %s",
            upstream_hash,
            UPSTREAM_PHASE_308_MERKLE_ROOT,
        )
        return False

    # 3. Verify double-entry balance invariant
    solvency = summary_data.get("solvency", {})
    drift = Decimal(str(solvency.get("drift", "0.0")))
    if abs(drift) >= Decimal("1e-15"):
        logger.error("Double-entry zero-drift invariant breached: drift %s", drift)
        return False

    # 4. Verify Merkle root
    combined_payload = f"phase_309:{upstream_hash}:{sq_hash}:{ev_hash}:{rep_hash}:{ex_hash}:{drift}"
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

    logger.info("Phase 309 Merkle DAG hash chain verified successfully!")
    print("PHASE 309 MERKLE DAG INTEGRITY: VERIFIED")
    return True


def run_phase_309_simulation(output_dir: Path) -> dict[str, Any]:
    """Executes the autonomous micro-capital self-driving trading simulation."""
    logger.info("Starting Phase 309 Autonomous Production Launch Simulation...")
    engine, _gov = build_default_self_driving_engine(output_dir=output_dir)

    # Step 1: Pre-flight safety check
    pre_flight_ok = engine.run_pre_flight_check()
    assert pre_flight_ok, "Pre-flight checks must pass"

    now = 1790160000000

    # Step 2: Realistic market ticks and ensemble trading decisions
    # Tick 1: BTCUSDT nominal tick, ensemble LONG
    ord_btc = engine.process_microstructure_tick(
        symbol="BTCUSDT",
        price=Decimal("95000.00"),
        hawkes_rho=0.45,
        heartbeat_latency_ms=25.0,
        ensemble_signal="LONG",
        signal_confidence=0.88,
        now_ms=now,
    )
    assert ord_btc is not None
    assert ord_btc.status.value == "FILLED"
    assert ord_btc.notional_usdt <= Decimal("5.75")

    # Tick 2: ETHUSDT nominal tick, ensemble SHORT
    ord_eth = engine.process_microstructure_tick(
        symbol="ETHUSDT",
        price=Decimal("2750.00"),
        hawkes_rho=0.52,
        heartbeat_latency_ms=30.0,
        ensemble_signal="SHORT",
        signal_confidence=0.82,
        now_ms=now + 500,
    )
    assert ord_eth is not None
    assert ord_eth.status.value == "FILLED"

    # Tick 3: SOLUSDT nominal tick, ensemble LONG
    ord_sol = engine.process_microstructure_tick(
        symbol="SOLUSDT",
        price=Decimal("185.00"),
        hawkes_rho=0.61,
        heartbeat_latency_ms=28.0,
        ensemble_signal="LONG",
        signal_confidence=0.79,
        now_ms=now + 1000,
    )
    assert ord_sol is not None
    assert ord_sol.status.value == "FILLED"

    # Tick 4: Hawkes Supercritical Runaway Shock on ETHUSDT (rho = 1.15)
    ord_hawkes_blocked = engine.process_microstructure_tick(
        symbol="ETHUSDT",
        price=Decimal("2740.00"),
        hawkes_rho=1.15,
        heartbeat_latency_ms=35.0,
        ensemble_signal="SHORT",
        signal_confidence=0.90,
        now_ms=now + 1500,
    )
    assert ord_hawkes_blocked is None, "Hawkes runaway must block new orders"

    # Tick 5: Stale Gateway Heartbeat (> 500 ms) on BTCUSDT
    ord_latency_blocked = engine.process_microstructure_tick(
        symbol="BTCUSDT",
        price=Decimal("95200.00"),
        hawkes_rho=0.50,
        heartbeat_latency_ms=620.0,
        ensemble_signal="LONG",
        signal_confidence=0.85,
        now_ms=now + 2000,
    )
    assert ord_latency_blocked is None, "Stale heartbeat must block new orders"

    # Tick 6: Partial profit taking on BTCUSDT (Sell to close portion)
    ord_btc_close = engine.process_microstructure_tick(
        symbol="BTCUSDT",
        price=Decimal("95500.00"),
        hawkes_rho=0.48,
        heartbeat_latency_ms=32.0,
        ensemble_signal="SHORT",
        signal_confidence=0.84,
        now_ms=now + 2500,
    )
    assert ord_btc_close is not None

    # Step 3: Verify double-entry ledger state
    snap = engine.ledger.get_snapshot()
    assert snap.zero_balance_drift, f"Balance drift {snap.drift} violates zero-drift invariant"
    assert abs(snap.drift) < 1e-15
    assert snap.unencumbered_cash_verified

    # Step 4: Export artifacts and generate Merkle DAG
    summary = engine.export_artifacts()
    logger.info("Phase 309 simulation successfully concluded!")
    logger.info("Merkle Root: %s", summary["merkle_root"])
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 309 Production Launch Runner")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/research/phase309"),
        help="Target artifacts directory",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing Phase 309 artifacts without re-running simulation",
    )
    args = parser.parse_args()

    if args.verify_only:
        logger.info("Executing Phase 309 verification-only check...")
        if not verify_phase_309_artifacts(args.output_dir):
            sys.exit(1)
        sys.exit(0)

    run_phase_309_simulation(args.output_dir)
    if not verify_phase_309_artifacts(args.output_dir):
        sys.exit(1)


if __name__ == "__main__":
    main()
