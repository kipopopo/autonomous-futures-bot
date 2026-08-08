from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.learner_artifacts import build_learner_artifact
from autonomous_futures.research.learner_evaluation import (
    LearnerEvaluationWindow,
    LearnerEvaluationWindowSpec,
)
from autonomous_futures.research.learner_metric_evaluation import (
    CachedOnlyLearnerMetricAdapter,
    LearnerMetricWindowEvaluation,
)
from autonomous_futures.research.trade_simulation import (
    TradeSimulationConfig,
    simulate_cached_signals,
)

START = datetime(2026, 8, 8, 12, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
DATASET_REGISTRY_HASH = "b" * 64


def _candidate():
    candidate_id = "cand-learner-metric-001"
    strategy = StrategySpec(
        dsl_version=1,
        strategy_id=candidate_id,
        family="experimental",
        universe=StrategyUniverse(
            symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="returns", lookback=1, shift=1),),
        entry=EntryExit(long="returns > 0", short="returns < 0"),
        exit=EntryExit(long="returns < 0", short="returns > 0"),
        vetoes=("regime_trend == 0",),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        creator_run_id="creator-run-learner-metric",
        research_seed=47,
        created_at=START,
    )


def _learner(tmp_path: Path, candidate=None):
    model_root = tmp_path / "models"
    model_root.mkdir(parents=True)
    model_bytes = b"learner-metric-model"
    (model_root / "learner-metric.bin").write_bytes(model_bytes)
    candidate = candidate or _candidate()
    return build_learner_artifact(
        candidate=candidate,
        learner_id="learner-metric-001",
        learner_run_id="learner-run-metric-001",
        learner_version="learner-v1",
        model_family="explicit_cached_signal_callback",
        feature_ids=("returns",),
        training_window_start=START - timedelta(days=7),
        training_window_end=START,
        model_artifact_ref="learner-metric.bin",
        model_artifact_hash=hashlib.sha256(model_bytes).hexdigest(),
        created_at=START,
    )


def _frame(start: datetime = START) -> pd.DataFrame:
    opens = [
        Decimal("100"),
        Decimal("101"),
        Decimal("103"),
        Decimal("102"),
        Decimal("104"),
        Decimal("105"),
    ]
    return pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=5 * index) for index in range(len(opens))],
            "open": opens,
            "high": [value + Decimal("1") for value in opens],
            "low": [value - Decimal("1") for value in opens],
            "close": opens,
        }
    )


def _window(learner, window_id: str, start: datetime = START) -> LearnerEvaluationWindow:
    spec = LearnerEvaluationWindowSpec(
        window_id=window_id,
        learner_id=learner.learner_id,
        candidate_id=learner.candidate_id,
        candidate_artifact_hash=learner.candidate_artifact_hash,
        symbol="BTCUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        time_start=start,
        time_end=start + timedelta(minutes=30),
    )
    return LearnerEvaluationWindow(spec=spec, frame=_frame(start))


def _config() -> TradeSimulationConfig:
    return TradeSimulationConfig(
        starting_equity=Decimal("100"),
        position_fraction=Decimal("1"),
        taker_fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
    )


