from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

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
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.learner_artifacts import build_learner_artifact
from autonomous_futures.research.learner_evaluation import (
    CachedOnlyLearnerEvaluatorAdapter,
    LearnerEvaluationWindow,
    LearnerEvaluationWindowSpec,
    LearnerWindowEvaluation,
)

START = datetime(2026, 8, 8, 12, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
DATASET_REGISTRY_HASH = "b" * 64


def _candidate():
    candidate_id = "cand-learner-eval-001"
    strategy = StrategySpec(
        dsl_version=1,
        strategy_id=candidate_id,
        family="experimental",
        universe=StrategyUniverse(
            symbols=("BTCUSDT", "ETHUSDT"), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="returns", lookback=20, shift=1),),
        entry=EntryExit(long="ema_slope > 0", short="ema_slope < 0"),
        exit=EntryExit(long="rsi > 70", short="rsi < 30"),
        vetoes=("regime_trend == 0",),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        creator_run_id="creator-run-learner-eval",
        research_seed=37,
        created_at=START,
    )


def _learner(tmp_path: Path):
    model_root = tmp_path / "models"
    model_root.mkdir(parents=True)
    model_path = model_root / "learner-001.bin"
    model_bytes = b"cached learner evaluation model"
    model_path.write_bytes(model_bytes)
    candidate = _candidate()
    learner = build_learner_artifact(
        candidate=candidate,
        learner_id="learner-eval-001",
        learner_run_id="learner-run-eval-001",
        learner_version="learner-v1",
        model_family="cached_classifier",
        feature_ids=("returns",),
        training_window_start=START - timedelta(days=7),
        training_window_end=START,
        model_artifact_ref="learner-001.bin",
        model_artifact_hash=hashlib.sha256(model_bytes).hexdigest(),
        created_at=START,
    )
    return learner


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


def _window(
    learner,
    window_id: str,
    start: datetime,
    *,
    learner_id: str | None = None,
    symbol: str = "BTCUSDT",
    bundle_hash: str = BUNDLE_HASH,
    frame: pd.DataFrame | None = None,
):
    spec = LearnerEvaluationWindowSpec(
        window_id=window_id,
        learner_id=learner_id or learner.learner_id,
        candidate_id=learner.candidate_id,
        candidate_artifact_hash=learner.candidate_artifact_hash,
        symbol=symbol,
        bundle_hash=bundle_hash,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        time_start=start,
        time_end=start + timedelta(minutes=15),
    )
    return LearnerEvaluationWindow(spec=spec, frame=frame if frame is not None else _frame(start))


def _result(learner, window: LearnerEvaluationWindow, rows: int | None = None):
    return LearnerWindowEvaluation(
        window_id=window.spec.window_id,
        learner_id=learner.learner_id,
        candidate_id=learner.candidate_id,
        symbol=window.spec.symbol,
        rows_evaluated=rows if rows is not None else len(window.frame),
    )


def test_learner_adapter_is_deterministic_and_isolates_frames(tmp_path: Path) -> None:
    learner = _learner(tmp_path)
    first_window = _window(learner, "window-01", START)
    second_window = _window(learner, "window-02", START + timedelta(minutes=15))
    seen_frames: list[pd.DataFrame] = []

    def evaluator(received_learner, frame, window):
        assert received_learner == learner
        seen_frames.append(frame)
        frame.loc[0, "close"] = Decimal("999")
        return _result(learner, window)

    adapter = CachedOnlyLearnerEvaluatorAdapter(
        learner=learner,
        evaluation_run_id="learner-eval-run-001",
        evaluation_version="learner-evaluator-v1",
        evaluator=evaluator,
    )
    first = adapter.evaluate(
        (second_window, first_window), evaluated_at=datetime(2026, 8, 8, 13, tzinfo=UTC)
    )
    second = adapter.evaluate(
        (first_window, second_window), evaluated_at=datetime(2026, 8, 8, 14, tzinfo=UTC)
    )

    assert first.evaluation_hash == second.evaluation_hash
    assert [item.window_id for item in first.windows] == ["window-01", "window-02"]
    assert first.learner_id == learner.learner_id
    assert first.candidate_id == learner.candidate_id
    assert first.data_source == "cached_only"
    assert first.exchange_access is False
    assert first_window.frame.loc[0, "close"] == Decimal("100.5")
    assert second_window.frame.loc[0, "close"] == Decimal("100.5")
    assert all(received is not first_window.frame for received in seen_frames)


