"""Unit tests for Phase 305: Autonomous Multi-Horizon Alpha Ensemble & Meta-Policy Blending."""

from __future__ import annotations

import tempfile
from pathlib import Path

from autonomous_futures.feed.alpha_ensemble import (
    UPSTREAM_PHASE304_ROOT_HASH,
    AlphaHorizon,
    CentralizedSolvencyLedger,
    EnsembleState,
    MarketRegime,
    MetaPolicyBlendingEngine,
    MultiHorizonAlphaExtractor,
    run_phase_305_simulation,
    verify_phase_305_merkle_dag,
)


def test_micro_signal_extraction() -> None:
    """Test micro horizon extracts OFI and applies Hawkes hazard damping."""
    extractor = MultiHorizonAlphaExtractor()
    # Bullish OFI with calm hazard
    sig = extractor.extract_micro_signal(
        symbol="BTCUSDT",
        timestamp_ms=1000,
        order_flow_imbalance=0.50,
        hawkes_hazard=0.25,
        quote_pressure=0.30,
    )
    assert sig.horizon == AlphaHorizon.MICRO_1S_5S
    assert sig.direction > 0.0
    assert sig.conviction > 0.20
    assert sig.features["ofi"] == 0.50
    assert sig.features["hazard_damping"] == 1.0

    # Spiking Hawkes hazard should damp conviction
    sig_spiked = extractor.extract_micro_signal(
        symbol="BTCUSDT",
        timestamp_ms=1001,
        order_flow_imbalance=0.50,
        hawkes_hazard=1.10,
        quote_pressure=0.30,
    )
    assert sig_spiked.conviction < sig.conviction
    assert sig_spiked.features["hazard_damping"] < 0.50


def test_short_signal_extraction() -> None:
    """Test short horizon extracts VWAP deviation and momentum."""
    extractor = MultiHorizonAlphaExtractor()
    sig = extractor.extract_short_signal(
        symbol="ETHUSDT",
        timestamp_ms=2000,
        vwap_deviation_bps=-10.0,
        short_momentum_pct=0.80,
        volatility_ratio=1.2,
    )
    assert sig.horizon == AlphaHorizon.SHORT_1M_5M
    assert sig.direction > 0.0
    assert sig.conviction > 0.30
    assert sig.features["short_momentum_pct"] == 0.80


def test_medium_signal_extraction() -> None:
    """Test medium horizon extracts Donchian position and trend slope."""
    extractor = MultiHorizonAlphaExtractor()
    sig = extractor.extract_medium_signal(
        symbol="SOLUSDT",
        timestamp_ms=3000,
        donchian_channel_pos=0.85,
        trend_slope_bps=18.0,
        adx_trend_strength=45.0,
    )
    assert sig.horizon == AlphaHorizon.MEDIUM_15M_1H
    assert sig.direction > 0.50
    assert sig.conviction > 0.40
    assert sig.features["adx_trend_strength"] == 45.0


def test_meta_policy_weights_per_regime() -> None:
    """Test dynamic weight distribution conditioned on Phase 304 regimes."""
    engine = MetaPolicyBlendingEngine()

    calm_w = engine.get_regime_weights(MarketRegime.CALM_BALANCED)
    assert calm_w.micro_weight == 0.35
    assert calm_w.short_weight == 0.35
    assert calm_w.medium_weight == 0.30
    assert calm_w.weights_sum == 1.0

    trend_w = engine.get_regime_weights(MarketRegime.TRENDING_MOMENTUM)
    assert trend_w.medium_weight == 0.50
    assert trend_w.weights_sum == 1.0

    vol_w = engine.get_regime_weights(MarketRegime.VOLATILITY_EXPANSION)
    assert vol_w.micro_weight == 0.50

    mean_rev_w = engine.get_regime_weights(MarketRegime.MEAN_REVERTING)
    assert mean_rev_w.micro_weight == 0.45

    toxic_w = engine.get_regime_weights(MarketRegime.TOXIC_TURBULENCE)
    assert toxic_w.weights_sum == 0.0


