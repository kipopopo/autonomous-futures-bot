from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.cached_evaluation import (
    CachedEvaluationWindow,
    CachedEvaluationWindowSpec,
)
from autonomous_futures.research.cached_oos_walk_forward import evaluate_cached_oos_walk_forward
from autonomous_futures.research.candidate_window_simulation import simulate_candidate_window
from autonomous_futures.research.creator_artifacts import (
    build_creator_candidate_artifact,
    read_creator_candidate_artifact,
    write_creator_candidate_artifact,
)
from autonomous_futures.research.trade_simulation import TradeSimulationConfig
from autonomous_futures.research.walk_forward import (
    read_walk_forward_aggregation,
    write_walk_forward_aggregation,
)

START = datetime(2026, 1, 1, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
DATASET_HASH = "b" * 64


def _candidate():
    return build_creator_candidate_artifact(
        candidate_id="cand-oos-chain-001",
        strategy=StrategySpec(
            dsl_version=1,
            strategy_id="cand-oos-chain-001",
            family="experimental",
            universe=StrategyUniverse(
                symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
            ),
            features=(FeatureRef(name="returns", lookback=3, shift=1),),
            entry=EntryExit(long="returns > 0", short="returns < 0"),
            exit=EntryExit(long="returns < 0", short="returns > 0"),
            vetoes=("regime_trend == 0",),
        ),
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_HASH,
        creator_run_id="creator-oos-chain",
        research_seed=7,
        created_at=START,
    )


def _window() -> CachedEvaluationWindow:
    closes = [Decimal(value) for value in ("100", "100", "101", "102", "103", "103", "102", "102")]
    return CachedEvaluationWindow(
        spec=CachedEvaluationWindowSpec(
            window_id="oos-001",
            symbol="BTCUSDT",
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=DATASET_HASH,
            time_start=START,
            time_end=START + timedelta(minutes=5 * len(closes)),
        ),
        frame=pd.DataFrame(
            {
                "timestamp": [START + timedelta(minutes=5 * index) for index in range(len(closes))],
                "open": closes,
                "high": [value + Decimal("1") for value in closes],
                "low": [value - Decimal("1") for value in closes],
                "close": closes,
            }
        ),
    )


def test_persisted_candidate_runs_cached_oos_and_persists_aggregation(tmp_path: Path) -> None:
    candidate_path = tmp_path / "candidates" / "cand-oos-chain-001.json"
    write_creator_candidate_artifact(candidate_path, _candidate())
    candidate = read_creator_candidate_artifact(candidate_path)
    config = TradeSimulationConfig(
        starting_equity=Decimal("100"),
        position_fraction=Decimal("1"),
        taker_fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
    )

    aggregation = evaluate_cached_oos_walk_forward(
        candidate,
        (_window(),),
        simulator=lambda item, frame, window: simulate_candidate_window(
            item, frame, symbol=window.spec.symbol, config=config
        ),
    )
    aggregation_path = tmp_path / "aggregations" / "cand-oos-chain-001.json"
    write_walk_forward_aggregation(aggregation_path, aggregation)
    persisted = read_walk_forward_aggregation(aggregation_path)

    assert persisted.aggregation == aggregation
    assert persisted.aggregation.total_trade_count > 0
    assert persisted.aggregation.data_source == "cached_only"
    assert persisted.aggregation.exchange_access is False
