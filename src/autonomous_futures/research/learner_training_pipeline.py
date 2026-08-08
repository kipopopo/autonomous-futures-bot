from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path, PurePosixPath

from ..data.parquet import DataQualityError
from ..domain.errors import DomainViolation
from .creator_artifacts import CreatorCandidateArtifact
from .learner_artifacts import (
    LearnerArtifact,
    read_learner_artifact,
    verify_learner_artifact_binding,
)
from .learner_inputs import LearnerInputWindow
from .learner_runs import LearnerRun, prepare_learner_run, write_learner_run
from .learner_training import LearnerTrainer, execute_learner_training
from .learner_training_evidence import (
    LearnerTrainingEvidence,
    build_learner_training_evidence,
    read_learner_training_evidence,
    write_learner_training_evidence,
)


def _resolve_ref(root: Path, reference: str, label: str) -> Path:
    path = PurePosixPath(reference)
    if (
        not reference
        or path.is_absolute()
        or path == PurePosixPath(".")
        or ".." in path.parts
        or "\\" in reference
    ):
        raise DataQualityError(f"{label} must be a relative POSIX path")
    root_resolved = root.resolve()
    resolved = (root_resolved / path).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise DataQualityError(f"{label} escapes its root") from None
    return resolved


def execute_learner_training_with_evidence(
    *,
    prepared_run: LearnerRun,
    source_learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    windows: Sequence[LearnerInputWindow],
    trainer: LearnerTrainer,
    run_root: Path,
    prepared_run_ref: str,
    artifact_root: Path,
    source_learner_artifact_ref: str,
    output_artifact_ref: str,
    model_root: Path,
    evidence_root: Path,
    evidence_ref: str,
    artifact_created_at: datetime,
    evidence_created_at: datetime,
) -> LearnerTrainingEvidence:
    """Run an explicit trainer and persist one verified evidence envelope."""
    run_path = _resolve_ref(run_root, prepared_run_ref, "prepared_run_ref")
    source_path = _resolve_ref(
        artifact_root, source_learner_artifact_ref, "source_learner_artifact_ref"
    )
    output_path = _resolve_ref(artifact_root, output_artifact_ref, "output_artifact_ref")
    evidence_path = _resolve_ref(evidence_root, evidence_ref, "evidence_ref")
    if source_path == output_path:
        raise DataQualityError("source and output learner artifact paths must differ")

    if evidence_path.exists():
        existing = read_learner_training_evidence(
            evidence_path,
            run_root=run_root,
            artifact_root=artifact_root,
            model_root=model_root,
            candidate=candidate,
        )
        if (
            existing.prepared_run_id != prepared_run.run_id
            or existing.prepared_run_hash != prepared_run.run_hash
            or existing.source_learner_artifact_ref != source_learner_artifact_ref
            or existing.source_learner_artifact_hash != source_learner.artifact_hash
            or existing.output_artifact_ref != output_artifact_ref
        ):
            raise DomainViolation(f"learner training evidence path is immutable: {evidence_path}")
        return existing

    try:
        persisted_source = read_learner_artifact(source_path, model_root=model_root)
    except (OSError, ValueError, DomainViolation) as exc:
        raise DataQualityError("source learner artifact is unavailable or invalid") from exc
    if persisted_source != source_learner:
        raise DataQualityError("source learner artifact does not match supplied artifact")
    try:
        verify_learner_artifact_binding(persisted_source, candidate)
        recomputed_run = prepare_learner_run(
            learner=persisted_source,
            windows=windows,
            run_id=prepared_run.run_id,
            prepared_at=prepared_run.prepared_at,
        )
    except (
        DataQualityError,
        DomainViolation,
    ):
        raise DataQualityError("prepared learner training evidence binding is invalid") from None
    if recomputed_run.run_hash != prepared_run.run_hash:
        raise DataQualityError("prepared learner training evidence binding is invalid")

    persisted_run = write_learner_run(run_path, prepared_run)
    output_artifact = execute_learner_training(
        prepared_run=persisted_run,
        learner=persisted_source,
        candidate=candidate,
        windows=windows,
        model_root=model_root,
        artifact_path=output_path,
        trainer=trainer,
        created_at=artifact_created_at,
    )
    evidence = build_learner_training_evidence(
        prepared_run=persisted_run,
        source_learner=persisted_source,
        output_artifact=output_artifact,
        candidate=candidate,
        source_learner_artifact_ref=source_learner_artifact_ref,
        prepared_run_ref=prepared_run_ref,
        output_artifact_ref=output_artifact_ref,
        created_at=evidence_created_at,
    )
    return write_learner_training_evidence(
        evidence_path,
        evidence,
        run_root=run_root,
        artifact_root=artifact_root,
        model_root=model_root,
        candidate=candidate,
    )


__all__ = ["execute_learner_training_with_evidence"]
