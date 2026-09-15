from __future__ import annotations

from datetime import timedelta

import pandas as pd

from ..data.parquet import DataQualityError
from .creator_artifacts import CreatorCandidateArtifact
from .feature_signals import CausalFeatureSignalEvaluator
from .trade_simulation import TradeSimulationConfig, TradeSimulationResult, simulate_cached_signals


def _timeframe_to_timedelta(timeframe: str) -> timedelta:
    if timeframe == "5m":
        return timedelta(minutes=5)
    if timeframe == "15m":
        return timedelta(minutes=15)
    if timeframe == "1h":
        return timedelta(hours=1)
    return timedelta(minutes=5)


def simulate_candidate_window(
    candidate: CreatorCandidateArtifact,
    frame: pd.DataFrame,
    *,
    symbol: str,
    config: TradeSimulationConfig,
) -> TradeSimulationResult:
    """Simulate one candidate against an explicit cached window."""
    if symbol not in candidate.strategy.universe.symbols:
        raise DataQualityError("simulation symbol is not present in candidate universe")
    signals = CausalFeatureSignalEvaluator().evaluate(candidate, frame)
    risk = candidate.strategy.risk
    if risk is not None:
        config = config.model_copy(
            update={
                "position_fraction": risk.position_fraction,
                "stop_atr_multiplier": risk.stop_atr_multiplier,
                "take_profit_atr_multiplier": risk.take_profit_atr_multiplier,
                "trailing_atr_multiplier": risk.trailing_atr_multiplier,
            }
        )
    interval = _timeframe_to_timedelta(candidate.strategy.universe.timeframe)
    return simulate_cached_signals(signals, symbol=symbol, config=config, interval=interval)


__all__ = ["simulate_candidate_window"]
