"""Unit tests for Phase 303: Autonomous End-to-End Closed-Loop Paper Trading Orchestrator

& Shadow Execution Engine.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.feed.orchestrator import (
    AutonomousExecutionOrchestrator,
    CentralizedSolvencyLedger,
    CycleStatus,
    PipelineStage,
    ShadowLongevitySimulator,
    SignalSide,
    StageStatus,
    StrategySignal,
    run_phase_303_simulation,
    verify_phase_303_merkle_dag,
)


@pytest.fixture
def orchestrator() -> AutonomousExecutionOrchestrator:
    return AutonomousExecutionOrchestrator(
        candidates=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        starting_equity=Decimal("100.00"),
        exposure_cap=Decimal("60.00"),
        intra_phase_loss_cap=Decimal("7.00"),
        child_order_cap=Decimal("5.00"),
    )


# =====================================================================
# R1: 8-Stage Closed-Loop Pipeline Tests
# =====================================================================


def test_stage1_ingress_sla_healthy_and_stale(
    orchestrator: AutonomousExecutionOrchestrator,
) -> None:
    """Verify Stage 1 checks heartbeat age and halts if SLA > 500 ms."""
    signal = StrategySignal(
        strategy_id="strat-test-01",
        symbol="BTCUSDT",
        side=SignalSide.BUY,
        strength=0.85,
        confidence=0.90,
        target_notional_usdt=Decimal("4.50"),
        horizon_bars=15,
    )

    # Fresh heartbeat: 45 ms <= 500 ms SLA
    res_healthy = orchestrator.orchestrate_cycle(
        symbol="BTCUSDT",
        heartbeat_age_ms=45.0,
        vpin=0.20,
        kyles_lambda=0.0001,
        hawkes_rho=0.30,
        signal=signal,
        best_bid=Decimal("50100.00"),
        best_ask=Decimal("50102.00"),
    )
    stage1 = next(s for s in res_healthy.stages if s.stage == PipelineStage.STAGE_1_INGRESS_SLA)
    assert stage1.status == StageStatus.HEALTHY
    assert res_healthy.cycle_status == CycleStatus.COMPLETED

    # Stale heartbeat: 550 ms > 500 ms SLA -> Cycle halted fail-closed
    res_stale = orchestrator.orchestrate_cycle(
        symbol="BTCUSDT",
        heartbeat_age_ms=550.0,
        vpin=0.20,
        kyles_lambda=0.0001,
        hawkes_rho=0.30,
        signal=signal,
        best_bid=Decimal("50100.00"),
        best_ask=Decimal("50102.00"),
    )
    assert res_stale.cycle_status == CycleStatus.STALE_HALTED
    stage1_stale = next(s for s in res_stale.stages if s.stage == PipelineStage.STAGE_1_INGRESS_SLA)
    assert stage1_stale.status == StageStatus.BLOCKED
    assert "STALE HEARTBEAT" in stage1_stale.detail
    assert len(res_stale.child_orders) == 0


def test_stage2_microstructure_toxicity_and_quote_defense(
    orchestrator: AutonomousExecutionOrchestrator,
) -> None:
    """Verify Stage 2 & Stage 5 pull maker quotes when VPIN or Hawkes rho is toxic."""
    signal = StrategySignal(
        strategy_id="strat-test-02",
        symbol="ETHUSDT",
        side=SignalSide.BUY,
        strength=0.75,
        confidence=0.85,
        target_notional_usdt=Decimal("4.50"),
        horizon_bars=15,
    )

    # High VPIN = 0.82 >= 0.70 threshold & Hawkes rho = 0.88 >= 0.85 threshold
    res_toxic = orchestrator.orchestrate_cycle(
        symbol="ETHUSDT",
        heartbeat_age_ms=65.0,
        vpin=0.82,
        kyles_lambda=0.045,
        hawkes_rho=0.88,
        signal=signal,
        best_bid=Decimal("2380.00"),
        best_ask=Decimal("2380.50"),
    )

    assert res_toxic.cycle_status == CycleStatus.DEFENDED
    assert res_toxic.quote_action == "PULLED_DEFENSE"
    stage2 = next(s for s in res_toxic.stages if s.stage == PipelineStage.STAGE_2_HAZARD_TOXICITY)
    assert stage2.status == StageStatus.DEFENSE_ACTIVE
    assert "TOXIC_DEFENSE_TRIGGERED" in stage2.detail

    stage5 = next(s for s in res_toxic.stages if s.stage == PipelineStage.STAGE_5_QUOTE_SHADING)
    assert stage5.status == StageStatus.DEFENSE_ACTIVE
    assert "PULLED_DEFENSE" in stage5.detail
    # No orders dispatched during defense
    assert len(res_toxic.child_orders) == 0
    assert len(res_toxic.brackets) == 0


def test_stage4_pretrade_risk_and_capital_headroom(
    orchestrator: AutonomousExecutionOrchestrator,
) -> None:
    """Verify Stage 4 enforces exposure ceiling <= 60 USDT and cash reserve >= 40%."""
    signal = StrategySignal(
        strategy_id="strat-test-03",
        symbol="BTCUSDT",
        side=SignalSide.BUY,
        strength=0.90,
        confidence=0.95,
        target_notional_usdt=Decimal("4.50"),
        horizon_bars=15,
    )

    # Artificially tie up margin close to exposure cap
    orchestrator.ledger.allocated_margin = Decimal("58.00")
    orchestrator.ledger.cash = Decimal("42.00")

    # Cycle attempting notional would breach 60 USDT total exposure
    res_interlock = orchestrator.orchestrate_cycle(
        symbol="BTCUSDT",
        heartbeat_age_ms=40.0,
        vpin=0.25,
        kyles_lambda=0.0001,
        hawkes_rho=0.35,
        signal=signal,
        best_bid=Decimal("50100.00"),
        best_ask=Decimal("50102.00"),
    )
    assert res_interlock.cycle_status == CycleStatus.INTERLOCKED
    stage4 = next(s for s in res_interlock.stages if s.stage == PipelineStage.STAGE_4_PRETRADE_RISK)
    assert stage4.status == StageStatus.BLOCKED
    assert "Exposure" in stage4.detail


def test_stage6_micro_order_slicing_and_step_size(
    orchestrator: AutonomousExecutionOrchestrator,
) -> None:
    """Verify child orders satisfy <= 5.00 USDT micro cap with ROUND_DOWN precision."""
    signal = StrategySignal(
        strategy_id="strat-test-04",
        symbol="SOLUSDT",
        side=SignalSide.BUY,
        strength=0.80,
        confidence=0.90,
        target_notional_usdt=Decimal("4.50"),
        horizon_bars=15,
    )

    res = orchestrator.orchestrate_cycle(
        symbol="SOLUSDT",
        heartbeat_age_ms=80.0,
        vpin=0.30,
        kyles_lambda=0.002,
        hawkes_rho=0.42,
        signal=signal,
        best_bid=Decimal("150.00"),
        best_ask=Decimal("150.10"),
        is_maker_preference=False,
    )

    assert res.cycle_status == CycleStatus.COMPLETED
    assert len(res.child_orders) == 1
    child = res.child_orders[0]
    assert child.notional_usdt <= Decimal("5.00")
    # Step size for SOLUSDT is 0.01 -> quantity should have max 2 decimal places
    assert child.quantity == Decimal("0.02")
    assert child.notional_usdt == Decimal("3.00")
    assert child.fee_usdt == Decimal("0.0015")
    assert child.slippage_usdt == Decimal("0.002")


def test_stage7_dynamic_oco_bracket_binding(
    orchestrator: AutonomousExecutionOrchestrator,
) -> None:
    """Verify Take-Profit and Trailing Stop brackets are bound with mutual OCO references."""
    signal = StrategySignal(
        strategy_id="strat-test-05",
        symbol="SOLUSDT",
        side=SignalSide.BUY,
        strength=0.85,
        confidence=0.90,
        target_notional_usdt=Decimal("4.50"),
        horizon_bars=15,
    )

    res = orchestrator.orchestrate_cycle(
        symbol="SOLUSDT",
        heartbeat_age_ms=70.0,
        vpin=0.25,
        kyles_lambda=0.001,
        hawkes_rho=0.35,
        signal=signal,
        best_bid=Decimal("150.00"),
        best_ask=Decimal("150.10"),
    )

    assert len(res.brackets) == 2
    tp_bracket = next(b for b in res.brackets if b.bracket_type == "TAKE_PROFIT_LIMIT")
    tsl_bracket = next(b for b in res.brackets if b.bracket_type == "TRAILING_STOP_MARKET")

    assert tp_bracket.oco_partner_id == tsl_bracket.bracket_id
    assert tsl_bracket.oco_partner_id == tp_bracket.bracket_id
    assert tp_bracket.status == "ACTIVE"
    assert tsl_bracket.status == "ACTIVE"
    assert tp_bracket.trigger_price > tp_bracket.ratchet_watermark
    assert tsl_bracket.trigger_price < tsl_bracket.ratchet_watermark


# =====================================================================
# R2: Shadow Longevity Simulator & Metrics Tests
# =====================================================================


def test_shadow_longevity_simulator_metrics(
    orchestrator: AutonomousExecutionOrchestrator,
) -> None:
    """Verify rolling Sharpe, Calmar, Max Drawdown, and PnL decomposition."""
    sim = ShadowLongevitySimulator(orchestrator)
    tracks = sim.run_longevity_tracks()

    assert "track_1_closed_loop" in tracks
    assert "track_2_hazard_defense" in tracks
    assert "track_3_shadow_longevity" in tracks
    assert "track_4_ecosystem_dag" in tracks

    perf = orchestrator.performance
    assert perf.total_cycles >= 3
    assert perf.completed_cycles >= 2
    assert perf.defended_cycles >= 1
    assert perf.win_rate_pct > 0.0
    assert perf.max_drawdown_pct <= 5.0
    assert perf.total_net_pnl_usdt > 0.0
    assert perf.total_fees_usdt > 0.0
    assert perf.total_slippage_usdt > 0.0
    assert perf.alpha_attribution_pnl_usdt > 0.0


# =====================================================================
# R3: Centralized Solvency Ledger & Zero-Drift Tests
# =====================================================================


def test_centralized_solvency_ledger_zero_drift() -> None:
    """Verify double-entry zero-drift balance invariant strictly holds."""
    ledger = CentralizedSolvencyLedger(starting_equity=Decimal("100.00"))

    # Initial balance check
    ledger.assert_zero_drift()
    assert ledger.drift == Decimal("0.00")

    # Simulate trade: 3 USDT margin allocated, 0.0015 fee, 0.002 slippage
    ledger.record_fill(
        notional_usdt=Decimal("3.00"),
        margin_allocated=Decimal("1.00"),
        fee_usdt=Decimal("0.0015"),
        slippage_usdt=Decimal("0.0020"),
    )
    ledger.update_mark_pnl(Decimal("0.0350"))

    ledger.assert_zero_drift()
    assert abs(ledger.drift) < Decimal("1e-15")

    solvency_dict = ledger.to_solvency_dict()
    assert solvency_dict["zero_balance_drift_verified"] is True
    assert solvency_dict["drift_usdt"] == 0.0
    assert solvency_dict["cash_reserve_pct"] >= 40.0


# =====================================================================
# R4: End-to-End Simulation & Merkle DAG Tests
# =====================================================================


def test_run_phase_303_simulation_and_merkle_verification(tmp_path: Path) -> None:
    """Verify full Phase 303 simulation generates valid artifacts and passes Merkle check."""
    target_dir = tmp_path / "phase303_test"

    summary = run_phase_303_simulation(
        output_dir=target_dir,
        starting_equity=100.0,
    )

    assert summary["verified"] is True
    assert summary["phase"] == "phase_303"
    assert summary["status"] == "ORCHESTRATOR_VERIFIED"
    assert summary["paper_safe"] is True
    assert summary["execution_authority"] is False

    # Check generated files
    assert (target_dir / "canary-orchestrator-telemetry.sqlite3").is_file()
    assert (target_dir / "canary-orchestrator-events.jsonl").is_file()
    assert (target_dir / "orchestrator-summary.json").is_file()
    assert (target_dir / "canary-orchestrator-report.json").is_file()
    assert (target_dir / "paper-summary.json").is_file()

    # Verify Merkle DAG integrity
    is_valid = verify_phase_303_merkle_dag(target_dir)
    assert is_valid is True
