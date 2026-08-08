from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..research.creator_artifacts import CreatorCandidateArtifact, CreatorCandidateRegistry
from ..research.qualification_artifacts import (
    CreatorCandidateQualificationArtifact,
    read_creator_candidate_qualification_artifact,
)
from .creator import (
    CreatorCandidateRegistryIntegrityError,
    CreatorCandidateRegistryNotFoundError,
    VerifiedCreatorCandidateRegistry,
    load_verified_creator_candidate_registry,
)


class CreatorQualificationArtifactNotFoundError(FileNotFoundError):
    """The requested candidate has no persisted qualification evidence."""


class CreatorQualificationArtifactIntegrityError(ValueError):
    """Persisted qualification evidence cannot be trusted."""


@dataclass(frozen=True, slots=True)
class VerifiedCreatorQualification:
    candidate: CreatorCandidateArtifact
    qualification: CreatorCandidateQualificationArtifact


@dataclass(frozen=True, slots=True)
class VerifiedCreatorQualifications:
    registry: CreatorCandidateRegistry
    qualifications: tuple[VerifiedCreatorQualification, ...]
    missing_candidate_ids: tuple[str, ...]


def _candidate_binding_matches(
    candidate: CreatorCandidateArtifact,
    qualification: CreatorCandidateQualificationArtifact,
) -> bool:
    return (
        qualification.candidate_id == candidate.candidate_id
        and qualification.candidate_artifact_hash == candidate.artifact_hash
        and qualification.bundle_hash == candidate.bundle_hash
        and qualification.dataset_registry_hash == candidate.dataset_registry_hash
    )


def _read_verified_qualification(
    candidate: CreatorCandidateArtifact, qualification_path: Path
) -> VerifiedCreatorQualification:
    try:
        qualification = read_creator_candidate_qualification_artifact(qualification_path)
    except (OSError, ValueError) as exc:
        raise CreatorQualificationArtifactIntegrityError from exc
    if not _candidate_binding_matches(candidate, qualification):
        raise CreatorQualificationArtifactIntegrityError(
            "creator qualification artifact is not bound to its candidate"
        )
    return VerifiedCreatorQualification(candidate=candidate, qualification=qualification)


def _qualification_path(root: Path, candidate_id: str) -> Path:
    return root / f"{candidate_id}.json"


def _candidate_from_registry(
    verified_registry: VerifiedCreatorCandidateRegistry, candidate_id: str
) -> CreatorCandidateArtifact:
    for entry, candidate in zip(
        verified_registry.registry.entries, verified_registry.artifacts, strict=True
    ):
        if entry.candidate_id == candidate_id:
            return candidate
    raise CreatorQualificationArtifactNotFoundError(candidate_id)


def load_verified_creator_candidate_qualification(
    *,
    registry_path: Path,
    candidate_artifact_root: Path,
    qualification_root: Path,
    candidate_id: str,
) -> VerifiedCreatorQualification:
    verified_registry = load_verified_creator_candidate_registry(
        registry_path=registry_path,
        artifact_root=candidate_artifact_root,
    )
    candidate = _candidate_from_registry(verified_registry, candidate_id)
    path = _qualification_path(qualification_root, candidate.candidate_id)
    if not path.exists():
        raise CreatorQualificationArtifactNotFoundError(path)
    return _read_verified_qualification(candidate, path)


def load_verified_creator_candidate_qualifications(
    *,
    registry_path: Path,
    candidate_artifact_root: Path,
    qualification_root: Path,
) -> VerifiedCreatorQualifications:
    verified_registry = load_verified_creator_candidate_registry(
        registry_path=registry_path,
        artifact_root=candidate_artifact_root,
    )
    qualifications: list[VerifiedCreatorQualification] = []
    missing_candidate_ids: list[str] = []
    for entry, candidate in zip(
        verified_registry.registry.entries, verified_registry.artifacts, strict=True
    ):
        path = _qualification_path(qualification_root, entry.candidate_id)
        if not path.exists():
            missing_candidate_ids.append(entry.candidate_id)
            continue
        qualifications.append(_read_verified_qualification(candidate, path))
    return VerifiedCreatorQualifications(
        registry=verified_registry.registry,
        qualifications=tuple(qualifications),
        missing_candidate_ids=tuple(missing_candidate_ids),
    )


__all__ = [
    "CreatorCandidateRegistryIntegrityError",
    "CreatorCandidateRegistryNotFoundError",
    "CreatorQualificationArtifactIntegrityError",
    "CreatorQualificationArtifactNotFoundError",
    "VerifiedCreatorQualification",
    "VerifiedCreatorQualifications",
    "load_verified_creator_candidate_qualification",
    "load_verified_creator_candidate_qualifications",
]
