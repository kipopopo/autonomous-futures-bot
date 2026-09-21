"""Targeted Boundary Condition & Adversarial Stress Tests for Phase 295.

Empirical Challenger Test Suite:
1. evaluate_oos_promotion_gates boundary precision:
   - Return: -0.0000001 (fails), 0.0000000 (passes), +0.0000001 (passes)
   - Drawdown: 15.00000% (passes), 15.00001% (passes), 15.00051% (fails), 15.00100% (fails)
   - Profit Factor: 1.049999 (fails), 1.050000 (passes), 1.050001 (passes)
   - Trade Count: 4 (fails), 5 (passes)
2. Real-Time Veto Interlocks:
   - Hawkes spectral radius rho=1.00000 suppresses signal dispatch
   - Gateway heartbeat age 500.001 ms blocks signal dispatch
   - Margin exposure 60.0001 USDT blocks signal dispatch
   - Cash reserve 39.999% blocks signal dispatch
   - Loss budget 7.0000 USDT triggers emergency micro-chunk flattening (<= 5.00 USDT)
"""

from __future__ import annotations

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


def make_qual_candidate(
    candidate_id: str = "cand-test-bound",
    symbol: str = "BTCUSDT",
    avg_return: Decimal = Decimal("2.0"),
    drawdown: Decimal = Decimal("10.0"),
    profit_factor: Decimal = Decimal("1.5"),
    trades: int = 10,
    windows: int = 3,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cand = {"candidate_id": candidate_id, "strategy": {"universe": {"symbols": [symbol]}}}
    qual = {
        "candidate_id": candidate_id,
        "decision": "qualified",
        "windows_evaluated": windows,
        "metrics": [
            {"metric_id": "oos_average_return_pct", "value": str(avg_return)},
            {"metric_id": "oos_worst_drawdown_pct", "value": str(drawdown)},
            {"metric_id": "oos_profit_factor", "value": str(profit_factor)},
            {"metric_id": "oos_total_trades", "value": str(trades)},
            {"metric_id": "oos_window_count", "value": str(windows)},
        ],
    }
    return cand, qual


class TestOOSPromotionGateBoundaries:
    """Stress tests for evaluate_oos_promotion_gates boundary precision."""

    def test_return_boundary_negative(self) -> None:
        c, q = make_qual_candidate(avg_return=Decimal("-0.0000001"))
        rec = evaluate_oos_promotion_gates(c, q)
        assert not rec.qualified
        assert rec.status == CandidatePromotionStatus.BLOCKED
        assert not rec.gates_passed["oos_average_return"]

    def test_return_boundary_zero_and_positive(self) -> None:
        c_zero, q_zero = make_qual_candidate(avg_return=Decimal("0.0000000"))
        rec_zero = evaluate_oos_promotion_gates(c_zero, q_zero)
        assert rec_zero.qualified
        assert rec_zero.status == CandidatePromotionStatus.PROMOTED
        assert rec_zero.gates_passed["oos_average_return"]

        c_pos, q_pos = make_qual_candidate(avg_return=Decimal("0.0000001"))
        rec_pos = evaluate_oos_promotion_gates(c_pos, q_pos)
        assert rec_pos.qualified
        assert rec_pos.status == CandidatePromotionStatus.PROMOTED

    def test_drawdown_boundary_precision(self) -> None:
        # 15.00000% passes
        c0, q0 = make_qual_candidate(drawdown=Decimal("15.00000"))
        rec0 = evaluate_oos_promotion_gates(c0, q0)
        assert rec0.qualified
        assert rec0.gates_passed["oos_worst_drawdown"]
        assert rec0.oos_worst_drawdown_pct == Decimal("15.000")

        # 15.00001% quantizes to 15.000% under 3-dec quantization, passes <= 15.00%
        c1, q1 = make_qual_candidate(drawdown=Decimal("15.00001"))
        rec1 = evaluate_oos_promotion_gates(c1, q1)
        assert rec1.qualified
        assert rec1.gates_passed["oos_worst_drawdown"]
        assert rec1.oos_worst_drawdown_pct == Decimal("15.000")

        # 15.00051% rounds to 15.001%, fails > 15.00%
        c2, q2 = make_qual_candidate(drawdown=Decimal("15.00051"))
        rec2 = evaluate_oos_promotion_gates(c2, q2)
        assert not rec2.qualified
        assert not rec2.gates_passed["oos_worst_drawdown"]
        assert rec2.status == CandidatePromotionStatus.BLOCKED

        # 15.00100% fails
        c3, q3 = make_qual_candidate(drawdown=Decimal("15.00100"))
        rec3 = evaluate_oos_promotion_gates(c3, q3)
        assert not rec3.qualified
        assert not rec3.gates_passed["oos_worst_drawdown"]

    def test_profit_factor_boundary(self) -> None:
        # 1.049999 fails
        c_sub, q_sub = make_qual_candidate(profit_factor=Decimal("1.049999"))
        rec_sub = evaluate_oos_promotion_gates(c_sub, q_sub)
        assert not rec_sub.qualified
        assert rec_sub.status == CandidatePromotionStatus.BLOCKED
        assert not rec_sub.gates_passed["oos_profit_factor"]

        # 1.050000 passes
        c_eq, q_eq = make_qual_candidate(profit_factor=Decimal("1.050000"))
        rec_eq = evaluate_oos_promotion_gates(c_eq, q_eq)
        assert rec_eq.qualified
        assert rec_eq.status == CandidatePromotionStatus.PROMOTED
        assert rec_eq.gates_passed["oos_profit_factor"]

        # 1.050001 passes
        c_pos, q_pos = make_qual_candidate(profit_factor=Decimal("1.050001"))
        rec_pos = evaluate_oos_promotion_gates(c_pos, q_pos)
        assert rec_pos.qualified
        assert rec_pos.status == CandidatePromotionStatus.PROMOTED

    def test_trade_count_boundary(self) -> None:
        # 4 trades fails
        c4, q4 = make_qual_candidate(trades=4)
        rec4 = evaluate_oos_promotion_gates(c4, q4)
        assert not rec4.qualified
        assert rec4.status == CandidatePromotionStatus.BLOCKED
        assert not rec4.gates_passed["oos_trade_count"]

        # 5 trades passes
        c5, q5 = make_qual_candidate(trades=5)
        rec5 = evaluate_oos_promotion_gates(c5, q5)
        assert rec5.qualified
        assert rec5.status == CandidatePromotionStatus.PROMOTED
        assert rec5.gates_passed["oos_trade_count"]


class TestRealTimeVetoInterlockBoundaries:
    """Stress tests for real-time fail-closed veto interlocks and signal dispatch suppression."""

    def test_hawkes_spectral_radius_veto_suppression(self) -> None:
        sm = CandidateLifecycleStateMachine(
            "cand-btcusdt-001", "BTCUSDT", CandidatePromotionStatus.PROMOTED
        )
        assert sm.is_executable

        health = GatewayHealth(
            heartbeat_age_ms=10.0, latency_ms=10.0, clock_skew_ms=5.0, is_healthy=True
        )
        risk = LivePaperRiskInterlock()
        hawkes_crit = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("1.00000"))

        decision = validate_realtime_veto_interlocks(
            risk, hawkes_crit, health, proposed_notional=Decimal("5.00"), symbol="BTCUSDT"
        )
        assert not decision.allowed
        assert decision.veto_code == InterlockCode.SUPERCRITICAL_CASCADE_LOCKOUT.value
        assert decision.veto_flags["hawkes_supercritical"]
        assert risk.circuit_state == CircuitState.SUPERCRITICAL_CASCADE_LOCKOUT

        sm.veto(decision.reason)
        assert sm.status == CandidatePromotionStatus.VETOED
        assert not sm.is_executable, "Signal dispatch must be suppressed in VETOED state"

        # Subcritical recovery (rho = 0.99999)
        risk_sub = LivePaperRiskInterlock()
        hawkes_sub = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("0.99999"))
        decision_sub = validate_realtime_veto_interlocks(
            risk_sub, hawkes_sub, health, proposed_notional=Decimal("5.00"), symbol="BTCUSDT"
        )
        assert decision_sub.allowed
        assert decision_sub.veto_code == InterlockCode.NORMAL.value

        sm.clear_veto("Hawkes normalized")
        assert sm.is_executable

    def test_heartbeat_age_500_001_ms_blocks_signal(self) -> None:
        hawkes = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("0.20"))
        risk = LivePaperRiskInterlock()
        health_stale = GatewayHealth(
            heartbeat_age_ms=500.001, latency_ms=10.0, clock_skew_ms=5.0, is_healthy=True
        )

        v_stale = validate_realtime_veto_interlocks(
            risk, hawkes, health_stale, proposed_notional=Decimal("5.00"), symbol="BTCUSDT"
        )
        assert not v_stale.allowed
        assert v_stale.veto_code == InterlockCode.GATEWAY_HEARTBEAT_STALE.value
        assert v_stale.veto_flags["gateway_heartbeat_stale"]

        # Exactly 500.000 ms clears
        risk_ok = LivePaperRiskInterlock()
        health_ok = GatewayHealth(
            heartbeat_age_ms=500.000, latency_ms=10.0, clock_skew_ms=5.0, is_healthy=True
        )
        v_ok = validate_realtime_veto_interlocks(
            risk_ok, hawkes, health_ok, proposed_notional=Decimal("5.00"), symbol="BTCUSDT"
        )
        assert v_ok.allowed

    def test_margin_exposure_60_0001_usdt_blocks_signal(self) -> None:
        hawkes = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("0.20"))
        health = GatewayHealth(
            heartbeat_age_ms=10.0, latency_ms=10.0, clock_skew_ms=5.0, is_healthy=True
        )

        risk = LivePaperRiskInterlock()
        risk.update_active_exposure("GLOBAL", Decimal("55.0000"))

        # 55.0000 + 5.0001 = 60.0001 USDT > 60.00 USDT
        v_over = validate_realtime_veto_interlocks(
            risk, hawkes, health, proposed_notional=Decimal("5.0001"), symbol="BTCUSDT"
        )
        assert not v_over.allowed
        assert v_over.veto_code == InterlockCode.AGGREGATE_EXPOSURE_CAP_EXCEEDED.value
        assert v_over.veto_flags["margin_headroom_breach"]

        # 55.0000 + 5.0000 = 60.0000 USDT <= 60.00 USDT
        risk_eq = LivePaperRiskInterlock()
        risk_eq.update_active_exposure("GLOBAL", Decimal("55.0000"))
        v_eq = validate_realtime_veto_interlocks(
            risk_eq, hawkes, health, proposed_notional=Decimal("5.0000"), symbol="BTCUSDT"
        )
        assert v_eq.allowed

    def test_cash_reserve_39_999_pct_blocks_signal(self) -> None:
        hawkes = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("0.20"))
        health = GatewayHealth(
            heartbeat_age_ms=10.0, latency_ms=10.0, clock_skew_ms=5.0, is_healthy=True
        )

        risk = LivePaperRiskInterlock(
            starting_equity=Decimal("100.00"),
            aggregate_exposure_cap=Decimal("100.00"),
            per_asset_margin_cap=Decimal("100.00"),
        )
        # Proposed 60.001 USDT -> reserve = 39.999% < 40.0%
        v_low = validate_realtime_veto_interlocks(
            risk, hawkes, health, proposed_notional=Decimal("60.001"), symbol="BTCUSDT"
        )
        assert not v_low.allowed
        assert v_low.veto_code == InterlockCode.MARGIN_HEADROOM_BREACH.value

        # Proposed 60.000 USDT -> reserve = 40.000% >= 40.0%
        risk_ok = LivePaperRiskInterlock(
            starting_equity=Decimal("100.00"),
            aggregate_exposure_cap=Decimal("100.00"),
            per_asset_margin_cap=Decimal("100.00"),
        )
        v_ok = validate_realtime_veto_interlocks(
            risk_ok, hawkes, health, proposed_notional=Decimal("60.000"), symbol="BTCUSDT"
        )
        assert v_ok.allowed

    def test_loss_budget_7_0000_usdt_triggers_emergency_flattening(self) -> None:
        hawkes = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("0.20"))
        health = GatewayHealth(
            heartbeat_age_ms=10.0, latency_ms=10.0, clock_skew_ms=5.0, is_healthy=True
        )

        risk = LivePaperRiskInterlock()
        risk.cumulative_loss = Decimal("7.0000")

        positions = {
            "BTCUSDT": Decimal("0.0005"),
            "ETHUSDT": Decimal("0.0100"),
            "SOLUSDT": Decimal("0.2000"),
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
            open_positions=positions,
            current_prices=prices,
        )

        assert not v_loss.allowed
        assert v_loss.veto_code == InterlockCode.INTRA_PHASE_LOSS_LOCKOUT.value
        assert v_loss.emergency_flattening_required
        assert risk.circuit_state == CircuitState.INTRA_PHASE_LOSS_LOCKOUT
        assert len(v_loss.closing_orders) > 0

        # All closing orders must obey <= 5.00 USDT cap
        for order in v_loss.closing_orders:
            notional = getattr(order, "notional_usdt", None) or Decimal(
                str(order.get("notional_usdt", "0"))
            )
            assert notional <= HARD_MICRO_NOTIONAL_CAP_USDT