def test_metric_adapter_runs_explicit_cached_simulation_and_calculates_metrics(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    learner = _learner(tmp_path, candidate)
    window = _window(learner, "window-01")
    original = window.frame.copy(deep=True)
    seen_frames: list[pd.DataFrame] = []

    def simulate(received_learner, received_candidate, frame, received_window):
        assert received_learner == learner
        assert received_candidate == candidate
        assert received_window.spec.window_id == "window-01"
        seen_frames.append(frame)
        frame["signal"] = [0, 1, 0, -1, 0, 0]
        return simulate_cached_signals(frame, symbol="BTCUSDT", config=_config())

    adapter = CachedOnlyLearnerMetricAdapter(
        learner=learner,
        candidate=candidate,
        evaluation_run_id="learner-metric-run-001",
        evaluation_version="learner-metric-v1",
        simulator=simulate,
    )
    run = adapter.evaluate((window,), evaluated_at=datetime(2026, 8, 8, 13, tzinfo=UTC))

    assert run.windows[0].window_id == "window-01"
    assert isinstance(run.windows[0], LearnerMetricWindowEvaluation)
    assert run.windows[0].rows_evaluated == 6
    assert run.windows[0].metrics.trade_count == 1
    expected_pnl = Decimal("100") / Decimal("101")
    assert run.windows[0].metrics.net_pnl == expected_pnl
    assert run.windows[0].metrics.final_equity == Decimal("100") + expected_pnl
    assert run.windows[0].metrics.data_source == "cached_only"
    assert run.data_source == "cached_only"
    assert run.exchange_access is False
    assert window.frame.equals(original)
    assert "signal" not in window.frame
    assert all(frame is not window.frame for frame in seen_frames)


def test_metric_adapter_is_deterministic_and_preserves_window_order(tmp_path: Path) -> None:
    candidate = _candidate()
    learner = _learner(tmp_path, candidate)
    first_window = _window(learner, "window-01")
    second_window = _window(learner, "window-02", START + timedelta(minutes=30))

    def simulate(received_learner, received_candidate, frame, received_window):
        frame["signal"] = [0, 1, 0, -1, 0, 0]
        return simulate_cached_signals(frame, symbol=received_window.spec.symbol, config=_config())

    adapter = CachedOnlyLearnerMetricAdapter(
        learner=learner,
        candidate=candidate,
        evaluation_run_id="learner-metric-run-001",
        evaluation_version="learner-metric-v1",
        simulator=simulate,
    )
    first = adapter.evaluate(
        (second_window, first_window), evaluated_at=datetime(2026, 8, 8, 13, tzinfo=UTC)
    )
    second = adapter.evaluate(
        (first_window, second_window), evaluated_at=datetime(2026, 8, 8, 14, tzinfo=UTC)
    )

    assert first.evaluation_hash == second.evaluation_hash
    assert [window.window_id for window in first.windows] == ["window-01", "window-02"]
    assert first.windows[0].metrics == second.windows[0].metrics


def test_metric_adapter_rejects_result_identity_mismatch(tmp_path: Path) -> None:
    candidate = _candidate()
    learner = _learner(tmp_path, candidate)

    def simulate(received_learner, received_candidate, frame, received_window):
        frame["signal"] = [0, 1, 0, -1, 0, 0]
        return simulate_cached_signals(frame, symbol="ETHUSDT", config=_config())

    adapter = CachedOnlyLearnerMetricAdapter(
        learner=learner,
        candidate=candidate,
        evaluation_run_id="learner-metric-run-001",
        evaluation_version="learner-metric-v1",
        simulator=simulate,
    )

    with pytest.raises(DataQualityError, match="symbol"):
        adapter.evaluate((_window(learner, "window-01"),), evaluated_at=START)


def test_metric_adapter_rejects_empty_run_and_invalid_timestamp(tmp_path: Path) -> None:
    candidate = _candidate()
    learner = _learner(tmp_path, candidate)
    adapter = CachedOnlyLearnerMetricAdapter(
        learner=learner,
        candidate=candidate,
        evaluation_run_id="learner-metric-run-001",
        evaluation_version="learner-metric-v1",
        simulator=lambda received_learner, received_candidate, frame, received_window: (
            simulate_cached_signals(
                frame.assign(signal=[0, 0, 0, 0, 0, 0]),
                symbol=received_window.spec.symbol,
                config=_config(),
            )
        ),
    )

    with pytest.raises(DataQualityError, match="at least one"):
        adapter.evaluate((), evaluated_at=START)
    with pytest.raises(DataQualityError, match="timezone-aware UTC"):
        adapter.evaluate((_window(learner, "window-01"),), evaluated_at=datetime(2026, 8, 8, 13))
