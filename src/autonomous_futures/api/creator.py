from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..research.creator_artifacts import (
    CreatorCandidateArtifact,
    CreatorCandidateRegistry,
    CreatorCandidateRegistryEntry,
    read_creator_candidate_artifact,
    read_creator_candidate_registry,
)


class CreatorCandidateRegistryNotFoundError(FileNotFoundError):
    """The optional creator registry has not been published yet."""


class CreatorCandidateRegistryIntegrityError(ValueError):
    """Persisted creator registry or referenced artifact cannot be trusted."""


@dataclass(frozen=True, slots=True)
class VerifiedCreatorCandidateRegistry:
    registry: CreatorCandidateRegistry
    artifacts: tuple[CreatorCandidateArtifact, ...]


def _resolve_artifact_ref(root: Path, artifact_ref: str) -> Path:
    relative = PurePosixPath(artifact_ref)
    if relative.is_absolute() or ".." in relative.parts or "\\" in artifact_ref:
        raise CreatorCandidateRegistryIntegrityError("creator artifact reference escapes root")

    resolved_root = root.resolve()
    resolved_path = (root / Path(*relative.parts)).resolve()
    if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
        raise CreatorCandidateRegistryIntegrityError("creator artifact reference escapes root")
    return resolved_path


def _entry_matches_artifact(
    entry: CreatorCandidateRegistryEntry, artifact: CreatorCandidateArtifact
) -> bool:
    return (
        entry.candidate_id == artifact.candidate_id
        and entry.artifact_hash == artifact.artifact_hash
        and entry.bundle_hash == artifact.bundle_hash
        and entry.dataset_registry_hash == artifact.dataset_registry_hash
        and entry.strategy_id == artifact.strategy.strategy_id
        and entry.family == artifact.strategy.family
        and entry.symbols == artifact.strategy.universe.symbols
        and entry.state == artifact.state
        and entry.creator_run_id == artifact.creator_run_id
    )


def load_verified_creator_candidate_registry(
    *, registry_path: Path, artifact_root: Path
) -> VerifiedCreatorCandidateRegistry:
    if not registry_path.exists():
        raise CreatorCandidateRegistryNotFoundError(registry_path)

    try:
        registry = read_creator_candidate_registry(registry_path)
        artifacts: list[CreatorCandidateArtifact] = []
        for entry in registry.entries:
            artifact_path = _resolve_artifact_ref(artifact_root, entry.artifact_ref)
            artifact = read_creator_candidate_artifact(artifact_path)
            if not _entry_matches_artifact(entry, artifact):
                raise CreatorCandidateRegistryIntegrityError(
                    "creator registry entry is not bound to its artifact"
                )
            artifacts.append(artifact)
    except CreatorCandidateRegistryIntegrityError:
        raise
    except (OSError, ValueError) as exc:
        raise CreatorCandidateRegistryIntegrityError from exc

    return VerifiedCreatorCandidateRegistry(registry=registry, artifacts=tuple(artifacts))


__all__ = [
    "CreatorCandidateRegistryIntegrityError",
    "CreatorCandidateRegistryNotFoundError",
    "VerifiedCreatorCandidateRegistry",
    "load_verified_creator_candidate_registry",
]
