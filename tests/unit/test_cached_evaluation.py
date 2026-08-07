from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from pydantic import ValidationError

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
        strategy_id="cand-cached-eval-001",
        family="experimental",
        universe=StrategyUniverse(
            symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="returns", lookback=20, shift=1),),
        entry=EntryExit(long="ema_slope > 0", short="ema_slope < 0"),
        exit=EntryExit(long="rsi > 70", short="rsi < 30"),
        vetoes=("regime_trend == 0",),
    )
    return build_creator_candidate_artifact(
        candidate_id="cand-cached-eval-001",
        strategy=strategy,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        creator_run_id="creator-run-cached-eval",
        research_seed=31,
        created_at=START,
    )


def _frame(start: datetime) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=5 * index) for index in range(3)],
            "open": [Decimal("100"), Decimal("101"), Decimal("102")],
            "high": [Decimal("101"), Decimal("102"), Decimal("103")],
            "low": [Decimal("99"), Decimal("100"), Decimal("101")],
            "close": [Decimal("100.5"), Decimal("101.5"), Decimal("102.5")],
        }
    )


def _window(window_id: str, start: datetime, *, bundle_hash: str = BUNDLE_HASH):
    spec = CachedEvaluationWindowSpec(
        window_id=window_id,
        symbol="BTCUSDT",
        bundle_hash=bundle_hash,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        time_start=start,
        time_end=start + timedelta(minutes=15),
    )
    return CachedEvaluationWindow(spec=spec, frame=_frame(start))


def _result(window: CachedEvaluationWindow) -> CachedWindowEvaluation:
    return CachedWindowEvaluation(
        window_id=window.spec.window_id,
        symbol=window.spec.symbol,
        metrics=(QualificationMetric(metric_id="oos_sharpe", value=Decimal("1.25")),),
        gates=(
            QualificationGateResult(
                gate_id="oos_sharpe_min",
                passed=True,
                observed=Decimal("1.25"),
                threshold=Decimal("1.0"),
                comparator="gte",
                reason_code="passed",
            ),
        ),
    )


def test_cached_adapter_is_deterministic_and_isolates_input_frames() -> None:
    candidate = _candidate()
    first_window = _window("window-01", START)
    second_window = _window("window-02", START + timedelta(minutes=15))
    seen_frames: list[pd.DataFrame] = []

    def evaluator(received_candidate, frame, window):
        assert received_candidate == candidate
        seen_frames.append(frame)
        frame.loc[0, "close"] = Decimal("999")
        return _result(window)

    adapter = CachedOnlyEvaluatorAdapter(
        candidate=candidate,
        evaluator_run_id="evaluator-run-cached-001",
        evaluator_version="cached-evaluator-v1",
        evaluator=evaluator,
    )
    first = adapter.evaluate(
        (second_window, first_window), evaluated_at=datetime(2026, 8, 7, 13, tzinfo=UTC)
    )
    second = adapter.evaluate(
        (first_window, second_window), evaluated_at=datetime(2026, 8, 7, 14, tzinfo=UTC)
    )

    assert first.evaluation_hash == second.evaluation_hash
    assert [window.window_id for window in first.windows] == ["window-01", "window-02"]
    assert first.data_source == "cached_only"
    assert first.exchange_access is False
    assert first_window.frame.loc[0, "close"] == Decimal("100.5")
    assert second_window.frame.loc[0, "close"] == Decimal("100.5")
    assert all(received is not first_window.frame for received in seen_frames)


def test_cached_adapter_rejects_binding_mismatch_before_callback() -> None:
    called = False

    def evaluator(received_candidate, frame, window):
        nonlocal called
        called = True
        return _result(window)

    adapter = CachedOnlyEvaluatorAdapter(
        candidate=_candidate(),
        evaluator_run_id="evaluator-run-cached-001",
        evaluator_version="cached-evaluator-v1",
        evaluator=evaluator,
    )

    with pytest.raises(DataQualityError, match="bundle_hash"):
        adapter.evaluate((_window("window-01", START, bundle_hash="c" * 64),), evaluated_at=START)
    assert called is False


def test_cached_adapter_rejects_unknown_symbol_and_result_identity() -> None:
    candidate = _candidate()
    spec = CachedEvaluationWindowSpec(
        window_id="window-01",
        symbol="ETHUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        time_start=START,
        time_end=START + timedelta(minutes=15),
    )
    window = CachedEvaluationWindow(spec=spec, frame=_frame(START))
    adapter = CachedOnlyEvaluatorAdapter(
        candidate=candidate,
        evaluator_run_id="evaluator-run-cached-001",
        evaluator_version="cached-evaluator-v1",
        evaluator=lambda received_candidate, frame, received_window: _result(window),
    )

    with pytest.raises(DataQualityError, match="not present in candidate universe"):
        adapter.evaluate((window,), evaluated_at=START)

    valid_window = _window("window-01", START)
    invalid_result_adapter = CachedOnlyEvaluatorAdapter(
        candidate=candidate,
        evaluator_run_id="evaluator-run-cached-001",
        evaluator_version="cached-evaluator-v1",
        evaluator=lambda received_candidate, frame, received_window: CachedWindowEvaluation(
            window_id="different-window",
            symbol=received_window.spec.symbol,
            metrics=_result(valid_window).metrics,
            gates=_result(valid_window).gates,
        ),
    )
    with pytest.raises(DataQualityError, match="window identity"):
        invalid_result_adapter.evaluate((valid_window,), evaluated_at=START)


def test_cached_window_requires_exact_closed_contiguous_coverage() -> None:
    spec = CachedEvaluationWindowSpec(
        window_id="window-01",
        symbol="BTCUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        time_start=START,
        time_end=START + timedelta(minutes=15),
    )
    gap_frame = _frame(START).drop(index=1)

    with pytest.raises(DataQualityError, match="gap"):
        CachedEvaluationWindow(spec=spec, frame=gap_frame)

    with pytest.raises(DataQualityError, match="cover exactly"):
        CachedEvaluationWindow(
            spec=spec,
            frame=_frame(START + timedelta(minutes=5)),
        )


def test_cached_window_rejects_timestamp_only_frames() -> None:
    spec = CachedEvaluationWindowSpec(
        window_id="window-01",
        symbol="BTCUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        time_start=START,
        time_end=START + timedelta(minutes=15),
    )
    timestamp_only = _frame(START).loc[:, ["timestamp"]]

    with pytest.raises(DataQualityError, match="OHLC"):
        CachedEvaluationWindow(spec=spec, frame=timestamp_only)


def test_cached_contract_rejects_empty_run_and_non_utc_window() -> None:
    candidate = _candidate()
    adapter = CachedOnlyEvaluatorAdapter(
        candidate=candidate,
        evaluator_run_id="evaluator-run-cached-001",
        evaluator_version="cached-evaluator-v1",
        evaluator=lambda received_candidate, frame, window: _result(window),
    )
    with pytest.raises(DataQualityError, match="at least one"):
        adapter.evaluate((), evaluated_at=START)

    with pytest.raises(ValidationError, match="UTC"):
        CachedEvaluationWindowSpec(
            window_id="window-01",
            symbol="BTCUSDT",
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=DATASET_REGISTRY_HASH,
            time_start=datetime(2026, 8, 7, 12),
            time_end=datetime(2026, 8, 7, 12, 15),
        )
