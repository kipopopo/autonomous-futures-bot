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
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.learner_artifacts import (
    LearnerArtifact,
    build_learner_artifact,
    write_learner_artifact,
)
from autonomous_futures.research.learner_inputs import LearnerInputMaterializer
from autonomous_futures.research.learner_runs import (
    LearnerRun,
    prepare_learner_run,
    write_learner_run,
)
from autonomous_futures.research.learner_training import (
    LearnerTrainingOutput,
    execute_learner_training,
)
from autonomous_futures.research.learner_training_evidence import (
    LearnerTrainingEvidence,
    build_learner_training_evidence,
    read_learner_training_evidence,
    write_learner_training_evidence,
)
from autonomous_futures.research.learner_training_pipeline import (
    execute_learner_training_with_evidence,
)

START = datetime(2026, 8, 8, 12, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
DATASET_REGISTRY_HASH = "b" * 64


def _candidate():
    candidate_id = "cand-learner-evidence-001"
    strategy = StrategySpec(
        dsl_version=1,
        strategy_id=candidate_id,
        family="experimental",
        universe=StrategyUniverse(
            symbols=("BTCUSDT", "ETHUSDT"), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="returns", lookback=2, shift=1),),
        entry=EntryExit(long="returns > 0", short="returns < 0"),
        exit=EntryExit(long="returns < 0", short="returns > 0"),
        vetoes=("regime_trend == 0",),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        creator_run_id="creator-run-learner-evidence",
        research_seed=53,
        created_at=START,
    )


def _source_learner(candidate) -> LearnerArtifact:
    model_bytes = b"source-learner-model"
    return build_learner_artifact(
        candidate=candidate,
        learner_id="learner-evidence-001",
        learner_run_id="learner-source-run-001",
        learner_version="learner-source-v1",
        model_family="cached_classifier",
        feature_ids=("returns",),
        training_window_start=START - timedelta(days=7),
        training_window_end=START,
        model_artifact_ref="source.bin",
        model_artifact_hash=hashlib.sha256(model_bytes).hexdigest(),
        created_at=START,
    )


def _primary(start: datetime = START) -> pd.DataFrame:
    timestamps = [start + timedelta(minutes=5 * index) for index in range(7)]
    closes = [Decimal(str(100 + index)) for index in range(7)]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": [value + Decimal("1") for value in closes],
            "low": [value - Decimal("1") for value in closes],
            "close": closes,
        }
    )


def _context(start: datetime = START) -> pd.DataFrame:
    timestamps = [start + timedelta(minutes=15 * index) for index in range(3)]
    closes = [Decimal("110"), Decimal("120"), Decimal("130")]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": [value + Decimal("1") for value in closes],
            "low": [value - Decimal("1") for value in closes],
            "close": closes,
            "close_time": [
                timestamp + timedelta(minutes=15) - timedelta(milliseconds=1)
                for timestamp in timestamps
            ],
        }
    )


def _prepared(tmp_path: Path):
    candidate = _candidate()
    learner = _source_learner(candidate)
    materializer = LearnerInputMaterializer(learner=learner, candidate=candidate)
    windows = (
        materializer.materialize(
            primary=_primary(), context=_context(), symbol="BTCUSDT", input_id="input-btc"
        ),
        materializer.materialize(
            primary=_primary(), context=_context(), symbol="ETHUSDT", input_id="input-eth"
        ),
    )
    run = prepare_learner_run(
        learner=learner,
        windows=windows,
        run_id="run-learner-evidence-001",
        prepared_at=datetime(2026, 8, 8, 13, tzinfo=UTC),
    )
    return candidate, learner, windows, run


def _persist_source_and_run(
    tmp_path: Path, candidate, learner: LearnerArtifact, run: LearnerRun
) -> tuple[Path, Path]:
    model_root = tmp_path / "models"
    model_root.mkdir(parents=True)
    (model_root / learner.model_artifact_ref).write_bytes(b"source-learner-model")
    artifact_root = tmp_path / "artifacts"
    source_path = artifact_root / "source" / "learner.json"
    write_learner_artifact(source_path, learner, model_root=model_root)
    run_root = tmp_path / "runs"
    run_path = run_root / "run.json"
    run_path.parent.mkdir(parents=True)
    write_learner_run(run_path, run)
    return source_path, run_path


def _persist_source_only(tmp_path: Path, learner: LearnerArtifact) -> Path:
    model_root = tmp_path / "models"
    model_root.mkdir(parents=True)
    (model_root / learner.model_artifact_ref).write_bytes(b"source-learner-model")
    source_path = tmp_path / "artifacts" / "source" / "learner.json"
    write_learner_artifact(source_path, learner, model_root=model_root)
    return source_path


