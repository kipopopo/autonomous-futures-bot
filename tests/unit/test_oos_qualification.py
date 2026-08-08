from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.performance_metrics import TradePerformanceMetrics
from autonomous_futures.research.qualification_artifacts import (
    WalkForwardQualificationPolicy,
    build_walk_forward_qualification_artifact,
)
from autonomous_futures.research.walk_forward import (
    WalkForwardWindowMetrics,
    aggregate_walk_forward_metrics,
)

START = datetime(2026, 8, 7, 12, tzinfo=UTC)


def _candidate(*, symbols: tuple[str, ...] = ("BTCUSDT",)):
    strategy = StrategySpec(
        dsl_version=1,
        strategy_id="cand-strict-oos-001",
        family="experimental",
        universe=StrategyUniverse(symbols=symbols, timeframe="5m", regime_context_timeframe="15m"),
        features=(FeatureRef(name="returns", lookback=20, shift=1),),
        entry=EntryExit(long="ema_slope > 0", short="ema_slope < 0"),
        exit=EntryExit(long="rsi > 70", short="rsi < 30"),
        vetoes=("regime_trend == 0",),
    )
    return build_creator_candidate_artifact(
        candidate_id="cand-strict-oos-001",
        strategy=strategy,
        bundle_hash="a" * 64,
        dataset_registry_hash="b" * 64,
        creator_run_id="creator-run-strict-oos",
        research_seed=31,
        created_at=START,
    )


def _window(
    window_id: str,
    start_offset: int,
    net_pnl: str,
    *,
    symbol: str = "BTCUSDT",
    drawdown: str = "2",
) -> WalkForwardWindowMetrics:
    window_start = START + timedelta(minutes=5 * start_offset)
    pnl = Decimal(net_pnl)
    gross_profit = max(pnl, Decimal("0"))
    gross_loss = max(-pnl, Decimal("0"))
    return WalkForwardWindowMetrics(
        window_id=window_id,
        symbol=symbol,
        split="oos",
        window_start=window_start,
        window_end=window_start + timedelta(minutes=10),
        metrics=TradePerformanceMetrics(
            symbol=symbol,
            starting_equity=Decimal("100"),
            final_equity=Decimal("100") + pnl,
            trade_count=1,
            winning_trades=int(pnl > 0),
            losing_trades=int(pnl < 0),
            breakeven_trades=int(pnl == 0),
            win_rate=Decimal("1") if pnl > 0 else Decimal("0"),
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            net_pnl=pnl,
            average_trade_pnl=pnl,
            return_pct=pnl,
            profit_factor=(gross_profit / gross_loss if gross_loss else None),
            max_drawdown=Decimal(drawdown),
            max_drawdown_pct=Decimal(drawdown),
            peak_equity=Decimal("100"),
        ),
    )


def _aggregation(*, second_pnl: str = "-1", second_drawdown: str = "2"):
    return aggregate_walk_forward_metrics(
        (_window("fold-1", 0, "5"), _window("fold-2", 4, second_pnl, drawdown=second_drawdown)),
        required_symbols=("BTCUSDT",),
        minimum_windows=2,
    )


def _policy(**overrides: object) -> WalkForwardQualificationPolicy:
    values: dict[str, object] = {
        "policy_id": "strict-oos-v1",
        "minimum_windows": 2,
        "minimum_trades": 2,
        "minimum_profit_factor": Decimal("1.0"),
        "maximum_drawdown_pct": Decimal("5"),
        "minimum_average_return_pct": Decimal("0"),
    }
    values.update(overrides)
    return WalkForwardQualificationPolicy(**values)


def test_strict_oos_qualification_binds_aggregation_and_preserves_safety() -> None:
    artifact = build_walk_forward_qualification_artifact(
        candidate=_candidate(),
        aggregation=_aggregation(),
        policy=_policy(),
        evaluator_run_id="evaluator-oos-strict-001",
        evaluator_version="walk-forward-v1",
        evaluated_at=START,
    )

    assert artifact.decision == "qualified"
    assert artifact.source == "walk_forward_oos"
    assert artifact.qualification_policy_id == "strict-oos-v1"
    assert artifact.oos_aggregation_hash is not None
    assert len(artifact.oos_aggregation_hash) == 64
    assert artifact.windows_evaluated == 2
    assert artifact.promotion_state == "unpromoted"
    assert artifact.execution_authority is False
    assert all(gate.passed for gate in artifact.gates)
    assert {metric.metric_id for metric in artifact.metrics} >= {
        "oos_window_count",
        "oos_total_trades",
        "oos_pooled_profit_factor",
        "oos_worst_drawdown_pct",
    }


