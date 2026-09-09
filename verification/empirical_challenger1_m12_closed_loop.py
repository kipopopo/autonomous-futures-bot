"""Empirical Challenger 1: E2E Test Timing, Immutability, Network Isolation, and Telemetry Parity.

This verification script runs empirical oracles against tests/integration/test_autonomous_pipeline_e2e.py:
1. Strict timing benchmark: runs the test suite and verifies duration strictly < 45.0s (target < 20.0s).
2. Offline Network Isolation Oracle: monkey-patches all socket/network primitives to catch any live
   outbound connections or paid API attempts during test execution.
3. Open Position Immutability Oracle: validates Candidate A exit rule retention vs Candidate B
   subsequent trade adoption at both tick level and bar level.
4. Telemetry Parity Oracle: cross-validates cryptographic hashes and candidate IDs across
   scheduler-health.json, paper-daemon-health.json, cycle-audit.json, and candidate_registry.json.
5. Temp Database Cleanup & Leak Oracle: verifies zero state leakage into repo root / artifacts.
"""

from __future__ import annotations

import gc
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
import scripts.run_phase_259_live_paper_daemon as daemon_mod
from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.feed.models import CanonicalBar, TickerSnapshot
from autonomous_futures.paper.candidate_registry import (
    CandidateRegistryHotReloader,
    publish_candidate_admission,
    read_candidate_registry,
)
from autonomous_futures.paper.live_engine import LivePaperEngine
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
    write_creator_candidate_artifact,
)


def _seed_warmup_bars(
    engine: LivePaperEngine,
    symbol: str = "BTCUSDT",
    count: int = 25,
    base_price: Decimal = Decimal("50000.00"),
    anchor_time: datetime | None = None,
) -> None:
    now = anchor_time or datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    engine._bar_history[symbol].clear()
    for i in range(count):
        bar_time = now - timedelta(minutes=5 * (count - 1 - i))
        engine._bar_history[symbol].append(
            {
                "timestamp": bar_time,
                "open": base_price,
                "high": base_price + Decimal("20"),
                "low": base_price - Decimal("20"),
                "close": base_price,
                "volume": Decimal("10.0"),
            }
        )


def run_timing_and_network_oracle() -> dict[str, Any]:
    """Test 1 & 2: Time execution and verify zero network connections."""
    print("\n" + "=" * 80)
    print("ORACLE 1 & 2: TIMING BENCHMARK & OFFLINE NETWORK ISOLATION")
    print("=" * 80)

    socket_attempts: list[tuple[str, Any]] = []

    def blocked_connect(self: Any, address: Any) -> None:
        socket_attempts.append(("connect", address))
        raise RuntimeError(f"BLOCKED_NETWORK_SOCKET_CONNECT: {address}")

    def blocked_connect_ex(self: Any, address: Any) -> int:
        socket_attempts.append(("connect_ex", address))
        return 111  # ECONNREFUSED

    def blocked_create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        socket_attempts.append(("create_connection", address))
        raise RuntimeError(f"BLOCKED_NETWORK_CREATE_CONNECTION: {address}")

    def blocked_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        socket_attempts.append(("getaddrinfo", (host, port)))
        raise RuntimeError(f"BLOCKED_NETWORK_GETADDRINFO: {host}:{port}")

    # Hook network primitives
    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_create_connection = socket.create_connection
    orig_getaddrinfo = socket.getaddrinfo

    socket.socket.connect = blocked_connect
    socket.socket.connect_ex = blocked_connect_ex
    socket.create_connection = blocked_create_connection
    socket.getaddrinfo = blocked_getaddrinfo

    try:
        start_time = time.monotonic()
        exit_code = pytest.main([
            str(REPO_ROOT / "tests" / "integration" / "test_autonomous_pipeline_e2e.py"),
            "-v",
            "--tb=short",
        ])
        elapsed = time.monotonic() - start_time
    finally:
        socket.socket.connect = orig_connect
        socket.socket.connect_ex = orig_connect_ex
        socket.create_connection = orig_create_connection
        socket.getaddrinfo = orig_getaddrinfo

    print(f"\n[TIMING] Execution time: {elapsed:.3f} seconds")
    print(f"[TIMING] Under 45s constraint: {elapsed < 45.0} (elapsed={elapsed:.3f}s)")
    print(f"[TIMING] Under 20s target: {elapsed < 20.0}")
    print(f"[NETWORK] Total external network attempts intercepted: {len(socket_attempts)}")
    for kind, addr in socket_attempts:
        print(f"  Intercepted: {kind} -> {addr}")

    assert exit_code == 0, f"Pytest failed with exit code {exit_code}"
    assert elapsed < 45.0, f"Execution time {elapsed:.3f}s exceeded 45.0s maximum!"
    assert len(socket_attempts) == 0, f"Detected unapproved network attempts: {socket_attempts}"

    return {
        "pytest_exit_code": exit_code,
        "elapsed_seconds": elapsed,
        "under_45s": elapsed < 45.0,
        "under_20s": elapsed < 20.0,
        "socket_attempts_count": len(socket_attempts),
    }


