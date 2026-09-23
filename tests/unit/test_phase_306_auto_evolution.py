"""Unit tests for Phase 306: Continuous Self-Learning Loop, Strategy Autopsy & Auto-Evolution."""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

from autonomous_futures.feed.auto_evolution import (
    UPSTREAM_PHASE305_ROOT_HASH,
    AutopsyAttributionCause,
    CandidateGeneSet,
    CandidateHealthTier,
    CentralizedSolvencyLedger,
    ContinuousSelfLearningDaemon,
    GeneticMutationEngine,
    ShadowCandidateSandbox,
    StrategyAutopsyEngine,
    TradeAutopsyRecord,
    run_phase_306_simulation,
    verify_phase_306_merkle_dag,
)


def test_strategy_autopsy_deconstruction() -> None:
    """Test trade autopsy correctly deconstructs execution friction and classifies cause."""
    engine = StrategyAutopsyEngine()

    # Winning trade with organic alpha
    win_autopsy = engine.deconstruct_trade(
        trade_id="test-win-01",
        candidate_id="cand-btcusdt-dcb-002",
        symbol="BTCUSDT",
        side="BUY",
        entry_price=95000.0,
        exit_price=95300.0,
        fill_qty=0.0001,
        optimal_price=94990.0,
        hawkes_intensity=0.30,
        adverse_delta_pct=0.0001,
        timestamp_ms=1000,
    )
    assert win_autopsy.cause == AutopsyAttributionCause.ORGANIC_ALPHA
    assert win_autopsy.net_pnl_usdt > 0.0
    assert win_autopsy.realized_edge_bps > 0.0
    assert win_autopsy.entry_timing_error_bps > 0.0

    # Losing trade due to heavy Hawkes cluster
    loss_hawkes = engine.deconstruct_trade(
        trade_id="test-loss-01",
        candidate_id="cand-ethusdt-dcb-003",
        symbol="ETHUSDT",
        side="BUY",
        entry_price=2750.0,
        exit_price=2735.0,
        fill_qty=0.002,
        optimal_price=2748.0,
        hawkes_intensity=0.85,
        adverse_delta_pct=0.0010,
        timestamp_ms=2000,
    )
    assert loss_hawkes.cause == AutopsyAttributionCause.HAWKES_CLUSTER
    assert loss_hawkes.net_pnl_usdt < 0.0
    assert loss_hawkes.hawkes_slip_drag_bps > 5.0

    # Losing trade due to entry timing delay
    loss_timing = engine.deconstruct_trade(
        trade_id="test-loss-02",
        candidate_id="cand-solusdt-rgb-001",
        symbol="SOLUSDT",
        side="BUY",
        entry_price=188.0,
        exit_price=187.0,
        fill_qty=0.02,
        optimal_price=186.5,
        hawkes_intensity=0.20,
        adverse_delta_pct=0.0001,
        timestamp_ms=3000,
    )
    assert loss_timing.cause == AutopsyAttributionCause.TIMING_DELAY
    assert loss_timing.entry_timing_error_bps > 6.0


def test_candidate_health_tier_classification() -> None:
    """Test rolling performance classification distinguishes ELITE, HEALTHY, and DEGRADED."""
    daemon = ContinuousSelfLearningDaemon()

    # Winning records -> ELITE
    elite_records = [
        TradeAutopsyRecord(
            trade_id=f"t-{i}",
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side="BUY",
            entry_price=95000.0,
            exit_price=95200.0,
            fill_qty=0.0001,
            entry_timing_error_bps=1.0,
            hawkes_slip_drag_bps=2.0,
            adverse_selection_bps=0.5,
            realized_edge_bps=15.0,
            gross_pnl_usdt=0.02,
            fee_cost_usdt=0.005,
            net_pnl_usdt=0.015,
            cause=AutopsyAttributionCause.ORGANIC_ALPHA,
            timestamp_ms=1000 + i * 1000,
        )
        for i in range(10)
    ]
    elite_eval = daemon.evaluate_candidate("cand-btc", "BTCUSDT", elite_records)
    assert elite_eval.tier == CandidateHealthTier.ELITE
    assert elite_eval.rolling_sharpe >= 2.0
    assert elite_eval.win_rate_pct == 100.0
    assert not elite_eval.needs_mutation

    # Degraded records (consecutive losses) -> DEGRADED
    degraded_records = [
        TradeAutopsyRecord(
            trade_id=f"t-loss-{i}",
            candidate_id="cand-eth",
            symbol="ETHUSDT",
            side="BUY",
            entry_price=2750.0,
            exit_price=2740.0,
            fill_qty=0.002,
            entry_timing_error_bps=5.0,
            hawkes_slip_drag_bps=7.5,
            adverse_selection_bps=8.0,
            realized_edge_bps=-20.0,
            gross_pnl_usdt=-0.02,
            fee_cost_usdt=0.005,
            net_pnl_usdt=-0.025,
            cause=AutopsyAttributionCause.HAWKES_CLUSTER,
            timestamp_ms=2000 + i * 1000,
        )
        for i in range(5)
    ]
    deg_eval = daemon.evaluate_candidate("cand-eth", "ETHUSDT", degraded_records)
    assert deg_eval.tier == CandidateHealthTier.DEGRADED
    assert deg_eval.consecutive_losses >= 3
    assert deg_eval.needs_mutation


