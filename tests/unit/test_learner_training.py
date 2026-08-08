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
    read_learner_artifact,
)
from autonomous_futures.research.learner_inputs import LearnerInputMaterializer
from autonomous_futures.research.learner_runs import prepare_learner_run
from autonomous_futures.research.learner_training import (
    LearnerTrainingOutput,
    execute_learner_training,
)

START = datetime(2026, 8, 8, 12, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
DATASET_REGISTRY_HASH = "b" * 64


def _candidate():
    candidate_id = "cand-learner-training-001"
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
        creator_run_id="creator-run-learner-training",
        research_seed=47,
        created_at=START,
    )


def _learner(candidate) -> LearnerArtifact:
    model_bytes = b"source-learner-model"
    return build_learner_artifact(
        candidate=candidate,
        learner_id="learner-training-001",
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
    learner = _learner(candidate)
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
        run_id="run-learner-training-001",
        prepared_at=datetime(2026, 8, 8, 13, tzinfo=UTC),
    )
    return candidate, learner, windows, run


def test_explicit_trainer_writes_verified_artifact_and_isolates_frames(tmp_path: Path) -> None:
    candidate, learner, windows, run = _prepared(tmp_path)
    observed: dict[str, object] = {}
    model_bytes = b"trained-model-output-v1"

    def trainer(callback_run, frames):
        observed["run_id"] = callback_run.run_id
        observed["symbols"] = tuple(frames)
        frames["BTCUSDT"].loc[0, "close"] = Decimal("999999")
        return LearnerTrainingOutput(
            model_artifact_ref="trained/model.bin",
            model_family="explicit_cached_trainer",
            learner_version="learner-output-v1",
            model_bytes=model_bytes,
        )

    artifact = execute_learner_training(
        prepared_run=run,
        learner=learner,
        candidate=candidate,
        windows=windows,
        model_root=tmp_path / "models",
        artifact_path=tmp_path / "artifacts" / "learner.json",
        trainer=trainer,
        created_at=datetime(2026, 8, 8, 14, tzinfo=UTC),
    )

    assert observed == {"run_id": run.run_id, "symbols": ("BTCUSDT", "ETHUSDT")}
    assert isinstance(artifact, LearnerArtifact)
    assert artifact.state == "testing"
    assert artifact.learner_run_id == run.run_id
    assert artifact.model_artifact_ref == "trained/model.bin"
    assert artifact.model_artifact_hash == hashlib.sha256(model_bytes).hexdigest()
    assert artifact.model_family == "explicit_cached_trainer"
    assert artifact.learner_version == "learner-output-v1"
    assert artifact.execution_authority is False
    assert windows[0].frame.loc[0, "close"] == Decimal("100")
    assert (
        read_learner_artifact(
            tmp_path / "artifacts" / "learner.json", model_root=tmp_path / "models"
        )
        == artifact
    )


def test_identical_output_is_idempotent_and_conflicting_model_is_rejected(tmp_path: Path) -> None:
    candidate, learner, windows, run = _prepared(tmp_path)
    output = LearnerTrainingOutput(
        model_artifact_ref="trained/model.bin",
        model_family="explicit_cached_trainer",
        learner_version="learner-output-v1",
        model_bytes=b"stable-model",
    )

    def trainer(_run, _frames):
        return output

    first = execute_learner_training(
        prepared_run=run,
        learner=learner,
        candidate=candidate,
        windows=windows,
        model_root=tmp_path / "models",
        artifact_path=tmp_path / "artifacts" / "learner.json",
        trainer=trainer,
        created_at=START,
    )
    second = execute_learner_training(
        prepared_run=run,
        learner=learner,
        candidate=candidate,
        windows=windows,
        model_root=tmp_path / "models",
        artifact_path=tmp_path / "artifacts" / "learner.json",
        trainer=trainer,
        created_at=START,
    )
    assert second == first

    def conflicting_trainer(_run, _frames):
        return output.__class__(
            model_artifact_ref=output.model_artifact_ref,
            model_family=output.model_family,
            learner_version=output.learner_version,
            model_bytes=b"different-model",
        )

    with pytest.raises(DomainViolation, match="model artifact is immutable"):
        execute_learner_training(
            prepared_run=run,
            learner=learner,
            candidate=candidate,
            windows=windows,
            model_root=tmp_path / "models",
            artifact_path=tmp_path / "artifacts" / "learner.json",
            trainer=conflicting_trainer,
            created_at=START,
        )


def test_training_boundary_rejects_invalid_output_and_run_binding(tmp_path: Path) -> None:
    candidate, learner, windows, run = _prepared(tmp_path)

    def invalid_trainer(_run, _frames):
        return LearnerTrainingOutput(
            model_artifact_ref="../escape.bin",
            model_family="explicit_cached_trainer",
            learner_version="learner-output-v1",
            model_bytes=b"model",
        )

    with pytest.raises(DataQualityError, match="model_artifact_ref"):
        execute_learner_training(
            prepared_run=run,
            learner=learner,
            candidate=candidate,
            windows=windows,
            model_root=tmp_path / "models",
            artifact_path=tmp_path / "artifacts" / "learner.json",
            trainer=invalid_trainer,
            created_at=START,
        )

    shifted = run.model_copy(update={"learner_artifact_hash": "c" * 64})
    with pytest.raises(DataQualityError, match="prepared run binding"):
        execute_learner_training(
            prepared_run=shifted,
            learner=learner,
            candidate=candidate,
            windows=windows,
            model_root=tmp_path / "models",
            artifact_path=tmp_path / "artifacts" / "learner.json",
            trainer=lambda _run, _frames: LearnerTrainingOutput(
                model_artifact_ref="trained/model.bin",
                model_family="explicit_cached_trainer",
                learner_version="learner-output-v1",
                model_bytes=b"model",
            ),
            created_at=START,
        )