def _persist_output(tmp_path: Path, candidate, learner, windows, run) -> LearnerArtifact:
    return execute_learner_training(
        prepared_run=run,
        learner=learner,
        candidate=candidate,
        windows=windows,
        model_root=tmp_path / "models",
        artifact_path=tmp_path / "artifacts" / "trained" / "learner.json",
        trainer=lambda _run, _frames: LearnerTrainingOutput(
            model_artifact_ref="trained/model.bin",
            model_family="explicit_cached_trainer",
            learner_version="learner-output-v1",
            model_bytes=b"trained-model-output-v1",
        ),
        created_at=datetime(2026, 8, 8, 14, tzinfo=UTC),
    )


def test_completed_training_evidence_is_bound_and_verified(tmp_path: Path) -> None:
    candidate, learner, windows, run = _prepared(tmp_path)
    source_path, run_path = _persist_source_and_run(tmp_path, candidate, learner, run)
    output = _persist_output(tmp_path, candidate, learner, windows, run)
    evidence = build_learner_training_evidence(
        prepared_run=run,
        source_learner=learner,
        output_artifact=output,
        candidate=candidate,
        source_learner_artifact_ref="source/learner.json",
        prepared_run_ref="run.json",
        output_artifact_ref="trained/learner.json",
        created_at=datetime(2026, 8, 8, 15, tzinfo=UTC),
    )

    assert isinstance(evidence, LearnerTrainingEvidence)
    assert evidence.status == "completed"
    assert evidence.prepared_run_hash == run.run_hash
    assert evidence.source_learner_artifact_hash == learner.artifact_hash
    assert evidence.output_artifact_hash == output.artifact_hash
    assert evidence.training_metrics is None
    assert evidence.data_source == "cached_only"
    assert evidence.promotion_state == "unpromoted"
    assert evidence.execution_authority is False

    evidence_path = tmp_path / "evidence" / "training.json"
    persisted = write_learner_training_evidence(
        evidence_path,
        evidence,
        run_root=run_path.parent,
        artifact_root=tmp_path / "artifacts",
        model_root=tmp_path / "models",
        candidate=candidate,
    )
    assert persisted == evidence
    assert (
        read_learner_training_evidence(
            evidence_path,
            run_root=run_path.parent,
            artifact_root=tmp_path / "artifacts",
            model_root=tmp_path / "models",
            candidate=candidate,
        )
        == evidence
    )


def test_training_evidence_rejects_binding_drift_and_tampering(tmp_path: Path) -> None:
    candidate, learner, windows, run = _prepared(tmp_path)
    source_path, run_path = _persist_source_and_run(tmp_path, candidate, learner, run)
    output = _persist_output(tmp_path, candidate, learner, windows, run)
    evidence = build_learner_training_evidence(
        prepared_run=run,
        source_learner=learner,
        output_artifact=output,
        candidate=candidate,
        source_learner_artifact_ref="source/learner.json",
        prepared_run_ref="run.json",
        output_artifact_ref="trained/learner.json",
        created_at=datetime(2026, 8, 8, 15, tzinfo=UTC),
    )
    evidence_path = tmp_path / "evidence" / "training.json"
    write_learner_training_evidence(
        evidence_path,
        evidence,
        run_root=run_path.parent,
        artifact_root=tmp_path / "artifacts",
        model_root=tmp_path / "models",
        candidate=candidate,
    )

    (tmp_path / "models" / "trained" / "model.bin").write_bytes(b"tampered")
    with pytest.raises(DomainViolation, match="training evidence"):
        read_learner_training_evidence(
            evidence_path,
            run_root=run_path.parent,
            artifact_root=tmp_path / "artifacts",
            model_root=tmp_path / "models",
            candidate=candidate,
        )

    shifted = run.model_copy(update={"run_hash": "c" * 64})
    with pytest.raises(DataQualityError, match="prepared run"):
        build_learner_training_evidence(
            prepared_run=shifted,
            source_learner=learner,
            output_artifact=output,
            candidate=candidate,
            source_learner_artifact_ref="source/learner.json",
            prepared_run_ref="run.json",
            output_artifact_ref="trained/learner.json",
            created_at=datetime(2026, 8, 8, 15, tzinfo=UTC),
        )


def test_training_evidence_is_write_once_and_rejects_unsafe_refs(tmp_path: Path) -> None:
    candidate, learner, windows, run = _prepared(tmp_path)
    source_path, run_path = _persist_source_and_run(tmp_path, candidate, learner, run)
    output = _persist_output(tmp_path, candidate, learner, windows, run)
    evidence = build_learner_training_evidence(
        prepared_run=run,
        source_learner=learner,
        output_artifact=output,
        candidate=candidate,
        source_learner_artifact_ref="source/learner.json",
        prepared_run_ref="run.json",
        output_artifact_ref="trained/learner.json",
        created_at=datetime(2026, 8, 8, 15, tzinfo=UTC),
    )
    path = tmp_path / "evidence" / "training.json"
    kwargs = {
        "run_root": run_path.parent,
        "artifact_root": tmp_path / "artifacts",
        "model_root": tmp_path / "models",
        "candidate": candidate,
    }
    assert write_learner_training_evidence(path, evidence, **kwargs) == evidence
    assert write_learner_training_evidence(path, evidence, **kwargs) == evidence

    changed = evidence.model_copy(update={"created_at": datetime(2026, 8, 8, 16, tzinfo=UTC)})
    with pytest.raises(DomainViolation, match="immutable"):
        write_learner_training_evidence(path, changed, **kwargs)

    with pytest.raises(DataQualityError, match="relative POSIX"):
        build_learner_training_evidence(
            prepared_run=run,
            source_learner=learner,
            output_artifact=output,
            candidate=candidate,
            source_learner_artifact_ref="../source.json",
            prepared_run_ref="run.json",
            output_artifact_ref="trained/learner.json",
            created_at=datetime(2026, 8, 8, 15, tzinfo=UTC),
        )


