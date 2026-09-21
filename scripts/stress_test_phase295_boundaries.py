#!/usr/bin/env python3
"""Adversarial Boundary Condition & Real-Time Veto Stress Test Harness.

Phase 295: Live Strategy Activation & Walk-Forward OOS Promotion Gates
Empirical challenger stress harness verifying:
1. evaluate_oos_promotion_gates boundary conditions:
   - Return: -0.0000001 vs 0.0000000 vs +0.0000001
   - Drawdown: 15.00001% vs 15.00000% vs 15.00050% vs 15.00051% vs 15.00100%
   - Profit factor: 1.049999 vs 1.050000 vs 1.050001
   - Trade count: 4 vs 5
2. Real-time fail-closed veto interlocks & signal dispatch suppression:
   - Hawkes spectral radius rho=1.00000 immediately suppresses signal dispatch
   - Gateway heartbeat age 500.001 ms blocks signal dispatch
   - Margin exposure 60.0001 USDT blocks signal dispatch
   - Cash reserve 39.999% blocks signal dispatch
   - Loss budget 7.0000 USDT triggers emergency micro-chunk flattening (<= 5 USDT)
"""

from __future__ import annotations

import argparse
import json
import logging
from decimal import Decimal
from typing import Any

from autonomous_futures.feed.paper_execution import (
    HARD_MICRO_NOTIONAL_CAP_USDT,
)
from autonomous_futures.feed.paper_risk import (
    CircuitState,
    InterlockCode,
    LivePaperRiskInterlock,
)
from autonomous_futures.feed.strategy_activation import (
    CandidateLifecycleStateMachine,
    CandidatePromotionStatus,
    GatewayHealth,
    HawkesTelemetrySnapshot,
    evaluate_oos_promotion_gates,
    validate_realtime_veto_interlocks,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("stress_test_phase295_boundaries")


def make_candidate_and_qualification(
    candidate_id: str = "cand-stress-001",
    symbol: str = "BTCUSDT",
    avg_return: Decimal = Decimal("2.5"),
    drawdown: Decimal = Decimal("10.0"),
    profit_factor: Decimal = Decimal("1.50"),
    trade_count: int = 10,
    window_count: int = 3,
    decision: str = "qualified",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate synthetic candidate and qualification dictionaries for boundary testing."""
    candidate = {
        "candidate_id": candidate_id,
        "strategy": {
            "universe": {
                "symbols": [symbol],
            }
        },
    }
    qualification = {
        "candidate_id": candidate_id,
        "decision": decision,
        "windows_evaluated": window_count,
        "metrics": [
            {"metric_id": "oos_average_return_pct", "value": str(avg_return)},
            {"metric_id": "oos_worst_drawdown_pct", "value": str(drawdown)},
            {"metric_id": "oos_profit_factor", "value": str(profit_factor)},
            {"metric_id": "oos_total_trades", "value": str(trade_count)},
            {"metric_id": "oos_window_count", "value": str(window_count)},
        ],
    }
    return candidate, qualification


# =====================================================================
# Stress Test Part 1: evaluate_oos_promotion_gates Boundary Tests
# =====================================================================


def test_oos_gate_return_boundary() -> dict[str, Any]:
    """Test boundary condition: return = -0.0000001 vs 0.0000000 vs +0.0000001."""
    results: dict[str, Any] = {}

    # Case 1: return = -0.0000001 (slightly negative)
    c_neg, q_neg = make_candidate_and_qualification(avg_return=Decimal("-0.0000001"))
    rec_neg = evaluate_oos_promotion_gates(c_neg, q_neg)
    assert not rec_neg.qualified, "Expected return -0.0000001 to fail qualification"
    assert rec_neg.status == CandidatePromotionStatus.BLOCKED
    assert not rec_neg.gates_passed["oos_average_return"]
    results["return_neg_1e7"] = {
        "input": "-0.0000001",
        "passed": rec_neg.gates_passed["oos_average_return"],
        "qualified": rec_neg.qualified,
        "status": rec_neg.status.value,
        "explanation": (
            "Strict pre-quantization comparison raw_avg_return >= 0.0 rejects negative values."
        ),
    }

    # Case 2: return = 0.0000000 (exact zero)
    c_zero, q_zero = make_candidate_and_qualification(avg_return=Decimal("0.0000000"))
    rec_zero = evaluate_oos_promotion_gates(c_zero, q_zero)
    assert rec_zero.qualified, "Expected return 0.0000000 to pass qualification"
    assert rec_zero.status == CandidatePromotionStatus.PROMOTED
    assert rec_zero.gates_passed["oos_average_return"]
    results["return_zero"] = {
        "input": "0.0000000",
        "passed": rec_zero.gates_passed["oos_average_return"],
        "qualified": rec_zero.qualified,
        "status": rec_zero.status.value,
        "explanation": "Exact zero passes boundary condition raw_avg_return >= 0.0.",
    }

    # Case 3: return = +0.0000001 (slightly positive)
    c_pos, q_pos = make_candidate_and_qualification(avg_return=Decimal("0.0000001"))
    rec_pos = evaluate_oos_promotion_gates(c_pos, q_pos)
    assert rec_pos.qualified, "Expected return +0.0000001 to pass qualification"
    assert rec_pos.status == CandidatePromotionStatus.PROMOTED
    assert rec_pos.gates_passed["oos_average_return"]
    results["return_pos_1e7"] = {
        "input": "+0.0000001",
        "passed": rec_pos.gates_passed["oos_average_return"],
        "qualified": rec_pos.qualified,
        "status": rec_pos.status.value,
        "explanation": "Strict positive value passes raw_avg_return >= 0.0.",
    }

    return results


def test_oos_gate_drawdown_boundary() -> dict[str, Any]:
    """Test boundary condition: drawdown 15.00001% vs 15.00000% vs 15.00051%."""
    results: dict[str, Any] = {}

    # Case 1: drawdown = 15.00000% (exact ceiling)
    c_eq, q_eq = make_candidate_and_qualification(drawdown=Decimal("15.00000"))
    rec_eq = evaluate_oos_promotion_gates(c_eq, q_eq)
    assert rec_eq.qualified
    assert rec_eq.gates_passed["oos_worst_drawdown"]
    results["dd_15_00000"] = {
        "input": "15.00000%",
        "quantized_drawdown_pct": str(rec_eq.oos_worst_drawdown_pct),
        "passed": rec_eq.gates_passed["oos_worst_drawdown"],
        "qualified": rec_eq.qualified,
        "status": rec_eq.status.value,
        "explanation": "Exact 15.00000% quantizes to 15.000% <= 15.00%, passes gate.",
    }

    # Case 2: drawdown = 15.00001% (slightly above 15.0%)
    c_15_00001, q_15_00001 = make_candidate_and_qualification(drawdown=Decimal("15.00001"))
    rec_15_00001 = evaluate_oos_promotion_gates(c_15_00001, q_15_00001)
    results["dd_15_00001"] = {
        "input": "15.00001%",
        "quantized_drawdown_pct": str(rec_15_00001.oos_worst_drawdown_pct),
        "passed": rec_15_00001.gates_passed["oos_worst_drawdown"],
        "qualified": rec_15_00001.qualified,
        "status": rec_15_00001.status.value,
        "explanation": (
            "Because evaluate_oos_promotion_gates performs scale-invariant normalization with "
            "3-decimal quantization (Decimal('0.001')), 15.00001% rounds to 15.000% <= 15.00%, "
            "allowing it to pass the gate."
        ),
    }

    # Case 3: drawdown = 15.00050% (half-even rounding boundary)
    c_15_00050, q_15_00050 = make_candidate_and_qualification(drawdown=Decimal("15.00050"))
    rec_15_00050 = evaluate_oos_promotion_gates(c_15_00050, q_15_00050)
    results["dd_15_00050"] = {
        "input": "15.00050%",
        "quantized_drawdown_pct": str(rec_15_00050.oos_worst_drawdown_pct),
        "passed": rec_15_00050.gates_passed["oos_worst_drawdown"],
        "qualified": rec_15_00050.qualified,
        "status": rec_15_00050.status.value,
        "explanation": "15.00050% rounds to even (15.000%), <= 15.00%, passes gate.",
    }

    # Case 4: drawdown = 15.00051% (just above half-even boundary)
    c_15_00051, q_15_00051 = make_candidate_and_qualification(drawdown=Decimal("15.00051"))
    rec_15_00051 = evaluate_oos_promotion_gates(c_15_00051, q_15_00051)
    assert not rec_15_00051.qualified
    assert not rec_15_00051.gates_passed["oos_worst_drawdown"]
    results["dd_15_00051"] = {
        "input": "15.00051%",
        "quantized_drawdown_pct": str(rec_15_00051.oos_worst_drawdown_pct),
        "passed": rec_15_00051.gates_passed["oos_worst_drawdown"],
        "qualified": rec_15_00051.qualified,
        "status": rec_15_00051.status.value,
        "explanation": "15.00051% rounds to 15.001% > 15.00%, fails gate and gets BLOCKED.",
    }

    # Case 5: drawdown = 15.00100% (1 basis point above 15%)
    c_15_001, q_15_001 = make_candidate_and_qualification(drawdown=Decimal("15.00100"))
    rec_15_001 = evaluate_oos_promotion_gates(c_15_001, q_15_001)
    assert not rec_15_001.qualified
    assert not rec_15_001.gates_passed["oos_worst_drawdown"]
    results["dd_15_00100"] = {
        "input": "15.00100%",
        "quantized_drawdown_pct": str(rec_15_001.oos_worst_drawdown_pct),
        "passed": rec_15_001.gates_passed["oos_worst_drawdown"],
        "qualified": rec_15_001.qualified,
        "status": rec_15_001.status.value,
        "explanation": "15.00100% quantizes to 15.001% > 15.00%, fails gate and gets BLOCKED.",
    }

    return results


def test_oos_gate_profit_factor_boundary() -> dict[str, Any]:
    """Test boundary condition: profit factor = 1.049999 vs 1.050000 vs 1.050001."""
    results: dict[str, Any] = {}

    # Case 1: profit factor = 1.049999 (substandard by 0.000001)
    c_sub, q_sub = make_candidate_and_qualification(profit_factor=Decimal("1.049999"))
    rec_sub = evaluate_oos_promotion_gates(c_sub, q_sub)
    assert not rec_sub.qualified, "Expected PF 1.049999 to fail qualification"
    assert rec_sub.status == CandidatePromotionStatus.BLOCKED
    assert not rec_sub.gates_passed["oos_profit_factor"]
    results["pf_1_049999"] = {
        "input": "1.049999",
        "passed": rec_sub.gates_passed["oos_profit_factor"],
        "qualified": rec_sub.qualified,
        "status": rec_sub.status.value,
        "explanation": "Strict pre-quantization comparison profit_factor >= 1.05 rejects 1.049999.",
    }

    # Case 2: profit factor = 1.050000 (exact threshold)
    c_eq, q_eq = make_candidate_and_qualification(profit_factor=Decimal("1.050000"))
    rec_eq = evaluate_oos_promotion_gates(c_eq, q_eq)
    assert rec_eq.qualified, "Expected PF 1.050000 to pass qualification"
    assert rec_eq.status == CandidatePromotionStatus.PROMOTED
    assert rec_eq.gates_passed["oos_profit_factor"]
    results["pf_1_050000"] = {
        "input": "1.050000",
        "passed": rec_eq.gates_passed["oos_profit_factor"],
        "qualified": rec_eq.qualified,
        "status": rec_eq.status.value,
        "explanation": "Exact threshold 1.050000 passes profit_factor >= 1.05.",
    }

    # Case 3: profit factor = 1.050001 (above threshold)
    c_pos, q_pos = make_candidate_and_qualification(profit_factor=Decimal("1.050001"))
    rec_pos = evaluate_oos_promotion_gates(c_pos, q_pos)
    assert rec_pos.qualified, "Expected PF 1.050001 to pass qualification"
    assert rec_pos.status == CandidatePromotionStatus.PROMOTED
    assert rec_pos.gates_passed["oos_profit_factor"]
    results["pf_1_050001"] = {
        "input": "1.050001",
        "passed": rec_pos.gates_passed["oos_profit_factor"],
        "qualified": rec_pos.qualified,
        "status": rec_pos.status.value,
        "explanation": "Strictly above threshold passes profit_factor >= 1.05.",
    }

    return results


def test_oos_gate_trade_count_boundary() -> dict[str, Any]:
    """Test boundary condition: trade count = 4 vs 5."""
    results: dict[str, Any] = {}

    # Case 1: trade count = 4 (substandard)
    c_4, q_4 = make_candidate_and_qualification(trade_count=4)
    rec_4 = evaluate_oos_promotion_gates(c_4, q_4)
    assert not rec_4.qualified, "Expected trade count 4 to fail qualification"
    assert rec_4.status == CandidatePromotionStatus.BLOCKED
    assert not rec_4.gates_passed["oos_trade_count"]
    results["trades_4"] = {
        "input": 4,
        "passed": rec_4.gates_passed["oos_trade_count"],
        "qualified": rec_4.qualified,
        "status": rec_4.status.value,
        "explanation": "Trade count 4 < 5 fails minimum trade count gate and BLOCKS candidate.",
    }

    # Case 2: trade count = 5 (exact minimum)
    c_5, q_5 = make_candidate_and_qualification(trade_count=5)
    rec_5 = evaluate_oos_promotion_gates(c_5, q_5)
    assert rec_5.qualified, "Expected trade count 5 to pass qualification"
    assert rec_5.status == CandidatePromotionStatus.PROMOTED
    assert rec_5.gates_passed["oos_trade_count"]
    results["trades_5"] = {
        "input": 5,
        "passed": rec_5.gates_passed["oos_trade_count"],
        "qualified": rec_5.qualified,
        "status": rec_5.status.value,
        "explanation": "Trade count 5 >= 5 satisfies minimum gate and PROMOTES candidate.",
    }

    return results


# =====================================================================
# Stress Test Part 2: Real-Time Veto Interlocks & Signal Dispatch
# =====================================================================


def test_veto_hawkes_spectral_radius_boundary() -> dict[str, Any]:
    """Test real-time veto: Hawkes rho=1.00000 immediately suppresses signal dispatch."""
    results: dict[str, Any] = {}
    health = GatewayHealth(
        heartbeat_age_ms=10.0,
        latency_ms=10.0,
        clock_skew_ms=5.0,
        is_healthy=True,
    )

    # State machine setup
    sm = CandidateLifecycleStateMachine(
        "cand-btcusdt-001", "BTCUSDT", CandidatePromotionStatus.PROMOTED
    )
    assert sm.is_executable, "Initial promoted candidate should be executable"

    # 1. At rho = 1.00000: immediate supercritical cascade lockout
    risk = LivePaperRiskInterlock()
    hawkes_crit = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("1.00000"))
    v_crit = validate_realtime_veto_interlocks(
        risk, hawkes_crit, health, proposed_notional=Decimal("5.00"), symbol="BTCUSDT"
    )

    assert not v_crit.allowed
    assert v_crit.veto_code == InterlockCode.SUPERCRITICAL_CASCADE_LOCKOUT.value
    assert v_crit.veto_flags["hawkes_supercritical"]
    assert risk.circuit_state == CircuitState.SUPERCRITICAL_CASCADE_LOCKOUT

    # Apply veto to candidate state machine
    sm.veto(v_crit.reason)
    assert sm.status == CandidatePromotionStatus.VETOED
    assert not sm.is_executable, "Candidate in VETOED state must NOT be executable"

    results["hawkes_rho_1_00000"] = {
        "spectral_radius": "1.00000",
        "veto_allowed": v_crit.allowed,
        "veto_code": v_crit.veto_code,
        "circuit_state": str(risk.circuit_state),
        "sm_status": sm.status.value,
        "sm_is_executable": sm.is_executable,
        "signal_suppressed": not sm.is_executable,
        "explanation": (
            "Spectral radius rho=1.00000 trips SUPERCRITICAL_CASCADE_LOCKOUT "
            "and suppresses signal dispatch."
        ),
    }

    # 2. At rho = 0.99999: subcritical normal regime allows dispatch
    sm.clear_veto("Subcritical recovery")
    assert sm.status == CandidatePromotionStatus.PROMOTED
    assert sm.is_executable

    risk_sub = LivePaperRiskInterlock()
    hawkes_sub = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("0.99999"))
    v_sub = validate_realtime_veto_interlocks(
        risk_sub, hawkes_sub, health, proposed_notional=Decimal("5.00"), symbol="BTCUSDT"
    )
    assert v_sub.allowed
    assert v_sub.veto_code == InterlockCode.NORMAL.value
    assert not v_sub.veto_flags["hawkes_supercritical"]

    results["hawkes_rho_0_99999"] = {
        "spectral_radius": "0.99999",
        "veto_allowed": v_sub.allowed,
        "veto_code": v_sub.veto_code,
        "circuit_state": str(risk_sub.circuit_state),
        "sm_status": sm.status.value,
        "sm_is_executable": sm.is_executable,
        "signal_suppressed": not sm.is_executable,
        "explanation": "Spectral radius rho=0.99999 < 1.00 allows signal dispatch.",
    }

    return results


def test_veto_heartbeat_age_boundary() -> dict[str, Any]:
    """Test real-time veto: gateway heartbeat age 500.001 ms blocks signal dispatch."""
    results: dict[str, Any] = {}
    hawkes = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("0.20"))

    # 1. At heartbeat age = 500.001 ms: strictly exceeds 500.0 ms tolerance
    risk_stale = LivePaperRiskInterlock()
    health_stale = GatewayHealth(
        heartbeat_age_ms=500.001,
        latency_ms=10.0,
        clock_skew_ms=5.0,
        is_healthy=True,
    )
    v_stale = validate_realtime_veto_interlocks(
        risk_stale, hawkes, health_stale, proposed_notional=Decimal("5.00"), symbol="BTCUSDT"
    )

    assert not v_stale.allowed
    assert v_stale.veto_code == InterlockCode.GATEWAY_HEARTBEAT_STALE.value
    assert v_stale.veto_flags["gateway_heartbeat_stale"]

    sm = CandidateLifecycleStateMachine(
        "cand-btcusdt-001", "BTCUSDT", CandidatePromotionStatus.PROMOTED
    )
    sm.veto(v_stale.reason)
    assert not sm.is_executable, "Stale heartbeat must block signal dispatch"

    results["heartbeat_500_001ms"] = {
        "heartbeat_age_ms": 500.001,
        "veto_allowed": v_stale.allowed,
        "veto_code": v_stale.veto_code,
        "sm_is_executable": sm.is_executable,
        "signal_blocked": not v_stale.allowed,
        "explanation": (
            "Heartbeat age 500.001ms > 500.0ms tolerance triggers GATEWAY_HEARTBEAT_STALE veto."
        ),
    }

    # 2. At heartbeat age = 500.000 ms: exactly at boundary
    risk_fresh = LivePaperRiskInterlock()
    health_fresh = GatewayHealth(
        heartbeat_age_ms=500.000,
        latency_ms=10.0,
        clock_skew_ms=5.0,
        is_healthy=True,
    )
    v_fresh = validate_realtime_veto_interlocks(
        risk_fresh, hawkes, health_fresh, proposed_notional=Decimal("5.00"), symbol="BTCUSDT"
    )
    assert v_fresh.allowed
    assert v_fresh.veto_code == InterlockCode.NORMAL.value

    results["heartbeat_500_000ms"] = {
        "heartbeat_age_ms": 500.000,
        "veto_allowed": v_fresh.allowed,
        "veto_code": v_fresh.veto_code,
        "signal_blocked": not v_fresh.allowed,
        "explanation": "Heartbeat age 500.000ms <= 500.0ms is within tolerance and clears veto.",
    }

    return results


def test_veto_margin_exposure_boundary() -> dict[str, Any]:
    """Test real-time veto: margin exposure 60.0001 USDT blocks signal dispatch."""
    results: dict[str, Any] = {}
    hawkes = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("0.20"))
    health = GatewayHealth(
        heartbeat_age_ms=10.0,
        latency_ms=10.0,
        clock_skew_ms=5.0,
        is_healthy=True,
    )

    # 1. Total projected exposure = 60.0001 USDT (55.0000 existing + 5.0001 proposed)
    risk_over = LivePaperRiskInterlock()
    risk_over.update_active_exposure("GLOBAL", Decimal("55.0000"))
    v_over = validate_realtime_veto_interlocks(
        risk_over, hawkes, health, proposed_notional=Decimal("5.0001"), symbol="BTCUSDT"
    )

    assert not v_over.allowed
    assert v_over.veto_code == InterlockCode.AGGREGATE_EXPOSURE_CAP_EXCEEDED.value
    assert v_over.veto_flags["margin_headroom_breach"]

    results["margin_exposure_60_0001_usdt"] = {
        "active_exposure": "55.0000",
        "proposed_notional": "5.0001",
        "projected_total": "60.0001",
        "aggregate_cap": "60.00",
        "veto_allowed": v_over.allowed,
        "veto_code": v_over.veto_code,
        "signal_blocked": not v_over.allowed,
        "explanation": (
            "Projected total exposure 60.0001 USDT > 60.00 USDT cap "
            "triggers AGGREGATE_EXPOSURE_CAP_EXCEEDED."
        ),
    }

    # 2. Total projected exposure = 60.0000 USDT (55.0000 existing + 5.0000 proposed)
    risk_eq = LivePaperRiskInterlock()
    risk_eq.update_active_exposure("GLOBAL", Decimal("55.0000"))
    v_eq = validate_realtime_veto_interlocks(
        risk_eq, hawkes, health, proposed_notional=Decimal("5.0000"), symbol="BTCUSDT"
    )
    assert v_eq.allowed
    assert v_eq.veto_code == InterlockCode.NORMAL.value

    results["margin_exposure_60_0000_usdt"] = {
        "active_exposure": "55.0000",
        "proposed_notional": "5.0000",
        "projected_total": "60.0000",
        "aggregate_cap": "60.00",
        "veto_allowed": v_eq.allowed,
        "veto_code": v_eq.veto_code,
        "signal_blocked": not v_eq.allowed,
        "explanation": "Projected total exposure 60.0000 USDT <= 60.00 USDT cap clears veto.",
    }

    return results


def test_veto_cash_reserve_boundary() -> dict[str, Any]:
    """Test real-time veto: cash reserve 39.999% blocks signal dispatch."""
    results: dict[str, Any] = {}
    hawkes = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("0.20"))
    health = GatewayHealth(
        heartbeat_age_ms=10.0,
        latency_ms=10.0,
        clock_skew_ms=5.0,
        is_healthy=True,
    )

    # Setup: starting equity 100.00 USDT, cash = 100.00 USDT.
    risk_reserve_low = LivePaperRiskInterlock(
        starting_equity=Decimal("100.00"),
        aggregate_exposure_cap=Decimal("100.00"),
        per_asset_margin_cap=Decimal("100.00"),
    )
    # Proposed notional 60.001 USDT -> reserve = (100.00 - 60.001) / 100.00 = 39.999% < 40.00%
    v_low = validate_realtime_veto_interlocks(
        risk_reserve_low, hawkes, health, proposed_notional=Decimal("60.001"), symbol="BTCUSDT"
    )

    assert not v_low.allowed
    assert v_low.veto_code == InterlockCode.MARGIN_HEADROOM_BREACH.value
    assert v_low.veto_flags["margin_headroom_breach"]

    results["cash_reserve_39_999_pct"] = {
        "starting_equity": "100.00",
        "proposed_notional": "60.001",
        "projected_reserve_pct": "39.999%",
        "min_reserve_required": "40.000%",
        "veto_allowed": v_low.allowed,
        "veto_code": v_low.veto_code,
        "signal_blocked": not v_low.allowed,
        "explanation": "Projected reserve 39.999% < 40.0% buffer triggers MARGIN_HEADROOM_BREACH.",
    }

    # Exact 40.000% reserve: proposed notional 60.000 USDT -> reserve 40.000%
    risk_reserve_ok = LivePaperRiskInterlock(
        starting_equity=Decimal("100.00"),
        aggregate_exposure_cap=Decimal("100.00"),
        per_asset_margin_cap=Decimal("100.00"),
    )
    v_ok = validate_realtime_veto_interlocks(
        risk_reserve_ok, hawkes, health, proposed_notional=Decimal("60.000"), symbol="BTCUSDT"
    )
    assert v_ok.allowed
    assert v_ok.veto_code == InterlockCode.NORMAL.value

    results["cash_reserve_40_000_pct"] = {
        "starting_equity": "100.00",
        "proposed_notional": "60.000",
        "projected_reserve_pct": "40.000%",
        "min_reserve_required": "40.000%",
        "veto_allowed": v_ok.allowed,
        "veto_code": v_ok.veto_code,
        "signal_blocked": not v_ok.allowed,
        "explanation": (
            "Projected reserve 40.000% >= 40.0% buffer satisfies margin headroom and clears veto."
        ),
    }

    return results


def test_veto_loss_budget_emergency_flattening() -> dict[str, Any]:
    """Test real-time veto: cumulative loss 7.0000 USDT triggers micro-chunk flattening."""
    results: dict[str, Any] = {}
    hawkes = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("0.20"))
    health = GatewayHealth(
        heartbeat_age_ms=10.0,
        latency_ms=10.0,
        clock_skew_ms=5.0,
        is_healthy=True,
    )

    risk = LivePaperRiskInterlock()
    risk.cumulative_loss = Decimal("7.0000")

    # Multi-asset portfolio with significant open positions across BTC, ETH, and SOL
    open_positions = {
        "BTCUSDT": Decimal("0.0005"),  # 0.0005 * 60,000 = 30.00 USDT
        "ETHUSDT": Decimal("0.0100"),  # 0.0100 * 3,000 = 30.00 USDT
        "SOLUSDT": Decimal("0.2000"),  # 0.2000 * 150 = 30.00 USDT
    }
    prices = {
        "BTCUSDT": Decimal("60000.00"),
        "ETHUSDT": Decimal("3000.00"),
        "SOLUSDT": Decimal("150.00"),
    }

    v_loss = validate_realtime_veto_interlocks(
        risk,
        hawkes,
        health,
        proposed_notional=Decimal("5.00"),
        symbol="BTCUSDT",
        open_positions=open_positions,
        current_prices=prices,
    )

    assert not v_loss.allowed
    assert v_loss.veto_code == InterlockCode.INTRA_PHASE_LOSS_LOCKOUT.value
    assert v_loss.veto_flags["intra_phase_loss_breach"]
    assert v_loss.emergency_flattening_required
    assert risk.circuit_state == CircuitState.INTRA_PHASE_LOSS_LOCKOUT

    # Verify closing orders
    closing_orders = v_loss.closing_orders
    assert len(closing_orders) > 0, "Emergency flattening must produce closing orders"

    # Verify that every closing order obeys HARD_MICRO_NOTIONAL_CAP_USDT (<= 5.00 USDT)
    oversized_orders = []
    total_flattening_notional = Decimal("0")
    for i, order in enumerate(closing_orders):
        notional = getattr(order, "notional_usdt", None) or Decimal(
            str(order.get("notional_usdt", "0"))
        )
        total_flattening_notional += notional
        if notional > HARD_MICRO_NOTIONAL_CAP_USDT:
            oversized_orders.append((i, notional))

    assert len(oversized_orders) == 0, f"Found {len(oversized_orders)} orders exceeding 5.00 cap"

    results["loss_budget_7_0000_usdt"] = {
        "cumulative_loss": "7.0000",
        "loss_ceiling": "7.00",
        "veto_allowed": v_loss.allowed,
        "veto_code": v_loss.veto_code,
        "circuit_state": str(risk.circuit_state),
        "emergency_flattening_required": v_loss.emergency_flattening_required,
        "closing_orders_count": len(closing_orders),
        "oversized_orders_count": len(oversized_orders),
        "total_flattening_notional_usdt": str(total_flattening_notional),
        "all_micro_chunks_under_5_usdt": len(oversized_orders) == 0,
        "explanation": (
            f"Cumulative loss {risk.cumulative_loss} reached budget ceiling 7.00 USDT, "
            f"tripping INTRA_PHASE_LOSS_LOCKOUT and generating {len(closing_orders)} micro-chunks "
            f"all strictly <= 5.00 USDT."
        ),
    }

    return results


# =====================================================================
# Main Execution Runner
# =====================================================================


def run_all_stress_tests() -> dict[str, Any]:
    """Execute all boundary stress tests and aggregate findings."""
    logger.info("Starting Phase 295 Boundary Condition & Veto Interlock Stress Tests...")

    report: dict[str, Any] = {
        "suite": "Phase 295 Adversarial Boundary Stress Suite",
        "timestamp_utc": "2026-09-21T10:25:00Z",
        "part_1_oos_promotion_gates": {},
        "part_2_realtime_veto_interlocks": {},
        "overall_status": "COMPLETED",
    }

    logger.info("--- [1/5] Testing Return Boundary (-0.0000001 vs 0.0) ---")
    ret_res = test_oos_gate_return_boundary()
    report["part_1_oos_promotion_gates"]["return_boundary"] = ret_res

    logger.info("--- [2/5] Testing Drawdown Boundary (15.00001% vs 15.00000%) ---")
    dd_res = test_oos_gate_drawdown_boundary()
    report["part_1_oos_promotion_gates"]["drawdown_boundary"] = dd_res

    logger.info("--- [3/5] Testing Profit Factor Boundary (1.049999 vs 1.050000) ---")
    pf_res = test_oos_gate_profit_factor_boundary()
    report["part_1_oos_promotion_gates"]["profit_factor_boundary"] = pf_res

    logger.info("--- [4/5] Testing Trade Count Boundary (4 vs 5) ---")
    tc_res = test_oos_gate_trade_count_boundary()
    report["part_1_oos_promotion_gates"]["trade_count_boundary"] = tc_res

    logger.info("--- [5/5] Testing Real-Time Veto Interlocks ---")
    report["part_2_realtime_veto_interlocks"]["hawkes_supercritical"] = (
        test_veto_hawkes_spectral_radius_boundary()
    )
    report["part_2_realtime_veto_interlocks"]["heartbeat_freshness"] = (
        test_veto_heartbeat_age_boundary()
    )
    report["part_2_realtime_veto_interlocks"]["margin_exposure"] = (
        test_veto_margin_exposure_boundary()
    )
    report["part_2_realtime_veto_interlocks"]["cash_reserve"] = test_veto_cash_reserve_boundary()
    report["part_2_realtime_veto_interlocks"]["loss_budget_flattening"] = (
        test_veto_loss_budget_emergency_flattening()
    )

    logger.info("All boundary condition stress tests completed successfully!")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 295 Boundary Stress Test Harness")
    parser.add_argument("--json", action="store_true", help="Output raw JSON report")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    report = run_all_stress_tests()

    if args.json or not args.verbose:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
