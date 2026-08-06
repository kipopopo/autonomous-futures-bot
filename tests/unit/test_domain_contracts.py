from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from autonomous_futures.domain.contracts import (
    OrderAction,
    OrderIntent,
    RiskDecision,
    StrategySpec,
    parse_strategy_spec,
)


def valid_intent_payload() -> dict[str, object]:
    signal_time = datetime(2026, 8, 6, 1, 0, tzinfo=UTC)
    return {
        "intent_id": uuid4(),
        "candidate_manifest_hash": "sha256:candidate",
        "symbol": "BTCUSDT",
        "action": OrderAction.OPEN_LONG,
        "signal_time": signal_time,
        "valid_until": signal_time + timedelta(minutes=5),
        "reference_price": Decimal("100.00"),
        "requested_stop_price": Decimal("98.00"),
        "requested_take_profit": Decimal("104.00"),
        "reason_codes": ("BREAKOUT", "REGIME_DIRECTIONAL"),
        "feature_snapshot_hash": "sha256:features",
    }


def test_order_intent_is_utc_and_cannot_carry_final_size_or_leverage() -> None:
    intent = OrderIntent.model_validate(valid_intent_payload())

    assert intent.signal_time.tzinfo is UTC
    assert intent.valid_until > intent.signal_time
    assert intent.requested_quantity is None
    assert intent.requested_leverage is None

    invalid = valid_intent_payload()
    invalid["requested_quantity"] = Decimal("0.01")
    with pytest.raises(ValidationError, match="requested_quantity"):
        OrderIntent.model_validate(invalid)

    naive = valid_intent_payload()
    naive["signal_time"] = datetime(2026, 8, 6, 1, 0)
    with pytest.raises(ValidationError, match="timezone-aware"):
        OrderIntent.model_validate(naive)


def test_risk_decision_uses_decimal_accounting_and_forbids_float_inputs() -> None:
    decision = RiskDecision(
        decision="APPROVE",
        intent_id=uuid4(),
        normalized_quantity=Decimal("0.001"),
        selected_leverage=Decimal("2"),
        estimated_loss_at_stop_usd=Decimal("0.75"),
        estimated_round_trip_cost_usd=Decimal("0.12"),
        stop_required=True,
        reduce_only_exit=True,
        policy_version="risk-v1",
        reason_codes=("WITHIN_TRADE_RISK",),
        input_state_hash="sha256:state",
    )

    assert decision.estimated_loss_at_stop_usd == Decimal("0.75")
    assert decision.selected_leverage == Decimal("2")

    invalid = decision.model_dump()
    invalid["estimated_loss_at_stop_usd"] = 0.75
    with pytest.raises(ValidationError):
        RiskDecision.model_validate(invalid)


def valid_strategy_payload() -> dict[str, object]:
    return {
        "dsl_version": 1,
        "strategy_id": str(uuid4()),
        "family": "regime_gated_breakout",
        "universe": {
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "timeframe": "5m",
            "regime_context_timeframe": "15m",
        },
        "features": [
            {"name": "donchian_high", "lookback": 20, "shift": 1},
            {"name": "adx", "lookback": 14, "shift": 1},
        ],
        "entry": {
            "long": "close > donchian_high AND adx >= 25",
            "short": "close < donchian_low AND adx >= 25",
        },
        "exit": {
            "long": "close < donchian_low",
            "short": "close > donchian_high",
        },
        "vetoes": ["stale_data", "spread_above_limit"],
    }


def test_strategy_spec_accepts_only_causal_bounded_dsl() -> None:
    spec = parse_strategy_spec(valid_strategy_payload())

    assert isinstance(spec, StrategySpec)
    assert spec.universe.timeframe == "5m"
    assert spec.universe.regime_context_timeframe == "15m"
    assert all(feature.shift >= 1 for feature in spec.features)

    unknown_feature = valid_strategy_payload()
    unknown_feature["features"] = [{"name": "future_close", "lookback": 1, "shift": 0}]
    with pytest.raises(ValidationError, match="feature"):
        parse_strategy_spec(unknown_feature)

    executable_expression = valid_strategy_payload()
    executable_expression["entry"] = {"long": "__import__('os').system('whoami')", "short": "0"}
    with pytest.raises(ValidationError, match="expression"):
        parse_strategy_spec(executable_expression)


def test_strategy_spec_cannot_grant_execution_authority() -> None:
    payload = valid_strategy_payload()
    payload["leverage"] = 10
    with pytest.raises(ValidationError, match="leverage"):
        parse_strategy_spec(payload)