def test_directional_conflict_shading() -> None:
    """Test conflict penalty shading when micro and medium signals contradict."""
    extractor = MultiHorizonAlphaExtractor()
    engine = MetaPolicyBlendingEngine(conflict_penalty=0.40)

    # Contradicting: Micro strongly bearish (-0.80), Medium strongly bullish (+0.80)
    micro_sig = extractor.extract_micro_signal(
        symbol="BTCUSDT",
        timestamp_ms=1000,
        order_flow_imbalance=-0.80,
        hawkes_hazard=0.30,
        quote_pressure=-0.70,
    )
    short_sig = extractor.extract_short_signal(
        symbol="BTCUSDT",
        timestamp_ms=1000,
        vwap_deviation_bps=2.0,
        short_momentum_pct=0.10,
        volatility_ratio=1.0,
    )
    med_sig = extractor.extract_medium_signal(
        symbol="BTCUSDT",
        timestamp_ms=1000,
        donchian_channel_pos=0.80,
        trend_slope_bps=15.0,
        adx_trend_strength=40.0,
    )

    signals = {
        str(AlphaHorizon.MICRO_1S_5S): micro_sig,
        str(AlphaHorizon.SHORT_1M_5M): short_sig,
        str(AlphaHorizon.MEDIUM_15M_1H): med_sig,
    }

    decision = engine.blend(
        symbol="BTCUSDT",
        timestamp_ms=1000,
        regime=MarketRegime.CALM_BALANCED,
        signals=signals,
    )

    assert decision.conflict_detected is True
    assert decision.conflict_penalty == 0.40
    assert decision.ensemble_state == EnsembleState.CONFLICT_SHADED
    assert decision.effective_conviction < decision.raw_blended_conviction


def test_toxic_turbulence_emergency_suppression() -> None:
    """Test emergency defense lockout suppression under toxic turbulence."""
    extractor = MultiHorizonAlphaExtractor()
    engine = MetaPolicyBlendingEngine()

    signals = {
        str(AlphaHorizon.MICRO_1S_5S): extractor.extract_micro_signal(
            "ETHUSDT", 2000, -0.90, 1.50, -0.90
        ),
        str(AlphaHorizon.SHORT_1M_5M): extractor.extract_short_signal(
            "ETHUSDT", 2000, -30.0, -1.5, 4.0
        ),
        str(AlphaHorizon.MEDIUM_15M_1H): extractor.extract_medium_signal(
            "ETHUSDT", 2000, -0.9, -25.0, 70.0
        ),
    }

    decision = engine.blend(
        symbol="ETHUSDT",
        timestamp_ms=2000,
        regime=MarketRegime.TOXIC_TURBULENCE,
        signals=signals,
    )

    assert decision.target_action == "DEFENSIVE_SUPPRESSED"
    assert decision.target_micro_chunk_usdt == 0.0
    assert decision.effective_conviction == 0.0
    assert decision.ensemble_state == EnsembleState.DEFENSE_LOCKOUT


def test_solvency_ledger_zero_drift() -> None:
    """Test CentralizedSolvencyLedger maintains exact double-entry zero drift (|drift| < 1e-15)."""
    ledger = CentralizedSolvencyLedger(starting_equity_usdt=100.0)

    # Initial state
    assert ledger.compute_drift() < 1e-15
    summary = ledger.get_summary()
    assert summary["zero_balance_drift_verified"] is True
    assert summary["cash_reserve_pct"] == 100.0
    assert summary["unencumbered_cash_verified"] is True

    # Apply executions
    ledger.apply_execution(
        margin_allocated=4.50,
        fee_usdt=0.0045,
        slippage_usdt=0.0015,
        unrealized_pnl_delta=0.25,
        realized_pnl_delta=0.0,
    )
    assert ledger.compute_drift() < 1e-15

    ledger.apply_execution(
        margin_allocated=-4.50,
        fee_usdt=0.0045,
        slippage_usdt=0.0010,
        unrealized_pnl_delta=-0.25,
        realized_pnl_delta=0.35,
    )
    assert ledger.compute_drift() < 1e-15
    summary2 = ledger.get_summary()
    assert summary2["drift_usdt"] < 1e-15
    assert summary2["unencumbered_cash_verified"] is True


def test_ensemble_longevity_simulation_and_merkle_dag() -> None:
    """Test full longevity simulation and Merkle DAG integrity verification."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        summary = run_phase_305_simulation(
            output_dir=tmp_path,
            starting_equity=100.0,
            parent_merkle_root=UPSTREAM_PHASE304_ROOT_HASH,
        )

        assert summary["status"] == "ENSEMBLE_VERIFIED"
        assert summary["verified"] is True
        assert summary["paper_safe"] is True
        assert summary["execution_authority"] is False
        assert summary["solvency"]["drift_usdt"] < 1e-15
        assert summary["performance"]["total_decisions"] > 0
        assert summary["merkle_root"] != ""

        # Test verification helper
        is_valid = verify_phase_305_merkle_dag(
            output_dir=tmp_path,
            parent_merkle_root=UPSTREAM_PHASE304_ROOT_HASH,
        )
        assert is_valid is True

        # Tampering with SQLite should fail verification
        sqlite_file = tmp_path / "canary-ensemble-telemetry.sqlite3"
        sqlite_file.write_bytes(sqlite_file.read_bytes() + b"corrupt")
        assert (
            verify_phase_305_merkle_dag(
                output_dir=tmp_path,
                parent_merkle_root=UPSTREAM_PHASE304_ROOT_HASH,
            )
            is False
        )