def test_genetic_mutation_engine_bounds_clamping() -> None:
    """Test genetic mutation adjusts parameters and strictly clamps to safe bounds."""
    mutator = GeneticMutationEngine()
    parent = CandidateGeneSet(
        candidate_id="cand-ethusdt-dcb-003",
        generation=1,
        parent_candidate_id=None,
        donchian_period=20,
        atr_multiplier=2.0,
        hawkes_intensity_threshold=0.65,
        micro_horizon_bias=0.35,
        mutation_rationale="Initial parent",
    )

    # Mutate for Hawkes cluster
    mutated_hawkes = mutator.mutate_candidate(parent, AutopsyAttributionCause.HAWKES_CLUSTER)
    assert mutated_hawkes.generation == 2
    assert mutated_hawkes.parent_candidate_id == "cand-ethusdt-dcb-003"
    assert mutated_hawkes.atr_multiplier > parent.atr_multiplier
    assert mutated_hawkes.hawkes_intensity_threshold < parent.hawkes_intensity_threshold
    assert mutator.MIN_ATR_MULT <= mutated_hawkes.atr_multiplier <= mutator.MAX_ATR_MULT
    assert (
        mutator.MIN_HAWKES_THRESH
        <= mutated_hawkes.hawkes_intensity_threshold
        <= mutator.MAX_HAWKES_THRESH
    )

    # Edge test: extreme parent values must clamp safely
    extreme_parent = CandidateGeneSet(
        candidate_id="cand-solusdt-ext-001",
        generation=3,
        parent_candidate_id=None,
        donchian_period=10,  # Minimum boundary
        atr_multiplier=3.95,  # Near maximum boundary
        hawkes_intensity_threshold=0.88,
        micro_horizon_bias=0.58,
        mutation_rationale="Extreme boundary parent",
    )
    mutated_extreme = mutator.mutate_candidate(extreme_parent, AutopsyAttributionCause.TIMING_DELAY)
    assert mutated_extreme.donchian_period == mutator.MIN_DONCHIAN
    assert mutated_extreme.micro_horizon_bias <= mutator.MAX_MICRO_BIAS


def test_shadow_candidate_sandbox_promotion() -> None:
    """Test shadow staging candidate promotion hurdle logic."""
    sandbox = ShadowCandidateSandbox(min_promotion_improvement_pct=15.0)

    # Rejection: insufficient shadow ticks
    eval_insufficient = sandbox.evaluate_shadow_promotion(
        staged_candidate_id="cand-eth-evo-002",
        parent_candidate_id="cand-eth-dcb-003",
        symbol="ETHUSDT",
        shadow_ticks=5,
        shadow_sharpe=2.5,
        parent_sharpe=1.0,
    )
    assert not eval_insufficient.promoted
    assert "Insufficient shadow ticks" in (eval_insufficient.rejection_reason or "")

    # Rejection: improvement below 15% hurdle
    eval_low_imp = sandbox.evaluate_shadow_promotion(
        staged_candidate_id="cand-eth-evo-002",
        parent_candidate_id="cand-eth-dcb-003",
        symbol="ETHUSDT",
        shadow_ticks=15,
        shadow_sharpe=1.08,
        parent_sharpe=1.00,
    )
    assert not eval_low_imp.promoted
    assert "below hurdle" in (eval_low_imp.rejection_reason or "")

    # Success: improvement above hurdle with sufficient ticks
    eval_promoted = sandbox.evaluate_shadow_promotion(
        staged_candidate_id="cand-eth-evo-002",
        parent_candidate_id="cand-eth-dcb-003",
        symbol="ETHUSDT",
        shadow_ticks=15,
        shadow_sharpe=1.40,
        parent_sharpe=1.00,
    )
    assert eval_promoted.promoted
    assert eval_promoted.rejection_reason is None
    assert eval_promoted.improvement_pct == 40.0


def test_centralized_solvency_ledger_zero_drift() -> None:
    """Test double-entry zero-drift balance invariant strictly holds."""
    ledger = CentralizedSolvencyLedger(starting_equity_usdt=100.0)
    assert ledger.compute_drift() < Decimal("1e-15")

    # Micro child slicing
    chunk = ledger.slice_micro_child(15.0)
    assert chunk <= Decimal("5.00")

    # Round-trip trades
    ok, drift = ledger.apply_execution(margin_delta=0.0, realized_pnl_delta=0.50, fee_delta=0.01)
    assert ok
    assert drift < Decimal("1e-15")

    ok2, drift2 = ledger.apply_execution(margin_delta=0.0, realized_pnl_delta=-0.25, fee_delta=0.01)
    assert ok2
    assert drift2 < Decimal("1e-15")

    summary = ledger.get_summary()
    assert summary["zero_drift_valid"]
    assert summary["drift_usdt"] < 1e-15


def test_phase_306_simulation_and_merkle_dag_verification() -> None:
    """Test end-to-end simulation runner produces valid artifacts and Merkle DAG chain."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        summary = run_phase_306_simulation(
            output_dir=out_dir,
            starting_equity=100.0,
            parent_merkle_root=UPSTREAM_PHASE305_ROOT_HASH,
        )
        assert summary["phase"] == "phase_306"
        assert summary["status"] == "EVOLUTION_VERIFIED"
        assert summary["upstream_hash"] == UPSTREAM_PHASE305_ROOT_HASH
        assert summary["solvency"]["zero_drift_valid"]

        is_valid = verify_phase_306_merkle_dag(
            output_dir=out_dir,
            parent_merkle_root=UPSTREAM_PHASE305_ROOT_HASH,
        )
        assert is_valid
