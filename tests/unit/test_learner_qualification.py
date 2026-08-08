from __future__ import annotations

import hashlib
import json
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
from autonomous_futures.research.learner_qualification import (
    LearnerQualificationEvidence,
    LearnerQualificationPolicy,
    LearnerQualificationPolicyGate,
    build_learner_qualification_evidence,
    learner_qualification_policy_content_hash,
    read_learner_qualification_evidence,
    write_learner_qualification_evidence,
)
from autonomous_futures.research.learner_quality_review import (
    LearnerQualityReviewMetric,
    LearnerQualityReviewWindow,
    LearnerQualityReviewWindowResult,
    LearnerQualityReviewWindowSpec,
    execute_learner_quality_review,
)
from autonomous_futures.research.learner_runs import LearnerRun, learner_run_content_hash
from autonomous_futures.research.learner_training_evidence import build_learner_training_evidence

START = datetime(2026, 8, 8, 12, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
DATASET_REGISTRY_HASH = "b" * 64


def _candidate():
    candidate_id = "cand-learner-qualification-001"
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
        creator_run_id="creator-run-learner-qualification",
        research_seed=43,
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


def _fixtures(tmp_path: Path, scores: tuple[Decimal, ...] = (Decimal("0.80"), Decimal("0.60"))):
    candidate = _candidate()
    model_root = tmp_path / "models"
    model_root.mkdir(parents=True)
    source_bytes = b"source learner bytes"
    output_bytes = b"output learner bytes"
    (model_root / "source.bin").write_bytes(source_bytes)
    (model_root / "output.bin").write_bytes(output_bytes)
    source = build_learner_artifact(
        candidate=candidate,
        learner_id="learner-qualification-001",
        learner_run_id="learner-run-qualification",
        learner_version="source-v1",
        model_family="qualification-test",
        feature_ids=("returns",),
        training_window_start=START - timedelta(days=7),
        training_window_end=START,
        model_artifact_ref="source.bin",
        model_artifact_hash=hashlib.sha256(source_bytes).hexdigest(),
        created_at=START,
    )
    run = LearnerRun(
        run_id="run-learner-qualification-001",
        learner_id=source.learner_id,
        learner_run_id=source.learner_run_id,
        learner_version=source.learner_version,
        learner_artifact_hash=source.artifact_hash,
        candidate_id=source.candidate_id,
        candidate_artifact_hash=source.candidate_artifact_hash,
        bundle_hash=source.bundle_hash,
        dataset_registry_hash=source.dataset_registry_hash,
        input_window_ids=("input-learner-qualification-001",),
        input_symbols=("BTCUSDT", "ETHUSDT"),
        feature_ids=source.feature_ids,
        training_window_start=source.training_window_start,
        training_window_end=source.training_window_end,
        prepared_at=START,
        run_hash="0" * 64,
    )
    run = run.model_copy(update={"run_hash": learner_run_content_hash(run)})
    output = build_learner_artifact(
        candidate=candidate,
        learner_id=source.learner_id,
        learner_run_id=run.run_id,
        learner_version="output-v1",
        model_family="qualification-test-output",
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
    windows = tuple(
        _window(f"window-{index:02d}", START + timedelta(minutes=15 * index))
        for index in range(len(scores))
    )

    def reviewer(received_output, frame, review_window):
        index = int(review_window.spec.window_id[-2:])
        return LearnerQualityReviewWindowResult(
            window_id=review_window.spec.window_id,
            symbol=review_window.spec.symbol,
            rows_evaluated=len(frame),
            metrics=(LearnerQualityReviewMetric(metric_id="holdout_score", value=scores[index]),),
        )

    review = execute_learner_quality_review(
        training_evidence=training_evidence,
        output_artifact=output,
        candidate=candidate,
        windows=windows,
        review_run_id="review-learner-qualification-001",
        review_version="holdout-v1",
        reviewer=reviewer,
        reviewed_at=START + timedelta(hours=1),
    )
    return candidate, output, training_evidence, review


def _policy(*, minimum_windows: int = 2) -> LearnerQualificationPolicy:
    return LearnerQualificationPolicy(
        policy_id="learner-quality-policy-v1",
        minimum_windows=minimum_windows,
        gates=(
            LearnerQualificationPolicyGate(
                metric_id="holdout_score", comparator="gte", threshold=Decimal("0.50")
            ),
        ),
    )


def test_learner_qualification_is_deterministic_and_unpromoted(tmp_path: Path) -> None:
    candidate, output, training_evidence, review = _fixtures(tmp_path)
    policy = _policy()

    first = build_learner_qualification_evidence(
        training_evidence=training_evidence,
        quality_review=review,
        output_artifact=output,
        candidate=candidate,
        policy=policy,
        evaluated_at=START + timedelta(hours=2),
    )
    second = build_learner_qualification_evidence(
        training_evidence=training_evidence,
        quality_review=review,
        output_artifact=output,
        candidate=candidate,
        policy=policy,
        evaluated_at=START + timedelta(hours=3),
    )

    assert isinstance(first, LearnerQualificationEvidence)
    assert first.qualification_hash == second.qualification_hash
    assert first.decision == "qualified"
    assert first.windows_evaluated == 2
    assert all(gate.passed for gate in first.gates)
    assert first.policy_hash == learner_qualification_policy_content_hash(policy)
    assert first.promotion_state == "unpromoted"
    assert first.paper_activation is False
    assert first.execution_authority is False
    assert first.data_source == "cached_only"
    assert first.exchange_access is False


def test_learner_qualification_rejects_failed_window_and_preserves_gate(tmp_path: Path) -> None:
    candidate, output, training_evidence, review = _fixtures(
        tmp_path, scores=(Decimal("0.80"), Decimal("0.40"))
    )

    evidence = build_learner_qualification_evidence(
        training_evidence=training_evidence,
        quality_review=review,
        output_artifact=output,
        candidate=candidate,
        policy=_policy(),
        evaluated_at=START + timedelta(hours=2),
    )

    assert evidence.decision == "rejected"
    assert any(not gate.passed for gate in evidence.gates)
    assert any(gate.reason_code == "metric_below_threshold" for gate in evidence.gates)
    assert evidence.promotion_state == "unpromoted"
    assert evidence.execution_authority is False


def test_learner_qualification_fails_closed_for_missing_metric_or_windows(tmp_path: Path) -> None:
    candidate, output, training_evidence, review = _fixtures(tmp_path)
    missing_metric = review.model_copy(
        update={
            "windows": tuple(
                window.model_copy(
                    update={
                        "metrics": (
                            LearnerQualityReviewMetric(
                                metric_id="different_metric", value=Decimal("1")
                            ),
                        )
                    }
                )
                for window in review.windows
            ),
            "review_hash": "0" * 64,
        }
    )
    with pytest.raises(DataQualityError, match="quality review hash"):
        build_learner_qualification_evidence(
            training_evidence=training_evidence,
            quality_review=missing_metric,
            output_artifact=output,
            candidate=candidate,
            policy=_policy(),
            evaluated_at=START,
        )

    evidence = build_learner_qualification_evidence(
        training_evidence=training_evidence,
        quality_review=review,
        output_artifact=output,
        candidate=candidate,
        policy=_policy(minimum_windows=3),
        evaluated_at=START,
    )
    assert evidence.decision == "rejected"
    assert any(gate.gate_id == "minimum_windows" and not gate.passed for gate in evidence.gates)


def test_learner_qualification_rejects_binding_drift_before_decision(tmp_path: Path) -> None:
    candidate, output, training_evidence, review = _fixtures(tmp_path)
    tampered = review.model_copy(update={"candidate_id": "cand-other", "review_hash": "0" * 64})

    with pytest.raises(DataQualityError, match="quality review hash"):
        build_learner_qualification_evidence(
            training_evidence=training_evidence,
            quality_review=tampered,
            output_artifact=output,
            candidate=candidate,
            policy=_policy(),
            evaluated_at=START,
        )


def test_learner_qualification_persistence_is_write_once_and_decimal_safe(tmp_path: Path) -> None:
    candidate, output, training_evidence, review = _fixtures(tmp_path)
    evidence = build_learner_qualification_evidence(
        training_evidence=training_evidence,
        quality_review=review,
        output_artifact=output,
        candidate=candidate,
        policy=_policy(),
        evaluated_at=START,
    )
    path = tmp_path / "qualification.json"

    assert (
        write_learner_qualification_evidence(
            path,
            evidence,
            training_evidence=training_evidence,
            quality_review=review,
            output_artifact=output,
            candidate=candidate,
            policy=_policy(),
        )
        == evidence
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["gates"][1]["threshold"] == "0.50"
    assert (
        read_learner_qualification_evidence(
            path,
            training_evidence=training_evidence,
            quality_review=review,
            output_artifact=output,
            candidate=candidate,
            policy=_policy(),
        )
        == evidence
    )
    assert (
        write_learner_qualification_evidence(
            path,
            evidence,
            training_evidence=training_evidence,
            quality_review=review,
            output_artifact=output,
            candidate=candidate,
            policy=_policy(),
        )
        == evidence
    )

    conflict = evidence.model_copy(update={"evaluated_at": START + timedelta(minutes=1)})
    with pytest.raises(DomainViolation, match="immutable"):
        write_learner_qualification_evidence(
            path,
            conflict,
            training_evidence=training_evidence,
            quality_review=review,
            output_artifact=output,
            candidate=candidate,
            policy=_policy(),
        )

    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '"qualification_hash": "', '"qualification_hash": "0'
        ),
        encoding="utf-8",
    )
    with pytest.raises(DomainViolation, match="hash"):
        read_learner_qualification_evidence(
            path,
            training_evidence=training_evidence,
            quality_review=review,
            output_artifact=output,
            candidate=candidate,
            policy=_policy(),
        )


def test_learner_qualification_policy_rejects_nonfinite_and_duplicate_gates() -> None:
    with pytest.raises(ValidationError, match="finite"):
        LearnerQualificationPolicyGate(
            metric_id="holdout_score", comparator="gte", threshold=Decimal("NaN")
        )

    with pytest.raises(ValidationError, match="sorted and unique"):
        LearnerQualificationPolicy(
            policy_id="learner-quality-policy-v1",
            minimum_windows=1,
            gates=(
                LearnerQualificationPolicyGate(
                    metric_id="holdout_score", comparator="gte", threshold=Decimal("0.5")
                ),
                LearnerQualificationPolicyGate(
                    metric_id="holdout_score", comparator="gte", threshold=Decimal("0.6")
                ),
            ),
        )
