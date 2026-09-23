"""Unit tests for Phase 304: Self-Calibrating Parameter Adaptation & Regime Learning."""

from __future__ import annotations

import tempfile
from pathlib import Path

from autonomous_futures.feed.regime_calibration import (
    PARAMETER_BOUNDS,
    CalibrationLongevitySimulator,
    CentralizedSolvencyLedger,
    MarketRegime,
    MarketRegimeDetector,
    MicrostructureTelemetrySnapshot,
    SelfCalibratingParameterEngine,
    verify_phase_304_merkle_dag,
)


def test_market_regime_detection_calm() -> None:
    """Test regime detection correctly classifies calm, balanced market conditions."""
    detector = MarketRegimeDetector()
    snap = MicrostructureTelemetrySnapshot(
        symbol="BTCUSDT",
        timestamp_ms=1000,
        mid_price=50000.0,
        spread_bps=1.5,
        parkinson_volatility=0.008,
        order_flow_imbalance=0.05,
        vpin=0.15,
        hawkes_hazard=0.20,
        depth_skew=0.02,
    )
    result = detector.classify(snap)
    assert result.dominant_regime == MarketRegime.CALM_BALANCED
    assert result.confidence >= 0.50
    assert "CALM_BALANCED" in result.transition_probabilities


def test_market_regime_detection_toxic_override() -> None:
    """Test toxic conditions (VPIN >= 0.65 or Hawkes rho >= 0.75) trigger toxic turbulence."""
    detector = MarketRegimeDetector()
    snap = MicrostructureTelemetrySnapshot(
        symbol="ETHUSDT",
        timestamp_ms=2000,
        mid_price=3000.0,
        spread_bps=8.5,
        parkinson_volatility=0.045,
        order_flow_imbalance=-0.80,
        vpin=0.75,
        hawkes_hazard=0.88,
        depth_skew=-0.65,
    )
    result = detector.classify(snap)
    assert result.dominant_regime == MarketRegime.TOXIC_TURBULENCE
    assert result.confidence >= 0.75


def test_market_regime_detection_trending() -> None:
    """Test persistent order flow imbalance classifies as trending momentum."""
    detector = MarketRegimeDetector()
    snap = MicrostructureTelemetrySnapshot(
        symbol="SOLUSDT",
        timestamp_ms=3000,
        mid_price=150.0,
        spread_bps=2.5,
        parkinson_volatility=0.020,
        order_flow_imbalance=0.75,
        vpin=0.30,
        hawkes_hazard=0.35,
        depth_skew=0.55,
    )
    result = detector.classify(snap)
    assert result.dominant_regime == MarketRegime.TRENDING_MOMENTUM


def test_parameter_calibration_and_damping() -> None:
    """Test parameter adaptation applies exponential moving average damping smoothly."""
    detector = MarketRegimeDetector()
    calibrator = SelfCalibratingParameterEngine(damping_alpha=0.15)

    snap1 = MicrostructureTelemetrySnapshot(
        symbol="BTCUSDT",
        timestamp_ms=1000,
        mid_price=50000.0,
        spread_bps=1.5,
        parkinson_volatility=0.010,
        order_flow_imbalance=0.10,
        vpin=0.20,
        hawkes_hazard=0.25,
        depth_skew=0.05,
    )
    res1 = detector.classify(snap1)
    rec1 = calibrator.calibrate("BTCUSDT", res1, snap1)

    initial_gamma = rec1.damped_parameters.risk_aversion_gamma
    assert initial_gamma > 0.0

    # Sudden volatility expansion shock
    snap2 = MicrostructureTelemetrySnapshot(
        symbol="BTCUSDT",
        timestamp_ms=2000,
        mid_price=50200.0,
        spread_bps=7.0,
        parkinson_volatility=0.050,
        order_flow_imbalance=0.30,
        vpin=0.55,
        hawkes_hazard=0.70,
        depth_skew=0.25,
    )
    res2 = detector.classify(snap2)
    rec2 = calibrator.calibrate("BTCUSDT", res2, snap2)

    # With damping alpha=0.15, gamma moves towards target without jumping to raw target
    assert rec2.damped_parameters.risk_aversion_gamma > initial_gamma
    assert rec2.damped_parameters.risk_aversion_gamma < rec2.raw_target.risk_aversion_gamma


def test_parameter_bounds_guardrail_clamping() -> None:
    """Test extreme market inputs are strictly clamped within guardrail bounds."""
    detector = MarketRegimeDetector()
    calibrator = SelfCalibratingParameterEngine(damping_alpha=1.0)  # instantaneous to test bounds

    extreme_snap = MicrostructureTelemetrySnapshot(
        symbol="ETHUSDT",
        timestamp_ms=5000,
        mid_price=3000.0,
        spread_bps=150.0,  # massive spread
        parkinson_volatility=0.50,  # 50% volatility
        order_flow_imbalance=1.0,
        vpin=0.99,
        hawkes_hazard=2.0,
        depth_skew=1.0,
    )
    res = detector.classify(extreme_snap)
    rec = calibrator.calibrate("ETHUSDT", res, extreme_snap)

    p = rec.damped_parameters
    assert (
        PARAMETER_BOUNDS["risk_aversion_gamma"][0]
        <= p.risk_aversion_gamma
        <= PARAMETER_BOUNDS["risk_aversion_gamma"][1]
    )
    assert (
        PARAMETER_BOUNDS["hawkes_decay_beta"][0]
        <= p.hawkes_decay_beta
        <= PARAMETER_BOUNDS["hawkes_decay_beta"][1]
    )
    assert (
        PARAMETER_BOUNDS["reservation_cushion_bps"][0]
        <= p.reservation_cushion_bps
        <= PARAMETER_BOUNDS["reservation_cushion_bps"][1]
    )
    assert (
        PARAMETER_BOUNDS["micro_chunk_usdt"][0]
        <= p.micro_chunk_usdt
        <= PARAMETER_BOUNDS["micro_chunk_usdt"][1]
    )


def test_centralized_solvency_ledger_zero_drift() -> None:
    """Test double-entry accounting preserves zero-drift balance (|drift| < 1e-15 USDT)."""
    ledger = CentralizedSolvencyLedger(starting_equity_usdt=100.0)

    ledger.apply_execution(
        margin_allocated=2.50,
        fee_usdt=0.0015,
        slippage_usdt=0.0020,
        unrealized_pnl_delta=0.0450,
    )
    drift = ledger.compute_drift()
    assert drift < 1e-15

    summary = ledger.get_summary()
    assert summary["zero_balance_drift_verified"] is True
    assert summary["drift_usdt"] == 0.0
    assert summary["unencumbered_cash_verified"] is True


def test_calibration_longevity_simulation_and_merkle_dag() -> None:
    """Test complete Phase 304 simulation run and cryptographic Merkle DAG integrity."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir) / "phase304"
        sim = CalibrationLongevitySimulator(output_dir=out_dir)
        summary = sim.run_simulation()

        assert summary["status"] == "CALIBRATION_VERIFIED"
        assert summary["verified"] is True
        assert summary["solvency"]["zero_balance_drift_verified"] is True
        assert (out_dir / "canary-calibration-telemetry.sqlite3").exists()
        assert (out_dir / "canary-calibration-events.jsonl").exists()
        assert (out_dir / "calibration-summary.json").exists()

        is_valid = verify_phase_304_merkle_dag(output_dir=out_dir)
        assert is_valid is True
