from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.candidate_window_simulation import simulate_candidate_window
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.feature_signals import CausalFeatureSignalEvaluator
from autonomous_futures.research.trade_simulation import TradeSimulationConfig

START = datetime(2026, 8, 7, 12, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
DATASET_REGISTRY_HASH = "b" * 64


def _candidate(
    *,
    feature_names: tuple[str, ...] = ("returns",),
    long_expression: str = "returns > 0",
    short_expression: str = "returns < 0",
):
    strategy = StrategySpec(
        dsl_version=1,
        strategy_id="cand-feature-signal-001",
        family="experimental",
        universe=StrategyUniverse(
            symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=tuple(FeatureRef(name=name, lookback=3, shift=1) for name in feature_names),
        entry=EntryExit(long=long_expression, short=short_expression),
        exit=EntryExit(long="returns < 0", short="returns > 0"),
        vetoes=("regime_trend == 0",),
    )
    return build_creator_candidate_artifact(
        candidate_id="cand-feature-signal-001",
        strategy=strategy,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        creator_run_id="creator-run-feature-signal",
        research_seed=41,
        created_at=START,
    )


def _frame() -> pd.DataFrame:
    closes = ("100", "100", "101", "102", "103", "103", "102", "102", "102", "103", "104", "104")
    close_values = [Decimal(value) for value in closes]
    return pd.DataFrame(
        {
            "timestamp": [START + timedelta(minutes=5 * index) for index in range(len(closes))],
            "open": close_values,
            "high": [value + Decimal("1") for value in close_values],
            "low": [value - Decimal("1") for value in close_values],
            "close": close_values,
        }
    )


def test_returns_feature_and_signal_use_only_prior_completed_bars() -> None:
    candidate = _candidate()
    source = _frame()
    mutated = source.copy(deep=True)
    mutated.loc[8, "close"] = Decimal("9999")
    mutated.loc[8, "high"] = Decimal("10000")

    evaluator = CausalFeatureSignalEvaluator()
    original = evaluator.evaluate(candidate, source)
    changed = evaluator.evaluate(candidate, mutated)

    assert original.loc[8, "returns"] == changed.loc[8, "returns"]
    assert original.loc[8, "signal"] == changed.loc[8, "signal"]
    pd.testing.assert_frame_equal(source, _frame())


def test_supported_features_are_prior_bar_only_and_input_is_unchanged() -> None:
    candidate = _candidate(
        feature_names=("returns", "ema_slope", "donchian_high", "donchian_low", "regime_trend"),
        long_expression="ema_slope > 0",
        short_expression="ema_slope < 0",
    )
    source = _frame()
    before = source.copy(deep=True)
    mutated = source.copy(deep=True)
    mutated.loc[8, "close"] = Decimal("9999")
    mutated.loc[8, "high"] = Decimal("10000")
    mutated.loc[8, "low"] = Decimal("9998")

    evaluator = CausalFeatureSignalEvaluator()
    result = evaluator.evaluate(candidate, source)
    changed = evaluator.evaluate(candidate, mutated)

    assert {"returns", "ema_slope", "donchian_high", "donchian_low", "regime_trend"}.issubset(
        result.columns
    )
    for feature_name in ("returns", "ema_slope", "donchian_high", "donchian_low", "regime_trend"):
        assert result.loc[8, feature_name] == changed.loc[8, feature_name]
    assert result.loc[8, "signal"] == changed.loc[8, "signal"]
    pd.testing.assert_frame_equal(source, before)


def test_bollinger_zscore_is_supported_and_uses_only_prior_bars() -> None:
    candidate = _candidate(
        feature_names=("bollinger_zscore",),
        long_expression="bollinger_zscore < -1",
        short_expression="bollinger_zscore > 1",
    )
    source = _frame()
    mutated = source.copy(deep=True)
    mutated.loc[8, "close"] = Decimal("9999")
    mutated.loc[8, "high"] = Decimal("10000")

    original = CausalFeatureSignalEvaluator().evaluate(candidate, source)
    changed = CausalFeatureSignalEvaluator().evaluate(candidate, mutated)

    assert "bollinger_zscore" in original.columns
    assert original.loc[8, "bollinger_zscore"] == changed.loc[8, "bollinger_zscore"]
    assert original.loc[8, "signal"] == changed.loc[8, "signal"]
    pd.testing.assert_frame_equal(source, _frame())


def test_rsi_is_supported_and_uses_only_prior_bars() -> None:
    candidate = _candidate(
        feature_names=("rsi",),
        long_expression="rsi < 30",
        short_expression="rsi > 70",
    )
    source = _frame()
    mutated = source.copy(deep=True)
    mutated.loc[8, "close"] = Decimal("9999")
    mutated.loc[8, "high"] = Decimal("10000")

    original = CausalFeatureSignalEvaluator().evaluate(candidate, source)
    changed = CausalFeatureSignalEvaluator().evaluate(candidate, mutated)

    assert "rsi" in original.columns
    assert original.loc[8, "rsi"] == changed.loc[8, "rsi"]
    assert original.loc[8, "signal"] == changed.loc[8, "signal"]
    assert original["rsi"].dropna().between(0, 100).all()
    pd.testing.assert_frame_equal(source, _frame())


def test_signal_entries_are_fresh_states_not_repeated_or_neutral_reversals() -> None:
    candidate = _candidate()
    result = CausalFeatureSignalEvaluator().evaluate(candidate, _frame())

    assert result.index[result["long_entry"]].tolist() == [3, 10]
    assert result.index[result["short_entry"]].tolist() == [7]
    assert not bool(result.loc[4, "long_entry"])
    assert not bool(result.loc[8, "short_entry"])
    assert not bool(result.loc[9, "long_entry"])
    assert result.loc[3, "signal"] == 1
    assert result.loc[7, "signal"] == -1
    assert result.loc[10, "signal"] == 1


def test_candidate_window_simulation_composes_causal_signals_with_cached_ledger() -> None:
    source = _frame()
    result = simulate_candidate_window(
        _candidate(),
        source,
        symbol="BTCUSDT",
        config=TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("1"),
            taker_fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
        ),
    )

    assert result.symbol == "BTCUSDT"
    assert result.trades
    assert result.data_source == "cached_only"
    pd.testing.assert_frame_equal(source, _frame())


def test_candidate_window_simulation_rejects_outside_universe_symbol() -> None:
    with pytest.raises(DataQualityError, match="candidate universe"):
        simulate_candidate_window(
            _candidate(),
            _frame(),
            symbol="ETHUSDT",
            config=TradeSimulationConfig(
                starting_equity=Decimal("100"),
                position_fraction=Decimal("1"),
                taker_fee_rate=Decimal("0"),
                slippage_rate=Decimal("0"),
            ),
        )


def test_expression_feature_must_be_declared() -> None:
    candidate = _candidate(long_expression="ema_slope > 0")

    with pytest.raises(DataQualityError, match="not declared"):
        CausalFeatureSignalEvaluator().evaluate(candidate, _frame())


def test_unimplemented_approved_feature_is_rejected() -> None:
    candidate = _candidate(
        feature_names=("atr",), long_expression="atr > 50", short_expression="atr < 50"
    )

    with pytest.raises(DataQualityError, match="not supported"):
        CausalFeatureSignalEvaluator().evaluate(candidate, _frame())


def test_duplicate_features_and_conflicting_conditions_are_rejected() -> None:
    duplicate_candidate = _candidate(feature_names=("returns", "returns"))
    with pytest.raises(DataQualityError, match="unique"):
        CausalFeatureSignalEvaluator().evaluate(duplicate_candidate, _frame())

    conflicting_candidate = _candidate(
        long_expression="returns == 0", short_expression="returns == 0"
    )
    with pytest.raises(DataQualityError, match="both long and short"):
        CausalFeatureSignalEvaluator().evaluate(conflicting_candidate, _frame())
