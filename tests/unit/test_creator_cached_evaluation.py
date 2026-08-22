from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

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
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.creator_batch import CreatorBatchResult, CreatorBatchTrial
from autonomous_futures.research.creator_cached_evaluation import (
    CreatorCachedEvaluationResult,
    evaluate_creator_batch_cached,
)
from autonomous_futures.research.trade_simulation import EquityPoint, TradeSimulationResult

HASH = "a" * 64
START = datetime(2026, 1, 1, tzinfo=UTC)


def _candidate():
    strategy = StrategySpec(
        dsl_version=1,
        strategy_id="cand-eval-001",
        family="range_mean_reversion",
        universe=StrategyUniverse(
            symbols=("DOGEUSDT",), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="rsi", lookback=14, shift=1),),
        entry=EntryExit(long="rsi <= 30", short="rsi >= 70"),
        exit=EntryExit(long="rsi >= 50", short="rsi <= 50"),
        vetoes=("testing_only_no_promotion",),
    )
    return build_creator_candidate_artifact(
        candidate_id="cand-eval-001",
        strategy=strategy,
        bundle_hash=HASH,
        dataset_registry_hash=HASH,
        creator_run_id="creator-eval-001",
        research_seed=1,
        created_at=START,
    )


def _window(candidate) -> CachedEvaluationWindow:
    timestamps = pd.date_range(START, periods=2, freq="5min", tz="UTC")
    return CachedEvaluationWindow(
        spec=CachedEvaluationWindowSpec(
            window_id="doge-1",
            symbol="DOGEUSDT",
            bundle_hash=candidate.bundle_hash,
            dataset_registry_hash=candidate.dataset_registry_hash,
            time_start=START,
            time_end=START + timedelta(minutes=10),
        ),
        frame=pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": [0.1, 0.101],
                "high": [0.101, 0.102],
                "low": [0.099, 0.1],
                "close": [0.1005, 0.1015],
            }
        ),
    )


def _flat_result(candidate, frame: pd.DataFrame, window: CachedEvaluationWindow):
    timestamp = frame["timestamp"].iloc[-1].to_pydatetime()
    return TradeSimulationResult(
        symbol=window.spec.symbol,
        starting_equity=Decimal("100"),
        final_equity=Decimal("100"),
        total_fees=Decimal("0"),
        total_slippage_cost=Decimal("0"),
        equity_curve=(EquityPoint(timestamp=timestamp, equity=Decimal("100")),),
    )


def test_creator_batch_cached_evaluation_builds_oos_aggregation() -> None:
    candidate = _candidate()
    result = evaluate_creator_batch_cached(
        CreatorBatchResult(
            trials=(
                CreatorBatchTrial(
                    research_run_id="run-evaluation",
                    candidate_id=candidate.candidate_id,
                    decision="accepted",
                    reason_codes=("candidate_accepted_for_testing",),
                    candidate_artifact_hash=candidate.artifact_hash,
                ),
            ),
            accepted_candidates=(candidate,),
        ),
        windows_by_candidate={candidate.candidate_id: (_window(candidate),)},
        simulator=_flat_result,
    )

    assert isinstance(result, CreatorCachedEvaluationResult)
    assert result.evaluations[0].status == "evaluated"
    assert result.evaluations[0].aggregation is not None
    assert result.evaluations[0].aggregation.window_count == 1
    assert result.evaluations[0].aggregation.data_source == "cached_only"
    assert result.execution_authority is False


def test_creator_batch_cached_evaluation_blocks_missing_windows() -> None:
    candidate = _candidate()
    result = evaluate_creator_batch_cached(
        CreatorBatchResult(
            trials=(
                CreatorBatchTrial(
                    research_run_id="run-evaluation",
                    candidate_id=candidate.candidate_id,
                    decision="accepted",
                    reason_codes=("candidate_accepted_for_testing",),
                    candidate_artifact_hash=candidate.artifact_hash,
                ),
            ),
            accepted_candidates=(candidate,),
        ),
        windows_by_candidate={},
        simulator=_flat_result,
    )

    assert result.evaluations[0].status == "blocked"
    assert result.evaluations[0].reason_codes == ("missing_cached_windows",)
    assert result.evaluations[0].aggregation is None