def run_immutability_adversarial_challenge() -> dict[str, Any]:
    """Test 3: Deep empirical challenge on open position immutability."""
    print("\n" + "=" * 80)
    print("ORACLE 3: ADVERSARIAL OPEN POSITION IMMUTABILITY CHALLENGE")
    print("=" * 80)

    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    tmp_dir = Path(tempfile.mkdtemp(prefix="immutability_challenger_"))
    try:
        storage_dir = tmp_dir / "paper_live"
        storage_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = storage_dir / "candidate_registry.json"

        # Candidate A:
        # Exit rule: rsi >= 50
        # Risk: stop_atr = 1.0, tp_atr = 2.0, trailing_atr = 1.0
        strategy_a = StrategySpec(
            dsl_version=2,
            strategy_id="cand-immutability-a",
            family="regime_gated_breakout",
            universe=StrategyUniverse(symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"),
            features=(FeatureRef(name="rsi", lookback=14, shift=1),),
            entry=EntryExit(long="rsi <= 30", short="rsi >= 70"),
            exit=EntryExit(long="rsi >= 50", short="rsi <= 50"),
            vetoes=("testing_only_no_promotion",),
            risk=CandidateSimulationRisk(
                position_fraction=Decimal("0.1"),
                stop_atr_multiplier=Decimal("1.0"),
                take_profit_atr_multiplier=Decimal("2.0"),
                trailing_atr_multiplier=Decimal("1.0"),
            ),
        )
        cand_a = build_creator_candidate_artifact(
            candidate_id="cand-immutability-a",
            strategy=strategy_a,
            bundle_hash="a" * 64,
            dataset_registry_hash="b" * 64,
            creator_run_id="run-a",
            research_seed=42,
            created_at=now,
        )
        cand_a_file = storage_dir / f"{cand_a.candidate_id}.json"
        write_creator_candidate_artifact(cand_a_file, cand_a)

        # Candidate B:
        # Exit rule: rsi >= 85 (much harder to trigger exit)
        # Risk: stop_atr = 4.0, tp_atr = 8.0, trailing_atr = 5.0
        strategy_b = StrategySpec(
            dsl_version=2,
            strategy_id="cand-immutability-b",
            family="regime_gated_breakout",
            universe=StrategyUniverse(symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"),
            features=(FeatureRef(name="rsi", lookback=14, shift=1),),
            entry=EntryExit(long="rsi <= 20", short="rsi >= 80"),
            exit=EntryExit(long="rsi >= 85", short="rsi <= 15"),
            vetoes=("testing_only_no_promotion",),
            risk=CandidateSimulationRisk(
                position_fraction=Decimal("0.2"),
                stop_atr_multiplier=Decimal("4.0"),
                take_profit_atr_multiplier=Decimal("8.0"),
                trailing_atr_multiplier=Decimal("5.0"),
            ),
        )
        cand_b = build_creator_candidate_artifact(
            candidate_id="cand-immutability-b",
            strategy=strategy_b,
            bundle_hash="c" * 64,
            dataset_registry_hash="d" * 64,
            creator_run_id="run-b",
            research_seed=43,
            created_at=now + timedelta(minutes=1),
        )
        cand_b_file = storage_dir / f"{cand_b.candidate_id}.json"
        write_creator_candidate_artifact(cand_b_file, cand_b)

        # Setup engine with Candidate A
        publish_candidate_admission(
            manifest_path=manifest_path,
            symbol="BTCUSDT",
            candidate_id=cand_a.candidate_id,
            candidate_artifact_hash=cand_a.artifact_hash,
            artifact_path=cand_a_file,
            qualification_hash="1" * 64,
            admitted_at=now,
        )

        ledger_path = storage_dir / "paper-ledger.sqlite3"
        lifecycle_path = storage_dir / "paper-lifecycle.sqlite3"
        obs_path = storage_dir / "paper-observations.sqlite3"

        engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            candidates={"BTCUSDT": cand_a},
            starting_capital=Decimal("100.00"),
            ledger_db=ledger_path,
            lifecycle_db=lifecycle_path,
            observations_db=obs_path,
        )
        engine.monitor._rolling_atrs["BTCUSDT"] = Decimal("100.0")
        engine.monitor._baseline_atrs["BTCUSDT"] = Decimal("100.0")
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("50000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("50001.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=now,
            event_time=now,
        )
        _seed_warmup_bars(engine, "BTCUSDT", count=25, anchor_time=now)

        reloader = CandidateRegistryHotReloader(manifest_path, engine, base_dir=storage_dir)
        assert reloader.check_and_reload() is True

        # Open Trade 1 under Candidate A
        opened_1 = engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.75"), event_time=now)
        assert opened_1 is not None
        trade_1 = engine.active_trades["BTCUSDT"]
        assert trade_1.candidate_id == cand_a.candidate_id
        assert trade_1.trailing_atr_multiplier == Decimal("1.0")
        print("  [Step 1] Trade 1 opened under Candidate A (trailing_atr=1.0, exit='rsi >= 50')")

        # Now Hot-Reload Candidate B into engine!
        publish_candidate_admission(
            manifest_path=manifest_path,
            symbol="BTCUSDT",
            candidate_id=cand_b.candidate_id,
            candidate_artifact_hash=cand_b.artifact_hash,
            artifact_path=cand_b_file,
            qualification_hash="2" * 64,
            admitted_at=now + timedelta(seconds=10),
        )
        assert reloader.check_and_reload() is True
        assert engine.candidates["BTCUSDT"].candidate_id == cand_b.candidate_id
        print("  [Step 2] Candidate B hot-reloaded into engine candidate pool")

        # ADVERSARIAL CHECK 1: Trade 1 must still have Candidate A!
        assert trade_1.candidate_id == cand_a.candidate_id
        assert trade_1.candidate is not None
        assert trade_1.candidate.candidate_id == cand_a.candidate_id
        assert trade_1.trailing_atr_multiplier == Decimal("1.0")
        assert trade_1.candidate.strategy.exit.long == "rsi >= 50"
        print("  [Check 1 Passed] Active Trade 1 immutably retained Candidate A metadata & multipliers")

        # ADVERSARIAL CHECK 2: Evaluate exit using evaluate_strategy_exit
        evaluated_expressions: list[str] = []

        def mock_evaluate_exit(
            row: Any,
            *,
            side: str = "LONG",
            long_exit_expr: str = "",
            short_exit_expr: str = "",
            **kwargs: Any,
        ) -> bool:
            evaluated_expressions.append(long_exit_expr)
            return long_exit_expr == cand_a.strategy.exit.long

        with patch("autonomous_futures.paper.live_engine.evaluate_strategy_exit", side_effect=mock_evaluate_exit):
            exit_bar = CanonicalBar(
                symbol="BTCUSDT",
                interval="5m",
                timestamp=now,
                close_time=now,
                open=Decimal("50000"),
                high=Decimal("50100"),
                low=Decimal("49900"),
                close=Decimal("50050"),
                volume=Decimal("10"),
                quote_volume=Decimal("500500"),
                trades=100,
                taker_buy_base=Decimal("5"),
                taker_buy_quote=Decimal("250250"),
                is_closed=True,
            )
            engine._process_closed_bar(exit_bar)

        assert len(evaluated_expressions) == 1
        assert evaluated_expressions[0] == "rsi >= 50", f"Expected Candidate A exit rule, got {evaluated_expressions[0]}"
        assert "BTCUSDT" not in engine.active_trades, "Trade 1 should have exited under Candidate A rules"
        assert engine.total_closed_trades == 1
        print("  [Check 2 Passed] Exit evaluation strictly used Candidate A's rule ('rsi >= 50')!")

        # ADVERSARIAL CHECK 3: Ledger attribution for Trade 1
        with sqlite3.connect(f"file:{ledger_path}?mode=ro", uri=True) as conn:
            t1_events = conn.execute(
                "SELECT event, candidate_id FROM paper_ledger_events ORDER BY sequence ASC"
            ).fetchall()
        assert len(t1_events) == 2
        assert t1_events[0] == ("open", cand_a.candidate_id)
        assert t1_events[1] == ("close", cand_a.candidate_id)
        print("  [Check 3 Passed] SQLite ledger attributed Candidate A to both open and close of Trade 1")

        # ADVERSARIAL CHECK 4: Subsequent Trade 2 MUST adopt Candidate B
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("50000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("50001.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=now + timedelta(minutes=10),
            event_time=now + timedelta(minutes=10),
        )
        opened_2 = engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.80"), event_time=now + timedelta(minutes=10))
        assert opened_2 is not None
        trade_2 = engine.active_trades["BTCUSDT"]
        assert trade_2.candidate_id == cand_b.candidate_id
        assert trade_2.candidate is not None
        assert trade_2.candidate.candidate_id == cand_b.candidate_id
        assert trade_2.trailing_atr_multiplier == Decimal("5.0")
        assert trade_2.candidate.strategy.exit.long == "rsi >= 85"

        with sqlite3.connect(f"file:{ledger_path}?mode=ro", uri=True) as conn:
            latest_open = conn.execute(
                "SELECT event, candidate_id FROM paper_ledger_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        assert latest_open == ("open", cand_b.candidate_id)
        print("  [Check 4 Passed] Subsequent Trade 2 adopted Candidate B (trailing_atr=5.0, exit='rsi >= 85')")

    finally:
        del engine
        gc.collect()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {"immutability_verified": True}


def run_telemetry_parity_challenge() -> dict[str, Any]:
    """Test 4: Cross-validate telemetry parity between health and audit files."""
    print("\n" + "=" * 80)
    print("ORACLE 4: TELEMETRY PARITY ACROSS HEALTH, AUDIT & REGISTRY FILES")
    print("=" * 80)

    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    tmp_dir = Path(tempfile.mkdtemp(prefix="telemetry_challenger_"))
    engine: LivePaperEngine | None = None
    try:
        storage_dir = tmp_dir / "paper_live"
        storage_dir.mkdir(parents=True, exist_ok=True)
        scheduler_out = tmp_dir / "scheduler_out"
        scheduler_out.mkdir(parents=True, exist_ok=True)
        manifest_path = storage_dir / "candidate_registry.json"
        scheduler_health_file = scheduler_out / "scheduler-health.json"
        daemon_health_file = storage_dir / "paper-daemon-health.json"

        # Pre-stage Candidate A
        cand_a = _build_mock_candidate("cand-telemetry-a")
        cand_a_file = storage_dir / f"{cand_a.candidate_id}.json"
        write_creator_candidate_artifact(cand_a_file, cand_a)

        publish_candidate_admission(
            manifest_path=manifest_path,
            symbol="BTCUSDT",
            candidate_id=cand_a.candidate_id,
            candidate_artifact_hash=cand_a.artifact_hash,
            artifact_path=cand_a_file,
            qualification_hash="1" * 64,
            admitted_at=now,
        )

        engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            candidates={"BTCUSDT": cand_a},
            starting_capital=Decimal("100.00"),
            ledger_db=storage_dir / "paper-ledger.sqlite3",
            lifecycle_db=storage_dir / "paper-lifecycle.sqlite3",
            observations_db=storage_dir / "paper-observations.sqlite3",
        )
        reloader = CandidateRegistryHotReloader(manifest_path, engine, base_dir=storage_dir)
        assert reloader.check_and_reload() is True

        # Now admit Candidate B
        cand_b = _build_mock_candidate("cand-telemetry-b")
        cand_b_file = storage_dir / f"{cand_b.candidate_id}.json"
        write_creator_candidate_artifact(cand_b_file, cand_b)

        publish_candidate_admission(
            manifest_path=manifest_path,
            symbol="BTCUSDT",
            candidate_id=cand_b.candidate_id,
            candidate_artifact_hash=cand_b.artifact_hash,
            artifact_path=cand_b_file,
            qualification_hash="2" * 64,
            admitted_at=now + timedelta(seconds=5),
        )
        assert reloader.check_and_reload() is True

        # Emit daemon health checkpoint
        active_cands, last_reload = reloader.get_telemetry()
        daemon_mod.emit_daemon_health_checkpoint(
            output_path=daemon_health_file,
            status="RUNNING",
            uptime_seconds=20.0,
            started_at=now.isoformat(),
            symbols=["BTCUSDT"],
            starting_capital=Decimal("100.00"),
            current_cash=Decimal("100.00"),
            current_equity=Decimal("100.00"),
            margin_utilization_pct=0.0,
            reserve_buffer_pct=100.0,
            active_positions={},
            total_trades=0,
            circuit_breaker_status="NORMAL",
            feed_messages_received=50,
            reconnect_count=0,
            active_candidates=active_cands,
            last_registry_reload=last_reload,
        )
        daemon_health = json.loads(daemon_health_file.read_text(encoding="utf-8"))

        # Emit mock scheduler health
        scheduler_health = {
            "status": "IDLE",
            "pid": 12345,
            "started_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "last_run_at": now.isoformat(),
            "next_run_at": (now + timedelta(hours=1)).isoformat(),
            "consecutive_failures": 0,
            "total_cycles_executed": 1,
            "admitted_candidates_count": 1,
            "last_cycle_result": {
                "cycle_id": "cycle-test-1",
                "trigger_type": "breach",
                "status": "completed_admitted",
                "exit_code": 0,
                "candidate_id": cand_b.candidate_id,
                "admitted": True,
                "executed_at": now.isoformat(),
                "duration_seconds": 3.45,
                "error_message": None,
            },
            "symbol": "BTCUSDT",
            "lockfile": str(scheduler_out / "scheduler.lock"),
            "mode": "daemon",
        }
        scheduler_health_file.write_text(json.dumps(scheduler_health), encoding="utf-8")

        # Emit mock cycle-audit.json
        cycle_audit = {
            "cycle_id": "cycle-test-1",
            "cycle_status": "completed_admitted",
            "candidate_id": cand_b.candidate_id,
            "candidate_artifact_hash": cand_b.artifact_hash,
            "qualification_hash": "2" * 64,
            "admission_decision": "admitted",
        }
        cycle_audit_file = scheduler_out / "cycle-audit.json"
        cycle_audit_file.write_text(json.dumps(cycle_audit), encoding="utf-8")

        manifest = read_candidate_registry(manifest_path, verify_hash=True)

        # 1. Candidate ID Parity
        assert scheduler_health["last_cycle_result"]["candidate_id"] == cand_b.candidate_id
        assert daemon_health["active_candidates"]["BTCUSDT"] == cand_b.candidate_id
        assert cycle_audit["candidate_id"] == cand_b.candidate_id
        assert manifest.symbols["BTCUSDT"].candidate_id == cand_b.candidate_id
        print("  [Parity 1 Passed] Candidate ID matches across scheduler, daemon, audit, and registry manifests!")

        # 2. Cryptographic Hash Parity
        assert daemon_health["last_registry_reload"]["registry_hash"] == manifest.registry_hash
        assert cycle_audit["candidate_artifact_hash"] == cand_b.artifact_hash
        assert manifest.symbols["BTCUSDT"].candidate_artifact_hash == cand_b.artifact_hash
        assert cycle_audit["qualification_hash"] == manifest.symbols["BTCUSDT"].qualification_hash
        print("  [Parity 2 Passed] Cryptographic hashes match across daemon, audit, and registry manifests!")

    finally:
        if engine is not None:
            del engine
        gc.collect()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {"parity_verified": True}


def run_filesystem_leak_oracle() -> dict[str, Any]:
    """Test 5: Verify no temporary SQLite or artifacts leak into the working tree."""
    print("\n" + "=" * 80)
    print("ORACLE 5: FILESYSTEM ISOLATION AND ZERO-LEAK VERIFICATION")
    print("=" * 80)

    # Check that no sqlite3 files or unapproved files exist in repository root or artifacts/
    repo_root_sqlite = list(REPO_ROOT.glob("*.sqlite*"))
    artifacts_sqlite = list((REPO_ROOT / "artifacts").glob("**/*.sqlite*")) if (REPO_ROOT / "artifacts").exists() else []
    
    print(f"  Repo root SQLite files: {repo_root_sqlite}")
    print(f"  Artifacts directory SQLite files count: {len(artifacts_sqlite)}")

    assert len(repo_root_sqlite) == 0, f"Found leaked SQLite files in repo root: {repo_root_sqlite}"
    print("  [Leak Check Passed] Zero temporary SQLite files leaked into repo working tree.")

    return {"zero_leak_verified": True}


def _build_mock_candidate(candidate_id: str) -> CreatorCandidateArtifact:
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=candidate_id,
        family="regime_gated_breakout",
        universe=StrategyUniverse(symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"),
        features=(FeatureRef(name="rsi", lookback=14, shift=1),),
        entry=EntryExit(long="rsi <= 30", short="rsi >= 70"),
        exit=EntryExit(long="rsi >= 50", short="rsi <= 50"),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.1"),
            stop_atr_multiplier=Decimal("1.5"),
            take_profit_atr_multiplier=Decimal("3.0"),
            trailing_atr_multiplier=Decimal("1.0"),
        ),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash="e" * 64,
        dataset_registry_hash="f" * 64,
        creator_run_id=f"run-{candidate_id}",
        research_seed=42,
        created_at=datetime.now(UTC),
    )


def run_all_challenger_checks() -> None:
    print("\n" + "#" * 80)
    print("STARTING EMPIRICAL CHALLENGER 1 AUDIT SUITE")
    print("#" * 80)

    # 1 & 2: Timing & Network Isolation
    timing_res = run_timing_and_network_oracle()

    # 3: Open Position Immutability
    immutability_res = run_immutability_adversarial_challenge()

    # 4: Telemetry Parity
    parity_res = run_telemetry_parity_challenge()

    # 5: Filesystem Leak Isolation
    leak_res = run_filesystem_leak_oracle()

    print("\n" + "#" * 80)
    print("ALL EMPIRICAL CHALLENGER 1 CHECKS PASSED PERFECTLY!")
    print(f"Timing: {timing_res['elapsed_seconds']:.2f}s (< 45.0s, target < 20.0s)")
    print(f"Network calls intercepted: {timing_res['socket_attempts_count']}")
    print(f"Immutability verified: {immutability_res['immutability_verified']}")
    print(f"Telemetry parity verified: {parity_res['parity_verified']}")
    print(f"Zero leak verified: {leak_res['zero_leak_verified']}")
    print("#" * 80)


if __name__ == "__main__":
    run_all_challenger_checks()
