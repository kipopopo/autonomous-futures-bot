from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pandas as pd

from ..data.parquet import DataQualityError
from .causal_evaluation import materialize_causal_context
from .creator_artifacts import CreatorCandidateArtifact
from .feature_signals import materialize_causal_features
from .learner_artifacts import (
    LearnerArtifact,
    build_learner_artifact,
    write_learner_artifact,
)
from .learner_inputs import LearnerInputWindow, LearnerInputWindowSpec
from .learner_runs import LearnerRun, prepare_learner_run, write_learner_run
from .learner_training import (
    LearnerTrainingOutput,
    _write_model_bytes_once,
)

LearnerBootstrapTrainer = Callable[
    [CreatorCandidateArtifact, dict[str, pd.DataFrame]], LearnerTrainingOutput
]


@dataclass(frozen=True, slots=True)
class LearnerBootstrapResult:
    learner: LearnerArtifact
    prepared_run: LearnerRun
    input_windows: tuple[LearnerInputWindow, ...]


def _materialize_frames(
    candidate: CreatorCandidateArtifact,
    primary_frames: Mapping[str, pd.DataFrame],
    context_frames: Mapping[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    symbols = candidate.strategy.universe.symbols
    if tuple(sorted(primary_frames)) != symbols:
        raise DataQualityError("primary frames must match candidate universe")
    if tuple(sorted(context_frames)) != symbols:
        raise DataQualityError("context frames must match candidate universe")

    materialized: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        causal_context = materialize_causal_context(primary_frames[symbol], context_frames[symbol])
        materialized[symbol] = materialize_causal_features(candidate, causal_context)

    first = materialized[symbols[0]]
    first_start = pd.Timestamp(first["timestamp"].iloc[0]).to_pydatetime()
    first_end = pd.Timestamp(first["timestamp"].iloc[-1]).to_pydatetime() + timedelta(minutes=5)
    for frame in materialized.values():
        start = pd.Timestamp(frame["timestamp"].iloc[0]).to_pydatetime()
        end = pd.Timestamp(frame["timestamp"].iloc[-1]).to_pydatetime() + timedelta(minutes=5)
        if start != first_start or end != first_end:
            raise DataQualityError("learner frames must share one training window")
    return materialized


def bootstrap_learner_training(
    *,
    candidate: CreatorCandidateArtifact,
    primary_frames: Mapping[str, pd.DataFrame],
    context_frames: Mapping[str, pd.DataFrame],
    learner_id: str,
    run_id: str,
    trainer: LearnerBootstrapTrainer,
    model_root: Path,
    learner_artifact_path: Path,
    run_path: Path,
    created_at: datetime,
    prepared_at: datetime,
) -> LearnerBootstrapResult:
    """Train one explicit cached-only learner and persist its prepared provenance."""
    if candidate.state != "testing":
        raise DataQualityError("only testing candidates may bootstrap a learner")

    materialized = _materialize_frames(candidate, primary_frames, context_frames)
    trainer_frames = {symbol: frame.copy(deep=True) for symbol, frame in materialized.items()}
    output = trainer(candidate, trainer_frames)
    if not isinstance(output, LearnerTrainingOutput):
        raise DataQualityError("trainer must return LearnerTrainingOutput")

    symbols = candidate.strategy.universe.symbols
    feature_ids = tuple(sorted(feature.name for feature in candidate.strategy.features))
    first_frame = materialized[symbols[0]]
    time_start = pd.Timestamp(first_frame["timestamp"].iloc[0]).to_pydatetime()
    time_end = pd.Timestamp(first_frame["timestamp"].iloc[-1]).to_pydatetime() + timedelta(
        minutes=5
    )
    model_hash = sha256(output.model_bytes).hexdigest()
    learner = build_learner_artifact(
        candidate=candidate,
        learner_id=learner_id,
        learner_run_id=run_id,
        learner_version=output.learner_version,
        model_family=output.model_family,
        feature_ids=feature_ids,
        training_window_start=time_start,
        training_window_end=time_end,
        model_artifact_ref=output.model_artifact_ref,
        model_artifact_hash=model_hash,
        created_at=created_at,
    )

    model_path, model_created = _write_model_bytes_once(
        model_root, output.model_artifact_ref, output.model_bytes
    )
    try:
        persisted_learner = write_learner_artifact(
            learner_artifact_path, learner, model_root=model_root
        )
    except Exception:
        if model_created:
            model_path.unlink(missing_ok=True)
        raise

    windows: list[LearnerInputWindow] = []
    for symbol in symbols:
        frame = materialized[symbol].copy(deep=True)
        spec = LearnerInputWindowSpec(
            input_id=f"input-{symbol.lower()}",
            learner_id=persisted_learner.learner_id,
            learner_artifact_hash=persisted_learner.artifact_hash,
            candidate_id=persisted_learner.candidate_id,
            candidate_artifact_hash=persisted_learner.candidate_artifact_hash,
            symbol=symbol,
            bundle_hash=persisted_learner.bundle_hash,
            dataset_registry_hash=persisted_learner.dataset_registry_hash,
            feature_ids=persisted_learner.feature_ids,
            time_start=time_start,
            time_end=time_end,
            row_count=len(frame),
        )
        windows.append(LearnerInputWindow(spec=spec, frame=frame))

    prepared_run = prepare_learner_run(
        learner=persisted_learner,
        windows=tuple(windows),
        run_id=run_id,
        prepared_at=prepared_at,
    )
    persisted_run = write_learner_run(run_path, prepared_run)
    return LearnerBootstrapResult(
        learner=persisted_learner,
        prepared_run=persisted_run,
        input_windows=tuple(windows),
    )


__all__ = [
    "LearnerBootstrapResult",
    "LearnerBootstrapTrainer",
    "bootstrap_learner_training",
]
