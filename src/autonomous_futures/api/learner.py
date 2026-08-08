from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..research.creator_artifacts import CreatorCandidateArtifact
from ..research.learner_artifacts import (
    LearnerArtifact,
    read_learner_artifact,
    verify_learner_artifact_binding,
)
from ..research.learner_runs import LearnerRun, read_learner_run
from ..research.learner_training_evidence import (
    LearnerTrainingEvidence,
    read_learner_training_evidence,
)
from .catalog import (
    DatasetCatalogIntegrityError,
    load_verified_dataset_catalog,
)
from .creator import (
    CreatorCandidateRegistryIntegrityError,
    CreatorCandidateRegistryNotFoundError,
    load_verified_creator_candidate_registry,
)


class LearnerArtifactNotFoundError(FileNotFoundError):
    """The configured learner artifact or its required registry is unavailable."""


class LearnerRunNotFoundError(FileNotFoundError):
    """The configured persisted learner run is unavailable."""


class LearnerTrainingEvidenceNotFoundError(FileNotFoundError):
    """The configured completed-training evidence is unavailable."""


class LearnerEvidenceIntegrityError(ValueError):
    """Learner evidence cannot be trusted after integrity/binding checks."""


class LearnerTrainingEvidenceIntegrityError(ValueError):
    """Completed-training evidence cannot be trusted after verification."""


@dataclass(frozen=True, slots=True)
class VerifiedLearnerEvidence:
    artifact: LearnerArtifact
    candidate: CreatorCandidateArtifact


def _candidate_for_artifact(
    *,
    artifact: LearnerArtifact,
    registry_path: Path,
    candidate_artifact_root: Path,
) -> CreatorCandidateArtifact:
    try:
        verified_registry = load_verified_creator_candidate_registry(
            registry_path=registry_path,
            artifact_root=candidate_artifact_root,
        )
    except CreatorCandidateRegistryNotFoundError as exc:
        raise LearnerArtifactNotFoundError from exc
    except CreatorCandidateRegistryIntegrityError as exc:
        raise LearnerEvidenceIntegrityError from exc

    for entry, candidate in zip(
        verified_registry.registry.entries, verified_registry.artifacts, strict=True
    ):
        if entry.candidate_id == artifact.candidate_id:
            return candidate
    raise LearnerArtifactNotFoundError(artifact.candidate_id)


def load_verified_learner_artifact(
    *,
    artifact_path: Path,
    model_root: Path,
    bundle_path: Path,
    registry_path: Path,
    candidate_registry_path: Path,
    candidate_artifact_root: Path,
) -> VerifiedLearnerEvidence:
    if not artifact_path.exists():
        raise LearnerArtifactNotFoundError(artifact_path)
    try:
        artifact = read_learner_artifact(artifact_path, model_root=model_root)
    except (OSError, ValueError) as exc:
        raise LearnerEvidenceIntegrityError from exc

    candidate = _candidate_for_artifact(
        artifact=artifact,
        registry_path=candidate_registry_path,
        candidate_artifact_root=candidate_artifact_root,
    )
    try:
        verify_learner_artifact_binding(artifact, candidate)
    except ValueError as exc:
        raise LearnerEvidenceIntegrityError from exc

    try:
        catalog = load_verified_dataset_catalog(
            bundle_path=bundle_path,
            registry_path=registry_path,
        )
    except DatasetCatalogIntegrityError as exc:
        raise LearnerEvidenceIntegrityError from exc
    if (
        artifact.bundle_hash != catalog.bundle.bundle_hash
        or artifact.dataset_registry_hash != catalog.registry.registry_hash
        or artifact.symbols != catalog.bundle.symbols
        or artifact.primary_interval != catalog.bundle.primary_interval
        or artifact.context_interval != catalog.bundle.context_interval
        or artifact.training_window_start < catalog.bundle.time_start
        or artifact.training_window_end > catalog.bundle.time_end
    ):
        raise LearnerEvidenceIntegrityError("learner artifact dataset binding mismatch")
    return VerifiedLearnerEvidence(artifact=artifact, candidate=candidate)


def load_verified_learner_run(
    *,
    run_path: Path,
    learner_evidence: VerifiedLearnerEvidence,
) -> LearnerRun:
    if not run_path.exists():
        raise LearnerRunNotFoundError(run_path)
    try:
        run = read_learner_run(run_path)
    except (OSError, ValueError) as exc:
        raise LearnerEvidenceIntegrityError from exc
    artifact = learner_evidence.artifact
    if (
        run.learner_id != artifact.learner_id
        or run.learner_run_id != artifact.learner_run_id
        or run.learner_version != artifact.learner_version
        or run.learner_artifact_hash != artifact.artifact_hash
        or run.candidate_id != artifact.candidate_id
        or run.candidate_artifact_hash != artifact.candidate_artifact_hash
        or run.bundle_hash != artifact.bundle_hash
        or run.dataset_registry_hash != artifact.dataset_registry_hash
        or run.input_symbols != artifact.symbols
        or run.feature_ids != artifact.feature_ids
        or run.training_window_start != artifact.training_window_start
        or run.training_window_end != artifact.training_window_end
    ):
        raise LearnerEvidenceIntegrityError("learner run binding mismatch")
    return run


def load_verified_learner_training_evidence(
    *,
    evidence_path: Path,
    run_root: Path,
    artifact_root: Path,
    model_root: Path,
    candidate: CreatorCandidateArtifact,
) -> LearnerTrainingEvidence:
    if not evidence_path.exists():
        raise LearnerTrainingEvidenceNotFoundError(evidence_path)
    try:
        return read_learner_training_evidence(
            evidence_path,
            run_root=run_root,
            artifact_root=artifact_root,
            model_root=model_root,
            candidate=candidate,
        )
    except (OSError, ValueError) as exc:
        raise LearnerTrainingEvidenceIntegrityError from exc


__all__ = [
    "LearnerArtifactNotFoundError",
    "LearnerEvidenceIntegrityError",
    "LearnerRunNotFoundError",
    "LearnerTrainingEvidenceIntegrityError",
    "LearnerTrainingEvidenceNotFoundError",
    "VerifiedLearnerEvidence",
    "load_verified_learner_artifact",
    "load_verified_learner_run",
    "load_verified_learner_training_evidence",
]
