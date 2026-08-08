from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath

import pandas as pd

from ..data.parquet import DataQualityError
from ..domain.errors import DomainViolation
from .creator_artifacts import CreatorCandidateArtifact
from .learner_artifacts import (
    LearnerArtifact,
    build_learner_artifact,
    verify_learner_artifact_binding,
    write_learner_artifact,
)
from .learner_inputs import LearnerInputWindow
from .learner_runs import LearnerRun, prepare_learner_run


@dataclass(frozen=True, slots=True)
class LearnerTrainingOutput:
    """Explicit trainer output; model bytes are the only accepted output payload."""

    model_artifact_ref: str
    model_family: str
    learner_version: str
    model_bytes: bytes

    def __post_init__(self) -> None:
        path = PurePosixPath(self.model_artifact_ref)
        if (
            not self.model_artifact_ref
            or path.is_absolute()
            or path == PurePosixPath(".")
            or ".." in path.parts
            or "\\" in self.model_artifact_ref
        ):
            raise DataQualityError("model_artifact_ref must be a relative POSIX path")
        if not self.model_family.strip():
            raise DataQualityError("model_family must be non-empty")
        if not self.learner_version.strip():
            raise DataQualityError("learner_version must be non-empty")
        if not isinstance(self.model_bytes, bytes) or not self.model_bytes:
            raise DataQualityError("trainer must return non-empty model bytes")


LearnerTrainer = Callable[[LearnerRun, dict[str, pd.DataFrame]], LearnerTrainingOutput]


def _model_path(model_root: Path, model_artifact_ref: str) -> Path:
    root = model_root.resolve()
    path = (root / PurePosixPath(model_artifact_ref)).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise DataQualityError("model_artifact_ref escapes model root") from None
    return path


def _write_model_bytes_once(
    model_root: Path, model_artifact_ref: str, model_bytes: bytes
) -> tuple[Path, bool]:
    path = _model_path(model_root, model_artifact_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.read_bytes() != model_bytes:
            raise DomainViolation(f"learner model artifact is immutable: {path}")
        return path, False

    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_bytes(model_bytes)
    try:
        os.link(temporary_path, path)
    except FileExistsError:
        temporary_path.unlink(missing_ok=True)
        if not path.is_file() or path.read_bytes() != model_bytes:
            raise DomainViolation(f"learner model artifact is immutable: {path}") from None
        return path, False
    finally:
        temporary_path.unlink(missing_ok=True)
    return path, True


def _verify_prepared_run_binding(
    *,
    prepared_run: LearnerRun,
    learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    windows: Sequence[LearnerInputWindow],
) -> None:
    try:
        verify_learner_artifact_binding(learner, candidate)
    except DomainViolation:
        raise DataQualityError("prepared run binding is invalid") from None
    if (
        prepared_run.learner_id != learner.learner_id
        or prepared_run.learner_artifact_hash != learner.artifact_hash
        or prepared_run.candidate_id != candidate.candidate_id
        or prepared_run.candidate_artifact_hash != candidate.artifact_hash
        or prepared_run.status != "prepared"
    ):
        raise DataQualityError("prepared run binding is invalid")
    try:
        recomputed = prepare_learner_run(
            learner=learner,
            windows=windows,
            run_id=prepared_run.run_id,
            prepared_at=prepared_run.prepared_at,
        )
    except DataQualityError:
        raise DataQualityError("prepared run binding is invalid") from None
    if recomputed.run_hash != prepared_run.run_hash:
        raise DataQualityError("prepared run binding is invalid")


def execute_learner_training(
    *,
    prepared_run: LearnerRun,
    learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    windows: Sequence[LearnerInputWindow],
    model_root: Path,
    artifact_path: Path,
    trainer: LearnerTrainer,
    created_at: datetime,
) -> LearnerArtifact:
    """Execute only an explicit trainer and persist its verified model artifact."""
    _verify_prepared_run_binding(
        prepared_run=prepared_run,
        learner=learner,
        candidate=candidate,
        windows=windows,
    )
    if len(windows) != len(prepared_run.input_symbols):
        raise DataQualityError("training boundary requires one input window per symbol")

    frames: dict[str, pd.DataFrame] = {}
    for window in windows:
        symbol = window.spec.symbol
        if symbol in frames:
            raise DataQualityError("training boundary requires unique input symbols")
        frames[symbol] = window.copy_frame()

    output = trainer(prepared_run, frames)
    if not isinstance(output, LearnerTrainingOutput):
        raise DataQualityError("trainer must return LearnerTrainingOutput")
    model_hash = sha256(output.model_bytes).hexdigest()
    artifact = build_learner_artifact(
        candidate=candidate,
        learner_id=learner.learner_id,
        learner_run_id=prepared_run.run_id,
        learner_version=output.learner_version,
        model_family=output.model_family,
        feature_ids=prepared_run.feature_ids,
        training_window_start=prepared_run.training_window_start,
        training_window_end=prepared_run.training_window_end,
        model_artifact_ref=output.model_artifact_ref,
        model_artifact_hash=model_hash,
        created_at=created_at,
    )

    model_path, model_created = _write_model_bytes_once(
        model_root, output.model_artifact_ref, output.model_bytes
    )
    try:
        return write_learner_artifact(artifact_path, artifact, model_root=model_root)
    except Exception:
        if model_created:
            model_path.unlink(missing_ok=True)
        raise


__all__ = ["LearnerTrainer", "LearnerTrainingOutput", "execute_learner_training"]
