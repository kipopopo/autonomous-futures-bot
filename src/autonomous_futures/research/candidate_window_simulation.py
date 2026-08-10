from __future__ import annotations

import pandas as pd

from ..data.parquet import DataQualityError
from .creator_artifacts import CreatorCandidateArtifact
from .feature_signals import CausalFeatureSignalEvaluator
from .trade_simulation import TradeSimulationConfig, TradeSimulationResult, simulate_cached_signals


def simulate_candidate_window(
    candidate: CreatorCandidateArtifact,
    frame: pd.DataFrame,
    *,
    symbol: str,
    config: TradeSimulationConfig,
) -> TradeSimulationResult:
    """Simulate one candidate against an explicit cached 5m window."""
    if symbol not in candidate.strategy.universe.symbols:
        raise DataQualityError("simulation symbol is not present in candidate universe")
    signals = CausalFeatureSignalEvaluator().evaluate(candidate, frame)
    return simulate_cached_signals(signals, symbol=symbol, config=config)


__all__ = ["simulate_candidate_window"]
