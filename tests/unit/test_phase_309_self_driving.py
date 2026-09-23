"""Unit tests for Phase 309: Autonomous Live Production Launch.

Tests the Micro-Capital Self-Driving Trading Engine.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from autonomous_futures.production.self_driving import (
    UPSTREAM_PHASE_308_MERKLE_ROOT,
    MicroCapitalConfig,
    OrderSide,
    OrderStatus,
    SelfDrivingState,
    SelfDrivingTradingEngine,
    build_default_self_driving_engine,
)
from autonomous_futures.safety.kill_switch import (
    CentralizedSolvencyLedger,
    HardwareOSKillSwitchEngine,
    MultiSigGovernanceEngine,
    SignerIdentity,
)


def test_pre_flight_check_and_initial_state(tmp_path: Path) -> None:
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    assert engine.state == SelfDrivingState.COLD_STANDBY

    ok = engine.run_pre_flight_check()
    assert ok
    assert engine.state == SelfDrivingState.MICRO_CAPITAL_ACTIVE


def test_kill_switch_fail_closed_prevents_pre_flight(tmp_path: Path) -> None:
    signers = [
        SignerIdentity("signer-1", "pub1", "ROLE_CRO"),
        SignerIdentity("signer-2", "pub2", "ROLE_DEV"),
    ]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=2)
    ledger = CentralizedSolvencyLedger(starting_equity=100.0)
    kill_switch = HardwareOSKillSwitchEngine(
        governance=gov,
        solvency_ledger=ledger,
    )
    # Put kill-switch into Lockout state
    kill_switch.trigger_level_2_lockout("Test lockout", "TEST_TRIGGER")

    engine = SelfDrivingTradingEngine(
        config=MicroCapitalConfig(),
        solvency_ledger=ledger,
        kill_switch=kill_switch,
        output_dir=tmp_path,
    )
    ok = engine.run_pre_flight_check()
    assert not ok
    assert engine.state == SelfDrivingState.KILL_SWITCH_HALTED


def test_micro_capital_sizing_and_zero_drift(tmp_path: Path) -> None:
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    engine.run_pre_flight_check()

    # Process buy order for BTCUSDT
    order = engine.process_microstructure_tick(
        symbol="BTCUSDT",
        price=Decimal("95000.00"),
        hawkes_rho=0.40,
        heartbeat_latency_ms=20.0,
        ensemble_signal="LONG",
        signal_confidence=0.85,
    )
    assert order is not None
    assert order.status == OrderStatus.FILLED
    assert order.side == OrderSide.BUY
    assert order.notional_usdt <= Decimal("5.75")

    # Invariant check
    snap = engine.ledger.get_snapshot()
    assert snap.zero_balance_drift
    assert abs(snap.drift) < 1e-15


def test_hawkes_and_heartbeat_interlocks(tmp_path: Path) -> None:
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    engine.run_pre_flight_check()

    # Hawkes runaway breach (rho >= 1.0)
    ord1 = engine.process_microstructure_tick(
        symbol="ETHUSDT",
        price=Decimal("2750.00"),
        hawkes_rho=1.10,
        heartbeat_latency_ms=30.0,
        ensemble_signal="LONG",
        signal_confidence=0.90,
    )
    assert ord1 is None
    assert engine.state == SelfDrivingState.HAWKES_THROTTLED

    # Stale heartbeat breach (> 500 ms)
    ord2 = engine.process_microstructure_tick(
        symbol="SOLUSDT",
        price=Decimal("180.00"),
        hawkes_rho=0.50,
        heartbeat_latency_ms=550.0,
        ensemble_signal="LONG",
        signal_confidence=0.80,
    )
    assert ord2 is None
    assert engine.interlock_blocks_count >= 2


def test_aggregate_exposure_and_loss_ceiling_containment(tmp_path: Path) -> None:
    # Use small caps to test limits quickly
    cfg = MicroCapitalConfig(
        max_aggregate_exposure_usdt=Decimal("12.00"),
        intra_day_loss_ceiling_usdt=Decimal("1.00"),
    )
    signers = [SignerIdentity("s1", "p1", "CRO"), SignerIdentity("s2", "p2", "DEV")]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=2)
    ledger = CentralizedSolvencyLedger(starting_equity=100.0)
    ks = HardwareOSKillSwitchEngine(governance=gov, solvency_ledger=ledger)
    engine = SelfDrivingTradingEngine(
        config=cfg,
        solvency_ledger=ledger,
        kill_switch=ks,
        output_dir=tmp_path,
    )
    engine.run_pre_flight_check()

    # Fill 1 (~5 USDT)
    o1 = engine.process_microstructure_tick("BTCUSDT", Decimal("95000.0"), 0.3, 10.0, "LONG", 0.9)
    assert o1 is not None

    # Fill 2 (~5 USDT, reaching ~10 USDT cap)
    o2 = engine.process_microstructure_tick("ETHUSDT", Decimal("2750.0"), 0.3, 10.0, "LONG", 0.9)
    assert o2 is not None

    # Order 3 should be blocked by aggregate exposure cap (10.00 USDT)
    o3 = engine.process_microstructure_tick("SOLUSDT", Decimal("180.0"), 0.3, 10.0, "LONG", 0.9)
    assert o3 is None


def test_phase_309_artifacts_and_merkle_dag(tmp_path: Path) -> None:
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    engine.run_pre_flight_check()

    engine.process_microstructure_tick("BTCUSDT", Decimal("95000.0"), 0.4, 25.0, "LONG", 0.85)
    engine.process_microstructure_tick("ETHUSDT", Decimal("2750.0"), 0.5, 25.0, "SHORT", 0.85)

    summary = engine.export_artifacts()

    assert summary["verified"]
    assert summary["phase"] == "phase_309"
    assert summary["status"] == "PRODUCTION_LAUNCH_VERIFIED"
    assert summary["upstream_hash"] == UPSTREAM_PHASE_308_MERKLE_ROOT
    assert summary["solvency"]["zero_balance_drift"]
    assert abs(summary["solvency"]["drift"]) < 1e-15
    assert (tmp_path / "canary-production-telemetry.sqlite3").is_file()
    assert (tmp_path / "canary-production-events.jsonl").is_file()
    assert (tmp_path / "canary-production-report.json").is_file()
    assert (tmp_path / "production-summary.json").is_file()
    assert (tmp_path / "canary-production-execution.json").is_file()
