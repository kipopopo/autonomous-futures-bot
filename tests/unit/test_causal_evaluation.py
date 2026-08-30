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
from autonomous_futures.research.cached_evaluation import (
    CachedEvaluationWindow,
    CachedEvaluationWindowSpec,
    CachedOnlyEvaluatorAdapter,
    CachedWindowEvaluation,
)
from autonomous_futures.research.causal_evaluation import (
    CausalCachedEvaluatorAdapter,
    materialize_causal_context,
)
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.qualification_artifacts import (
    QualificationGateResult,
    QualificationMetric,
)

START = datetime(2026, 8, 7, 12, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
DATASET_REGISTRY_HASH = "b" * 64


def _candidate():
    strategy = StrategySpec(
        dsl_version=1,
        strategy_id="cand-causal-eval-001",
        family="experimental",
        universe=StrategyUniverse(
            symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="regime_trend", lookback=20, shift=1),),
        entry=EntryExit(long="ema_slope > 0", short="ema_slope < 0"),
        exit=EntryExit(long="rsi > 70", short="rsi < 30"),
        vetoes=("regime_trend == 0",),
    )
    return build_creator_candidate_artifact(
        candidate_id="cand-causal-eval-001",
        strategy=strategy,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        creator_run_id="creator-run-causal-eval",
        research_seed=37,
        created_at=START,
    )


def _primary_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [START + timedelta(minutes=5 * index) for index in range(6)],
            "open": [Decimal(value) for value in ("100", "101", "102", "103", "104", "105")],
            "high": [Decimal(value) for value in ("101", "102", "103", "104", "105", "106")],
            "low": [Decimal(value) for value in ("99", "100", "101", "102", "103", "104")],
            "close": [
                Decimal(value) for value in ("100.5", "101.5", "102.5", "103.5", "104.5", "105.5")
            ],
        }
    )


def _context_frame() -> pd.DataFrame:
    context_close_time = pd.Timestamp(START) + timedelta(minutes=15) - timedelta(milliseconds=1)
    return pd.DataFrame(
        {
            "timestamp": [pd.Timestamp(START)],
            "open": [Decimal("90")],
            "high": [Decimal("110")],
            "low": [Decimal("80")],
            "close": [Decimal("105")],
            "close_time": [context_close_time],
        }
    )


def _window() -> CachedEvaluationWindow:
    spec = CachedEvaluationWindowSpec(
        window_id="window-01",
        symbol="BTCUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        time_start=START,
        time_end=START + timedelta(minutes=30),
    )
    return CachedEvaluationWindow(spec=spec, frame=_primary_frame())


def _result(window: CachedEvaluationWindow) -> CachedWindowEvaluation:
    return CachedWindowEvaluation(
        window_id=window.spec.window_id,
        symbol=window.spec.symbol,
        metrics=(QualificationMetric(metric_id="oos_sharpe", value=Decimal("0.5")),),
        gates=(
            QualificationGateResult(
                gate_id="oos_sharpe_min",
                passed=True,
                observed=Decimal("0.5"),
                threshold=Decimal("0.3"),
                comparator="gte",
                reason_code="passed",
            ),
        ),
    )


def test_causal_context_is_unusable_until_15m_close_boundary() -> None:
    primary = _primary_frame()
    context = _context_frame()
    result = materialize_causal_context(primary, context)

    assert result["context_close"].iloc[:3].isna().all()
    assert result["context_close"].iloc[3] == Decimal("105")
    assert result["context_close"].iloc[4] == Decimal("105")
    assert result["context_timestamp"].iloc[3] == pd.Timestamp(START)
    pd.testing.assert_frame_equal(primary, _primary_frame())
    pd.testing.assert_frame_equal(context, _context_frame())


def test_causal_context_normalizes_mixed_timestamp_precision() -> None:
    primary = _primary_frame()
    context = _context_frame()
    primary["timestamp"] = pd.DatetimeIndex(primary["timestamp"]).as_unit("ms")
    context["timestamp"] = pd.DatetimeIndex(context["timestamp"]).as_unit("us")
    context["close_time"] = pd.DatetimeIndex(context["close_time"]).as_unit("us")

    result = materialize_causal_context(primary, context)

    assert result["context_close"].iloc[:3].isna().all()
    assert result["context_close"].iloc[3] == Decimal("105")


def test_causal_context_uses_prior_closed_context_when_available() -> None:
    primary = _primary_frame()
    earlier_context = _context_frame()
    earlier_context["timestamp"] = pd.Timestamp(START) - timedelta(minutes=15)
    earlier_context["close_time"] = pd.Timestamp(START) - timedelta(milliseconds=1)
    earlier_context["close"] = Decimal("95")

    result = materialize_causal_context(primary, earlier_context)

    assert result["context_close"].iloc[0] == Decimal("95")
    assert result["context_close"].iloc[5] == Decimal("95")


def test_causal_context_rejects_invalid_context_close_boundary() -> None:
    invalid_context = _context_frame()
    invalid_context["close_time"] = pd.Timestamp(START) + timedelta(minutes=15)

    with pytest.raises(DataQualityError, match="close_time"):
        materialize_causal_context(_primary_frame(), invalid_context)


def test_causal_adapter_passes_materialized_frame_to_cached_adapter() -> None:
    received: list[pd.DataFrame] = []
    candidate = _candidate()

    def evaluator(received_candidate, frame, window):
        assert received_candidate == candidate
        received.append(frame)
        return _result(window)

    base_adapter = CachedOnlyEvaluatorAdapter(
        candidate=candidate,
        evaluator_run_id="evaluator-run-causal-001",
        evaluator_version="causal-evaluator-v1",
        evaluator=evaluator,
    )
    causal_adapter = CausalCachedEvaluatorAdapter(base_adapter)
    run = causal_adapter.evaluate(
        (_window(),),
        context_frames={"window-01": _context_frame()},
        evaluated_at=START,
    )

    assert run.data_source == "cached_only"
    assert run.exchange_access is False
    assert len(received) == 1
    assert received[0]["context_close"].iloc[:3].isna().all()
    assert received[0]["context_close"].iloc[3] == Decimal("105")


def test_causal_adapter_rejects_missing_context_window() -> None:
    candidate = _candidate()
    base_adapter = CachedOnlyEvaluatorAdapter(
        candidate=candidate,
        evaluator_run_id="evaluator-run-causal-001",
        evaluator_version="causal-evaluator-v1",
        evaluator=lambda received_candidate, frame, window: _result(window),
    )
    causal_adapter = CausalCachedEvaluatorAdapter(base_adapter)

    with pytest.raises(DataQualityError, match="missing context frame"):
        causal_adapter.evaluate((_window(),), context_frames={}, evaluated_at=START)
