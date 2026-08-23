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
from autonomous_futures.research.creator_failure_feedback import CreatorQualificationFailureFeedback
from autonomous_futures.research.creator_feedback_training import (
    execute_creator_feedback_training_with_evidence,
)
from autonomous_futures.research.learner_artifacts import (
    build_learner_artifact,
    write_learner_artifact,
)
from autonomous_futures.research.learner_critic import LearnerCriticRequest, parse_learner_critique
from autonomous_futures.research.learner_critic_evidence import build_learner_critique_evidence
from autonomous_futures.research.learner_critic_training import (
    execute_learner_critic_training_with_evidence,
)
from autonomous_futures.research.learner_inputs import LearnerInputMaterializer
from autonomous_futures.research.learner_runs import prepare_learner_run
from autonomous_futures.research.learner_training import LearnerTrainingOutput
from autonomous_futures.research.learner_training_evidence import read_learner_training_evidence

START = datetime(2026, 8, 8, 12, tzinfo=UTC)
BUNDLE = "a" * 64
REGISTRY = "b" * 64


def _candidate():
    candidate_id = "cand-feedback-training-001"
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=StrategySpec(
            dsl_version=1,
            strategy_id=candidate_id,
            family="experimental",
            universe=StrategyUniverse(
                symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
            ),
            features=(FeatureRef(name="returns", lookback=2, shift=1),),
            entry=EntryExit(long="returns > 0", short="returns < 0"),
            exit=EntryExit(long="returns < 0", short="returns > 0"),
            vetoes=("testing_only_no_promotion",),
        ),
        bundle_hash=BUNDLE,
        dataset_registry_hash=REGISTRY,
        creator_run_id="creator-feedback-training",
        research_seed=1,
        created_at=START,
    )


def _feedback(candidate):
    return CreatorQualificationFailureFeedback.model_validate(
        {
            "candidate_id": candidate.candidate_id,
            "candidate_artifact_hash": candidate.artifact_hash,
            "bundle_hash": BUNDLE,
            "dataset_registry_hash": REGISTRY,
            "qualification_hash": "c" * 64,
            "qualification_policy_id": "policy-creator-001",
            "failed_gates": [
                {
                    "gate_id": "oos_profit_factor_min",
                    "passed": False,
                    "observed": "0.5",
                    "threshold": "1",
                    "comparator": "gte",
                    "reason_code": "oos_profit_factor_below_threshold",
                }
            ],
            "failure_reason_codes": ["oos_profit_factor_below_threshold"],
        }
    )


def _learner(candidate, model_root: Path):
    model_bytes = b"source-model"
    (model_root / "source.bin").parent.mkdir(parents=True, exist_ok=True)
    (model_root / "source.bin").write_bytes(model_bytes)
    return build_learner_artifact(
        candidate=candidate,
        learner_id="learner-feedback-001",
        learner_run_id="learner-feedback-source-001",
        learner_version="source-v1",
        model_family="feedback_critic",
        feature_ids=("returns",),
        training_window_start=START - timedelta(days=7),
        training_window_end=START,
        model_artifact_ref="source.bin",
        model_artifact_hash=hashlib.sha256(model_bytes).hexdigest(),
        created_at=START,
    )


def _frames(candidate, learner):
    primary = pd.DataFrame(
        {
            "timestamp": [START + timedelta(minutes=5 * i) for i in range(7)],
            "open": [Decimal(str(100 + i)) for i in range(7)],
            "high": [Decimal(str(101 + i)) for i in range(7)],
            "low": [Decimal(str(99 + i)) for i in range(7)],
            "close": [Decimal(str(100 + i)) for i in range(7)],
        }
    )
    context = pd.DataFrame(
        {
            "timestamp": [START + timedelta(minutes=15 * i) for i in range(3)],
            "open": [Decimal("110"), Decimal("120"), Decimal("130")],
            "high": [Decimal("111"), Decimal("121"), Decimal("131")],
            "low": [Decimal("109"), Decimal("119"), Decimal("129")],
            "close": [Decimal("110"), Decimal("120"), Decimal("130")],
            "close_time": [
                START + timedelta(minutes=15 * (i + 1)) - timedelta(milliseconds=1)
                for i in range(3)
            ],
        }
    )
    window = LearnerInputMaterializer(learner=learner, candidate=candidate).materialize(
        primary=primary, context=context, symbol="BTCUSDT", input_id="input-btc"
    )
    return (window,)


