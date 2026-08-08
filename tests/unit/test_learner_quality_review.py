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
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.learner_artifacts import build_learner_artifact
from autonomous_futures.research.learner_quality_review import (
    LearnerQualityReviewEvidence,
    LearnerQualityReviewMetric,
    LearnerQualityReviewWindow,
    LearnerQualityReviewWindowResult,
    LearnerQualityReviewWindowSpec,
    execute_learner_quality_review,
    read_learner_quality_review_evidence,
    write_learner_quality_review_evidence,
)
from autonomous_futures.research.learner_runs import LearnerRun, learner_run_content_hash
from autonomous_futures.research.learner_training_evidence import build_learner_training_evidence

START = datetime(2026, 8, 8, 12, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
DATASET_REGISTRY_HASH = "b" * 64


def _candidate():
    candidate_id = "cand-quality-review-001"
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
        creator_run_id="creator-run-quality-review",
        research_seed=41,
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


def _fixtures(tmp_path: Path):
    candidate = _candidate()
    model_root = tmp_path / "models"
    model_root.mkdir(parents=True)
    source_bytes = b"source learner bytes"
    output_bytes = b"output learner bytes"
    (model_root / "source.bin").write_bytes(source_bytes)
    (model_root / "output.bin").write_bytes(output_bytes)
    source = build_learner_artifact(
        candidate=candidate,
        learner_id="learner-quality-review-001",
        learner_run_id="learner-run-quality-review",
        learner_version="source-v1",
        model_family="quality-test",
        feature_ids=("returns",),
        training_window_start=START - timedelta(days=7),
        training_window_end=START,
        model_artifact_ref="source.bin",
        model_artifact_hash=hashlib.sha256(source_bytes).hexdigest(),
        created_at=START,
    )
    run = LearnerRun(
        run_id="run-quality-review-001",
        learner_id=source.learner_id,
        learner_run_id=source.learner_run_id,
        learner_version=source.learner_version,
        learner_artifact_hash=source.artifact_hash,
        candidate_id=source.candidate_id,
        candidate_artifact_hash=source.candidate_artifact_hash,
        bundle_hash=source.bundle_hash,
        dataset_registry_hash=source.dataset_registry_hash,
        input_window_ids=("input-quality-001",),
        input_symbols=("BTCUSDT", "ETHUSDT"),
        feature_ids=source.feature_ids,
        training_window_start=START - timedelta(days=7),
        training_window_end=START,
        prepared_at=START,
        run_hash="0" * 64,
    )
    run = run.model_copy(update={"run_hash": learner_run_content_hash(run)})
    output = build_learner_artifact(
        candidate=candidate,
        learner_id=source.learner_id,
        learner_run_id=run.run_id,
        learner_version="output-v1",
        model_family="quality-test-output",
        feature_ids=source.feature_ids,
        training_window_start=run.training_window_start,
        training_window_end=run.training_window_end,
        model_artifact_ref="output.bin",
        model_artifact_hash=hashlib.sha256(output_bytes).hexdigest(),
        created_at=START,
    )
    training_evidence = build_learner_training_evidence(
        prepared_run=run,
        source_learner=source,
        output_artifact=output,
        candidate=candidate,
        source_learner_artifact_ref="source.json",
        prepared_run_ref="run.json",
        output_artifact_ref="output.json",
        created_at=START,
    )
    return candidate, output, training_evidence


def _window(window_id: str, start: datetime) -> LearnerQualityReviewWindow:
    spec = LearnerQualityReviewWindowSpec(
        window_id=window_id,
        symbol="BTCUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        split="holdout",
        time_start=start,
        time_end=start + timedelta(minutes=15),
    )
    return LearnerQualityReviewWindow(spec=spec, frame=_frame(start))


def _result(window: LearnerQualityReviewWindow) -> LearnerQualityReviewWindowResult:
    return LearnerQualityReviewWindowResult(
        window_id=window.spec.window_id,
        symbol=window.spec.symbol,
        rows_evaluated=len(window.frame),
        metrics=(LearnerQualityReviewMetric(metric_id="holdout_score", value=Decimal("0.75")),),
    )


def test_quality_review_is_deterministic_and_keeps_holdout_frames_isolated(tmp_path: Path) -> None:
    candidate, output, training_evidence = _fixtures(tmp_path)
    first_window = _window("window-01", START)
    second_window = _window("window-02", START + timedelta(minutes=15))
    seen_frames: list[pd.DataFrame] = []

    def reviewer(received_output, frame, window):
        assert received_output == output
        seen_frames.append(frame)
        frame.loc[0, "close"] = Decimal("999")
        return _result(window)

    first = execute_learner_quality_review(
        training_evidence=training_evidence,
        output_artifact=output,
        candidate=candidate,
        windows=(second_window, first_window),
        review_run_id="quality-review-run-001",
        review_version="holdout-review-v1",
        reviewer=reviewer,
        reviewed_at=datetime(2026, 8, 8, 14, tzinfo=UTC),
    )
    second = execute_learner_quality_review(
        training_evidence=training_evidence,
        output_artifact=output,
        candidate=candidate,
        windows=(first_window, second_window),
        review_run_id="quality-review-run-001",
        review_version="holdout-review-v1",
        reviewer=reviewer,
        reviewed_at=datetime(2026, 8, 8, 15, tzinfo=UTC),
    )

    assert isinstance(first, LearnerQualityReviewEvidence)
    assert first.review_hash == second.review_hash
    assert [window.window_id for window in first.windows] == ["window-01", "window-02"]
    assert first.status == "completed"
    assert first.review_conclusion == "observed_only"
    assert first.promotion_state == "unpromoted"
    assert first.paper_activation is False
    assert first.execution_authority is False
    assert first.data_source == "cached_only"
    assert first.exchange_access is False
    assert first_window.frame.loc[0, "close"] == Decimal("100.5")
    assert second_window.frame.loc[0, "close"] == Decimal("100.5")
    assert all(frame is not first_window.frame for frame in seen_frames)


def test_quality_review_rejects_training_binding_before_reviewer(tmp_path: Path) -> None:
    candidate, output, training_evidence = _fixtures(tmp_path)
    called = False

    def reviewer(received_output, frame, window):
        nonlocal called
        called = True
        return _result(window)

    tampered = training_evidence.model_copy(update={"output_artifact_hash": "0" * 64})
    with pytest.raises(DataQualityError, match="training evidence"):
        execute_learner_quality_review(
            training_evidence=tampered,
            output_artifact=output,
            candidate=candidate,
            windows=(_window("window-01", START),),
            review_run_id="quality-review-run-001",
            review_version="holdout-review-v1",
            reviewer=reviewer,
            reviewed_at=START,
        )
    assert called is False


def test_quality_review_rejects_reviewer_identity_and_nonfinite_metric(tmp_path: Path) -> None:
    candidate, output, training_evidence = _fixtures(tmp_path)
    window = _window("window-01", START)

    def bad_identity(received_output, frame, received_window):
        return LearnerQualityReviewWindowResult(
            window_id="different-window",
            symbol=received_window.spec.symbol,
            rows_evaluated=len(frame),
            metrics=(LearnerQualityReviewMetric(metric_id="holdout_score", value=Decimal("0.75")),),
        )

    with pytest.raises(DataQualityError, match="window identity"):
        execute_learner_quality_review(
            training_evidence=training_evidence,
            output_artifact=output,
            candidate=candidate,
            windows=(window,),
            review_run_id="quality-review-run-001",
            review_version="holdout-review-v1",
            reviewer=bad_identity,
            reviewed_at=START,
        )

    with pytest.raises(ValidationError, match="finite"):
        LearnerQualityReviewMetric(metric_id="holdout_score", value=Decimal("NaN"))


def test_quality_review_rejects_holdout_overlap_with_training_window(tmp_path: Path) -> None:
    candidate, output, training_evidence = _fixtures(tmp_path)
    called = False

    def reviewer(received_output, frame, window):
        nonlocal called
        called = True
        return _result(window)

    with pytest.raises(DataQualityError, match="overlaps training window"):
        execute_learner_quality_review(
            training_evidence=training_evidence,
            output_artifact=output,
            candidate=candidate,
            windows=(_window("window-overlap", START - timedelta(minutes=5)),),
            review_run_id="quality-review-run-001",
            review_version="holdout-review-v1",
            reviewer=reviewer,
            reviewed_at=START,
        )
    assert called is False


def test_quality_review_persistence_is_immutable_and_fail_closed(tmp_path: Path) -> None:
    candidate, output, training_evidence = _fixtures(tmp_path)
    evidence = execute_learner_quality_review(
        training_evidence=training_evidence,
        output_artifact=output,
        candidate=candidate,
        windows=(_window("window-01", START),),
        review_run_id="quality-review-run-001",
        review_version="holdout-review-v1",
        reviewer=lambda received_output, frame, window: _result(window),
        reviewed_at=START,
    )
    path = tmp_path / "quality-review.json"

    assert (
        write_learner_quality_review_evidence(
            path,
            evidence,
            training_evidence=training_evidence,
            output_artifact=output,
            candidate=candidate,
        )
        == evidence
    )
    assert (
        read_learner_quality_review_evidence(
            path, training_evidence=training_evidence, output_artifact=output, candidate=candidate
        )
        == evidence
    )
    assert (
        write_learner_quality_review_evidence(
            path,
            evidence,
            training_evidence=training_evidence,
            output_artifact=output,
            candidate=candidate,
        )
        == evidence
    )

    conflict = evidence.model_copy(update={"reviewed_at": START + timedelta(minutes=1)})
    with pytest.raises(DomainViolation, match="immutable"):
        write_learner_quality_review_evidence(
            path,
            conflict,
            training_evidence=training_evidence,
            output_artifact=output,
            candidate=candidate,
        )

    path.write_text(
        path.read_text(encoding="utf-8").replace('"review_hash": "', '"review_hash": "0'),
        encoding="utf-8",
    )
    with pytest.raises(DomainViolation, match="hash"):
        read_learner_quality_review_evidence(
            path, training_evidence=training_evidence, output_artifact=output, candidate=candidate
        )