def test_learner_adapter_rejects_binding_mismatch_before_callback(tmp_path: Path) -> None:
    learner = _learner(tmp_path)
    called = False

    def evaluator(received_learner, frame, window):
        nonlocal called
        called = True
        return _result(learner, window)

    adapter = CachedOnlyLearnerEvaluatorAdapter(
        learner=learner,
        evaluation_run_id="learner-eval-run-001",
        evaluation_version="learner-evaluator-v1",
        evaluator=evaluator,
    )

    with pytest.raises(DataQualityError, match="learner_id"):
        adapter.evaluate(
            (_window(learner, "window-01", START, learner_id="learner-other"),),
            evaluated_at=START,
        )
    assert called is False

    with pytest.raises(DataQualityError, match="bundle_hash"):
        adapter.evaluate(
            (_window(learner, "window-01", START, bundle_hash="c" * 64),),
            evaluated_at=START,
        )
    assert called is False


def test_learner_adapter_rejects_unknown_symbol_and_result_identity(tmp_path: Path) -> None:
    learner = _learner(tmp_path)
    adapter = CachedOnlyLearnerEvaluatorAdapter(
        learner=learner,
        evaluation_run_id="learner-eval-run-001",
        evaluation_version="learner-evaluator-v1",
        evaluator=lambda received_learner, frame, window: _result(learner, window),
    )

    with pytest.raises(DataQualityError, match="not present in learner universe"):
        adapter.evaluate(
            (_window(learner, "window-01", START, symbol="SOLUSDT"),),
            evaluated_at=START,
        )

    valid_window = _window(learner, "window-01", START)
    invalid_result_adapter = CachedOnlyLearnerEvaluatorAdapter(
        learner=learner,
        evaluation_run_id="learner-eval-run-001",
        evaluation_version="learner-evaluator-v1",
        evaluator=lambda received_learner, frame, window: LearnerWindowEvaluation(
            window_id="different-window",
            learner_id=learner.learner_id,
            candidate_id=learner.candidate_id,
            symbol=window.spec.symbol,
            rows_evaluated=len(frame),
        ),
    )
    with pytest.raises(DataQualityError, match="window identity"):
        invalid_result_adapter.evaluate((valid_window,), evaluated_at=START)


def test_learner_window_requires_exact_closed_contiguous_coverage(tmp_path: Path) -> None:
    learner = _learner(tmp_path)
    gap_frame = _frame(START).drop(index=1)

    with pytest.raises(DataQualityError, match="gap"):
        _window(learner, "window-01", START, frame=gap_frame)

    with pytest.raises(DataQualityError, match="cover exactly"):
        _window(learner, "window-01", START, frame=_frame(START + timedelta(minutes=5)))


def test_learner_contract_rejects_empty_run_non_utc_and_invalid_rows(tmp_path: Path) -> None:
    learner = _learner(tmp_path)
    adapter = CachedOnlyLearnerEvaluatorAdapter(
        learner=learner,
        evaluation_run_id="learner-eval-run-001",
        evaluation_version="learner-evaluator-v1",
        evaluator=lambda received_learner, frame, window: _result(learner, window),
    )
    with pytest.raises(DataQualityError, match="at least one"):
        adapter.evaluate((), evaluated_at=START)

    with pytest.raises(ValidationError, match="UTC"):
        LearnerEvaluationWindowSpec(
            window_id="window-01",
            learner_id=learner.learner_id,
            candidate_id=learner.candidate_id,
            candidate_artifact_hash=learner.candidate_artifact_hash,
            symbol="BTCUSDT",
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=DATASET_REGISTRY_HASH,
            time_start=datetime(2026, 8, 8, 12),
            time_end=datetime(2026, 8, 8, 12, 15),
        )

    with pytest.raises(DataQualityError, match="rows_evaluated"):
        bad_rows_adapter = CachedOnlyLearnerEvaluatorAdapter(
            learner=learner,
            evaluation_run_id="learner-eval-run-001",
            evaluation_version="learner-evaluator-v1",
            evaluator=lambda received_learner, frame, window: _result(learner, window, rows=0),
        )
        bad_rows_adapter.evaluate((_window(learner, "window-01", START),), evaluated_at=START)