def test_strict_oos_qualification_rejects_failed_threshold_and_preserves_reason() -> None:
    artifact = build_walk_forward_qualification_artifact(
        candidate=_candidate(),
        aggregation=_aggregation(second_drawdown="9"),
        policy=_policy(maximum_drawdown_pct=Decimal("5")),
        evaluator_run_id="evaluator-oos-strict-001",
        evaluator_version="walk-forward-v1",
        evaluated_at=START,
    )

    assert artifact.decision == "rejected"
    drawdown_gate = next(gate for gate in artifact.gates if gate.gate_id == "oos_drawdown_max")
    assert drawdown_gate.passed is False
    assert drawdown_gate.reason_code == "oos_drawdown_above_threshold"
    assert artifact.promotion_state == "unpromoted"
    assert artifact.execution_authority is False


def test_strict_oos_qualification_fails_closed_for_missing_profit_factor() -> None:
    artifact = build_walk_forward_qualification_artifact(
        candidate=_candidate(),
        aggregation=_aggregation(second_pnl="2"),
        policy=_policy(),
        evaluator_run_id="evaluator-oos-strict-001",
        evaluator_version="walk-forward-v1",
        evaluated_at=START,
    )

    assert artifact.decision == "rejected"
    profit_factor_gate = next(
        gate for gate in artifact.gates if gate.gate_id == "oos_profit_factor_min"
    )
    assert profit_factor_gate.passed is False
    assert profit_factor_gate.observed is None
    assert profit_factor_gate.reason_code == "oos_profit_factor_missing"


def test_strict_oos_qualification_rejects_candidate_universe_mismatch() -> None:
    with pytest.raises(DataQualityError, match="candidate universe"):
        build_walk_forward_qualification_artifact(
            candidate=_candidate(symbols=("BTCUSDT", "ETHUSDT")),
            aggregation=_aggregation(),
            policy=_policy(),
            evaluator_run_id="evaluator-oos-strict-001",
            evaluator_version="walk-forward-v1",
            evaluated_at=START,
        )


def test_strict_oos_qualification_requires_every_symbol_to_pass() -> None:
    aggregation = aggregate_walk_forward_metrics(
        (
            _window("fold-1", 0, "5", symbol="BTCUSDT"),
            _window("fold-2", 4, "-1", symbol="BTCUSDT"),
            _window("fold-1", 0, "5", symbol="ETHUSDT", drawdown="9"),
            _window("fold-2", 4, "-1", symbol="ETHUSDT", drawdown="9"),
        ),
        required_symbols=("BTCUSDT", "ETHUSDT"),
        minimum_windows=2,
    )

    artifact = build_walk_forward_qualification_artifact(
        candidate=_candidate(symbols=("BTCUSDT", "ETHUSDT")),
        aggregation=aggregation,
        policy=_policy(),
        evaluator_run_id="evaluator-oos-strict-001",
        evaluator_version="walk-forward-v1",
        evaluated_at=START,
    )

    assert artifact.decision == "rejected"
    eth_drawdown_gate = next(
        gate for gate in artifact.gates if gate.gate_id == "oos_ethusdt_drawdown_max"
    )
    assert eth_drawdown_gate.passed is False
    assert eth_drawdown_gate.reason_code == "oos_symbol_drawdown_above_threshold"


def test_policy_rejects_invalid_thresholds() -> None:
    with pytest.raises(ValidationError):
        WalkForwardQualificationPolicy(
            policy_id="strict-oos-v1",
            minimum_windows=0,
            minimum_trades=1,
            minimum_profit_factor=Decimal("1"),
            maximum_drawdown_pct=Decimal("5"),
            minimum_average_return_pct=Decimal("0"),
        )