def test_explicit_training_pipeline_persists_run_output_and_evidence(tmp_path: Path) -> None:
    candidate, learner, windows, run = _prepared(tmp_path)
    _persist_source_only(tmp_path, learner)
    observed: dict[str, object] = {}

    def trainer(callback_run, frames):
        observed["calls"] = int(observed.get("calls", 0)) + 1
        observed["run_id"] = callback_run.run_id
        observed["symbols"] = tuple(frames)
        return LearnerTrainingOutput(
            model_artifact_ref="trained/model.bin",
            model_family="explicit_cached_trainer",
            learner_version="learner-output-v1",
            model_bytes=b"pipeline-trained-model",
        )

    evidence = execute_learner_training_with_evidence(
        prepared_run=run,
        source_learner=learner,
        candidate=candidate,
        windows=windows,
        trainer=trainer,
        run_root=tmp_path / "runs",
        prepared_run_ref="run.json",
        artifact_root=tmp_path / "artifacts",
        source_learner_artifact_ref="source/learner.json",
        output_artifact_ref="trained/learner.json",
        model_root=tmp_path / "models",
        evidence_root=tmp_path / "evidence",
        evidence_ref="training.json",
        artifact_created_at=datetime(2026, 8, 8, 14, tzinfo=UTC),
        evidence_created_at=datetime(2026, 8, 8, 15, tzinfo=UTC),
    )
    repeated = execute_learner_training_with_evidence(
        prepared_run=run,
        source_learner=learner,
        candidate=candidate,
        windows=windows,
        trainer=trainer,
        run_root=tmp_path / "runs",
        prepared_run_ref="run.json",
        artifact_root=tmp_path / "artifacts",
        source_learner_artifact_ref="source/learner.json",
        output_artifact_ref="trained/learner.json",
        model_root=tmp_path / "models",
        evidence_root=tmp_path / "evidence",
        evidence_ref="training.json",
        artifact_created_at=datetime(2026, 8, 8, 14, tzinfo=UTC),
        evidence_created_at=datetime(2026, 8, 8, 15, tzinfo=UTC),
    )

    assert observed == {
        "calls": 1,
        "run_id": run.run_id,
        "symbols": ("BTCUSDT", "ETHUSDT"),
    }
    assert repeated == evidence
    assert evidence.status == "completed"
    assert evidence.prepared_run_ref == "run.json"
    assert evidence.source_learner_artifact_ref == "source/learner.json"
    assert evidence.output_artifact_ref == "trained/learner.json"
    assert (tmp_path / "runs" / "run.json").exists()
    assert (tmp_path / "artifacts" / "trained" / "learner.json").exists()
    assert (tmp_path / "evidence" / "training.json").exists()
    assert (
        read_learner_training_evidence(
            tmp_path / "evidence" / "training.json",
            run_root=tmp_path / "runs",
            artifact_root=tmp_path / "artifacts",
            model_root=tmp_path / "models",
            candidate=candidate,
        )
        == evidence
    )


def test_explicit_training_pipeline_fails_closed_before_run_persistence(
    tmp_path: Path,
) -> None:
    candidate, learner, windows, run = _prepared(tmp_path)

    with pytest.raises(DataQualityError, match="source learner artifact"):
        execute_learner_training_with_evidence(
            prepared_run=run,
            source_learner=learner,
            candidate=candidate,
            windows=windows,
            trainer=lambda _run, _frames: LearnerTrainingOutput(
                model_artifact_ref="trained/model.bin",
                model_family="explicit_cached_trainer",
                learner_version="learner-output-v1",
                model_bytes=b"pipeline-trained-model",
            ),
            run_root=tmp_path / "runs",
            prepared_run_ref="run.json",
            artifact_root=tmp_path / "artifacts",
            source_learner_artifact_ref="source/learner.json",
            output_artifact_ref="trained/learner.json",
            model_root=tmp_path / "models",
            evidence_root=tmp_path / "evidence",
            evidence_ref="training.json",
            artifact_created_at=datetime(2026, 8, 8, 14, tzinfo=UTC),
            evidence_created_at=datetime(2026, 8, 8, 15, tzinfo=UTC),
        )

    assert not (tmp_path / "runs" / "run.json").exists()
