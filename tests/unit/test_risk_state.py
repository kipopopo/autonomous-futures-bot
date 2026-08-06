from __future__ import annotations

from decimal import Decimal

import pytest

from autonomous_futures.domain.contracts import PositionState
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.domain.risk import (
    PositionBook,
    ResumeEvidence,
    RiskPolicy,
    RiskSizingRequest,
    RuntimeEvent,
    RuntimeState,
    evaluate_sizing,
    transition_runtime_state,
)


def position(symbol: str) -> PositionState:
    return PositionState(symbol=symbol, quantity=Decimal("0.001"), side="LONG")


def test_position_book_rejects_duplicate_symbol_and_second_global_position() -> None:
    book = PositionBook(max_positions=1)
    book.open(position("BTCUSDT"))

    with pytest.raises(DomainViolation, match="active position"):
        book.open(position("BTCUSDT"))
    with pytest.raises(DomainViolation, match="global position limit"):
        book.open(position("ETHUSDT"))


def test_runtime_state_only_moves_down_automatically() -> None:
    assert transition_runtime_state(RuntimeState.NORMAL, RuntimeEvent.DAILY_LOSS_STOP) == (
        RuntimeState.THROTTLED
    )
    assert transition_runtime_state(RuntimeState.THROTTLED, RuntimeEvent.DRAWDOWN_HALT) == (
        RuntimeState.HALTED
    )
    assert transition_runtime_state(RuntimeState.HALTED, RuntimeEvent.CRITICAL_MISMATCH) == (
        RuntimeState.EMERGENCY_FLAT
    )

    with pytest.raises(DomainViolation, match="automatic resume"):
        transition_runtime_state(RuntimeState.HALTED, RuntimeEvent.HEALTHY)


def test_guarded_resume_requires_reconciled_and_healthy_evidence() -> None:
    evidence = ResumeEvidence(
        reconciled=True,
        incident_resolved=True,
        data_fresh=True,
        risk_healthy=True,
        operator_approved=True,
    )
    assert evidence.can_resume is True

    unsafe = evidence.model_copy(update={"reconciled": False})
    assert unsafe.can_resume is False


def test_risk_policy_keeps_ordered_drawdown_and_leverage_limits() -> None:
    policy = RiskPolicy()

    assert policy.max_selected_leverage == Decimal("2")
    assert policy.drawdown_throttle == Decimal("0.05")
    assert policy.drawdown_halt == Decimal("0.08")
    assert policy.catastrophic_drawdown == Decimal("0.10")
    assert policy.drawdown_throttle < policy.drawdown_halt < policy.catastrophic_drawdown

    with pytest.raises(ValueError, match="drawdown"):
        RiskPolicy(drawdown_halt=Decimal("0.04"))


def test_sizing_rejects_minimum_notional_that_exceeds_risk_budget() -> None:
    request = RiskSizingRequest(
        equity_usd=Decimal("100"),
        risk_fraction=Decimal("0.005"),
        stop_distance_fraction=Decimal("0.01"),
        estimated_round_trip_cost_usd=Decimal("0"),
        minimum_notional_usd=Decimal("100"),
    )

    result = evaluate_sizing(request, RiskPolicy())

    assert result.decision == "REJECT"
    assert "MINIMUM_NOTIONAL_BREACHES_RISK" in result.reason_codes


def test_sizing_rejects_risk_fraction_above_absolute_cap() -> None:
    request = RiskSizingRequest(
        equity_usd=Decimal("100"),
        risk_fraction=Decimal("0.02"),
        stop_distance_fraction=Decimal("0.01"),
        estimated_round_trip_cost_usd=Decimal("0"),
        minimum_notional_usd=Decimal("1"),
    )

    result = evaluate_sizing(request, RiskPolicy())

    assert result.decision == "REJECT"
    assert "RISK_FRACTION_ABOVE_CAP" in result.reason_codes
