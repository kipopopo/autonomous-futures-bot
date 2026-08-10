from __future__ import annotations

from collections.abc import Callable, Sequence

import pandas as pd

from ..data.parquet import DataQualityError
from .cached_evaluation import CachedEvaluationWindow
from .creator_artifacts import CreatorCandidateArtifact
from .performance_metrics import calculate_performance_metrics
from .trade_simulation import TradeSimulationResult
from .walk_forward import (
    WalkForwardAggregation,
    WalkForwardWindowMetrics,
    aggregate_walk_forward_metrics,
)

CachedSimulator = Callable[
    [CreatorCandidateArtifact, pd.DataFrame, CachedEvaluationWindow], TradeSimulationResult
]


def evaluate_cached_oos_walk_forward(
    candidate: CreatorCandidateArtifact,
    windows: Sequence[CachedEvaluationWindow],
    *,
    simulator: CachedSimulator,
) -> WalkForwardAggregation:
    """Evaluate explicit cached windows and build OOS-only aggregation."""
    if not windows:
        raise DataQualityError("cached OOS evaluation requires at least one window")
    required_symbols = tuple(candidate.strategy.universe.symbols)
    metrics: list[WalkForwardWindowMetrics] = []
    for window in windows:
        spec = window.spec
        if spec.bundle_hash != candidate.bundle_hash:
            raise DataQualityError("cached OOS bundle_hash does not match candidate")
        if spec.dataset_registry_hash != candidate.dataset_registry_hash:
            raise DataQualityError("cached OOS dataset_registry_hash does not match candidate")
        if spec.symbol not in required_symbols:
            raise DataQualityError("cached OOS symbol is not present in candidate universe")
        result = simulator(candidate, window.copy_frame(), window)
        if result.symbol != spec.symbol:
            raise DataQualityError("cached OOS simulation symbol does not match window")
        if result.data_source != "cached_only" or result.exchange_access:
            raise DataQualityError("cached OOS simulation must be cached-only")
        metrics.append(
            WalkForwardWindowMetrics(
                window_id=spec.window_id,
                symbol=spec.symbol,
                window_start=spec.time_start,
                window_end=spec.time_end,
                metrics=calculate_performance_metrics(result),
            )
        )
    return aggregate_walk_forward_metrics(metrics, required_symbols=required_symbols)


__all__ = ["CachedSimulator", "evaluate_cached_oos_walk_forward"]