def test_feedback_aware_training_passes_feedback_to_existing_evidence_pipeline(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    model_root = tmp_path / "models"
    learner = _learner(candidate, model_root)
    windows = _frames(candidate, learner)
    prepared = prepare_learner_run(
        learner=learner,
        windows=windows,
        run_id="run-feedback-training-001",
        prepared_at=START + timedelta(hours=1),
    )
    source_path = tmp_path / "artifacts" / "source.json"
    write_learner_artifact(source_path, learner, model_root=model_root)
    feedback = _feedback(candidate)
    observed: list[tuple[str, str]] = []

    def trainer(received_feedback, run, frames):
        observed.append((received_feedback.candidate_id, run.run_id))
        assert tuple(frames) == ("BTCUSDT",)
        return LearnerTrainingOutput(
            model_artifact_ref="trained/model.bin",
            model_family="feedback_critic",
            learner_version="trained-v1",
            model_bytes=b"trained-feedback-model",
        )

    evidence = execute_creator_feedback_training_with_evidence(
        feedback=feedback,
        prepared_run=prepared,
        source_learner=learner,
        candidate=candidate,
        windows=windows,
        trainer=trainer,
        run_root=tmp_path / "runs",
        prepared_run_ref="prepared.json",
        artifact_root=tmp_path / "artifacts",
        source_learner_artifact_ref="source.json",
        output_artifact_ref="trained.json",
        model_root=model_root,
        evidence_root=tmp_path / "evidence",
        evidence_ref="training.json",
        artifact_created_at=START + timedelta(hours=2),
        evidence_created_at=START + timedelta(hours=2),
    )

    assert observed == [(candidate.candidate_id, prepared.run_id)]
    assert evidence.candidate_id == candidate.candidate_id
    assert evidence.promotion_state == "unpromoted"
    assert evidence.execution_authority is False
    assert (
        read_learner_training_evidence(
            tmp_path / "evidence" / "training.json",
            run_root=tmp_path / "runs",
            artifact_root=tmp_path / "artifacts",
            model_root=model_root,
            candidate=candidate,
        )
        == evidence
    )


def test_feedback_binding_mismatch_blocks_trainer_before_filesystem_work(tmp_path: Path) -> None:
    candidate = _candidate()
    model_root = tmp_path / "models"
    learner = _learner(candidate, model_root)
    windows = _frames(candidate, learner)
    prepared = prepare_learner_run(
        learner=learner,
        windows=windows,
        run_id="run-feedback-training-001",
        prepared_at=START + timedelta(hours=1),
    )
    feedback = _feedback(candidate).model_copy(update={"candidate_id": "cand-other"})
    called = False

    def trainer(*_args):
        nonlocal called
        called = True
        raise AssertionError("trainer must not run")

    with pytest.raises(DataQualityError, match="feedback candidate binding"):
        execute_creator_feedback_training_with_evidence(
            feedback=feedback,
            prepared_run=prepared,
            source_learner=learner,
            candidate=candidate,
            windows=windows,
            trainer=trainer,
            run_root=tmp_path / "runs",
            prepared_run_ref="prepared.json",
            artifact_root=tmp_path / "artifacts",
            source_learner_artifact_ref="source.json",
            output_artifact_ref="trained.json",
            model_root=model_root,
            evidence_root=tmp_path / "evidence",
            evidence_ref="training.json",
            artifact_created_at=START + timedelta(hours=2),
            evidence_created_at=START + timedelta(hours=2),
        )
    assert called is False
    assert not (tmp_path / "runs").exists()


def test_persisted_critic_evidence_feeds_existing_injected_training_pipeline(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    model_root = tmp_path / "models"
    learner = _learner(candidate, model_root)
    windows = _frames(candidate, learner)
    prepared = prepare_learner_run(
        learner=learner,
        windows=windows,
        run_id="run-feedback-training-001",
        prepared_at=START + timedelta(hours=1),
    )
    source_path = tmp_path / "artifacts" / "source.json"
    write_learner_artifact(source_path, learner, model_root=model_root)
    feedback = _feedback(candidate)
    request = LearnerCriticRequest(
        research_run_id="run-feedback-training-001",
        candidate_id=candidate.candidate_id,
        candidate_artifact_hash=candidate.artifact_hash,
        feedback=feedback,
        input_evidence_refs=("feedback/hash", "qualification/hash"),
        output_schema_id="learner-critic-v1",
        attempt=1,
    )
    evidence = build_learner_critique_evidence(
        request=request,
        critique=parse_learner_critique(
            {
                "review_id": "review-feedback-training-001",
                "research_run_id": request.research_run_id,
                "candidate_id": candidate.candidate_id,
                "decision": "revise",
                "failure_reason_codes": list(feedback.failure_reason_codes),
                "revision_actions": ["change_entry_threshold"],
            }
        ),
        evidence_id="critic-evidence-training-001",
        created_at=START + timedelta(hours=2),
    )
    observed: list[tuple[str, str]] = []

    def trainer(received_evidence, callback_run, frames):
        observed.append((received_evidence.evidence_id, callback_run.run_id))
        assert tuple(frames) == ("BTCUSDT",)
        return LearnerTrainingOutput(
            model_artifact_ref="trained/model.bin",
            model_family="critic_guided_trainer",
            learner_version="trained-v1",
            model_bytes=b"critic-guided-model",
        )

    result = execute_learner_critic_training_with_evidence(
        evidence=evidence,
        prepared_run=prepared,
        source_learner=learner,
        candidate=candidate,
        windows=windows,
        trainer=trainer,
        run_root=tmp_path / "runs",
        prepared_run_ref="prepared.json",
        artifact_root=tmp_path / "artifacts",
        source_learner_artifact_ref="source.json",
        output_artifact_ref="trained.json",
        model_root=model_root,
        evidence_root=tmp_path / "training-evidence",
        evidence_ref="training.json",
        artifact_created_at=START + timedelta(hours=3),
        evidence_created_at=START + timedelta(hours=3),
    )

    assert observed == [(evidence.evidence_id, prepared.run_id)]
    assert result.candidate_id == candidate.candidate_id
    assert result.promotion_state == "unpromoted"
