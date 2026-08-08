from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..domain.errors import DomainViolation
from ..research.creator_artifacts import CreatorCandidateArtifact
from ..research.learner_artifacts import (
    LearnerArtifact,
    read_learner_artifact,
    verify_learner_artifact_binding,
)
from ..research.learner_qualification import (
    LearnerQualificationEvidence,
    read_learner_qualification_evidence,
    read_learner_qualification_policy,
)
from ..research.learner_quality_review import (
    LearnerQualityReviewEvidence,
    read_learner_quality_review_evidence,
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


class LearnerQualityReviewEvidenceNotFoundError(FileNotFoundError):
    """The configured learner quality-review evidence is unavailable."""


class LearnerQualityReviewEvidenceIntegrityError(ValueError):
    """Quality-review evidence cannot be trusted after verification."""


class LearnerQualificationEvidenceNotFoundError(FileNotFoundError):
    """The configured learner qualification evidence is unavailable."""


class LearnerQualificationEvidenceIntegrityError(ValueError):
    """Qualification evidence cannot be trusted after verification."""


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


def _resolve_artifact_ref(root: Path, reference: str) -> Path:
    root_resolved = root.resolve()
    path = (root_resolved / PurePosixPath(reference)).resolve()
    try:
        path.relative_to(root_resolved)
    except ValueError:
        raise DomainViolation("learner quality review reference escapes root") from None
    return path


def load_verified_learner_quality_review_evidence(
    *,
    evidence_path: Path,
    training_evidence_path: Path,
    run_root: Path,
    artifact_root: Path,
    model_root: Path,
    candidate: CreatorCandidateArtifact,
) -> LearnerQualityReviewEvidence:
    if not evidence_path.exists():
        raise LearnerQualityReviewEvidenceNotFoundError(evidence_path)
    try:
        training_evidence = read_learner_training_evidence(
            training_evidence_path,
            run_root=run_root,
            artifact_root=artifact_root,
            model_root=model_root,
            candidate=candidate,
        )
        output_artifact = read_learner_artifact(
            _resolve_artifact_ref(artifact_root, training_evidence.output_artifact_ref),
            model_root=model_root,
        )
        return read_learner_quality_review_evidence(
            evidence_path,
            training_evidence=training_evidence,
            output_artifact=output_artifact,
            candidate=candidate,
        )
    except (OSError, ValueError, DomainViolation) as exc:
        raise LearnerQualityReviewEvidenceIntegrityError from exc


def load_verified_learner_qualification_evidence(
    *,
    evidence_path: Path,
    policy_path: Path,
    quality_review_path: Path,
    training_evidence_path: Path,
    run_root: Path,
    artifact_root: Path,
    model_root: Path,
    candidate: CreatorCandidateArtifact,
) -> LearnerQualificationEvidence:
    if not evidence_path.exists():
        raise LearnerQualificationEvidenceNotFoundError(evidence_path)
    try:
        policy = read_learner_qualification_policy(policy_path)
        training_evidence = read_learner_training_evidence(
            training_evidence_path,
            run_root=run_root,
            artifact_root=artifact_root,
            model_root=model_root,
            candidate=candidate,
        )
        output_artifact = read_learner_artifact(
            _resolve_artifact_ref(artifact_root, training_evidence.output_artifact_ref),
            model_root=model_root,
        )
        quality_review = read_learner_quality_review_evidence(
            quality_review_path,
            training_evidence=training_evidence,
            output_artifact=output_artifact,
            candidate=candidate,
        )
        return read_learner_qualification_evidence(
            evidence_path,
            training_evidence=training_evidence,
            quality_review=quality_review,
            output_artifact=output_artifact,
            candidate=candidate,
            policy=policy,
        )
    except (OSError, ValueError, DomainViolation) as exc:
        raise LearnerQualificationEvidenceIntegrityError from exc


__all__ = [
    "LearnerArtifactNotFoundError",
    "LearnerEvidenceIntegrityError",
    "LearnerRunNotFoundError",
    "LearnerTrainingEvidenceIntegrityError",
    "LearnerTrainingEvidenceNotFoundError",
    "LearnerQualityReviewEvidenceIntegrityError",
    "LearnerQualityReviewEvidenceNotFoundError",
    "LearnerQualificationEvidenceIntegrityError",
    "LearnerQualificationEvidenceNotFoundError",
    "VerifiedLearnerEvidence",
    "load_verified_learner_artifact",
    "load_verified_learner_run",
    "load_verified_learner_training_evidence",
    "load_verified_learner_quality_review_evidence",
    "load_verified_learner_qualification_evidence",
]
