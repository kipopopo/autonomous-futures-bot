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
from ..research.creator_proposals import canonical_creator_candidate_id


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


def collect_verified_creator_candidate_ids(history_root: Path) -> tuple[str, ...]:
    """Return the complete, verified candidate-ID snapshot beneath one history root."""
    if not history_root.is_dir():
        raise CreatorCandidateRegistryNotFoundError(history_root)

    registry_paths = tuple(sorted(history_root.rglob("candidate-registry.json")))
    if not registry_paths:
        raise CreatorCandidateRegistryNotFoundError(history_root)

    provider_ids: set[str] = set()
    canonical_ids: set[str] = set()
    for registry_path in registry_paths:
        verified = load_verified_creator_candidate_registry(
            registry_path=registry_path,
            artifact_root=registry_path.parent,
        )
        for entry, artifact in zip(verified.registry.entries, verified.artifacts, strict=True):
            canonical_id = canonical_creator_candidate_id(artifact.strategy)
            if entry.candidate_id in provider_ids or entry.candidate_id in canonical_ids:
                raise CreatorCandidateRegistryIntegrityError(
                    "historical candidate ID maps to multiple artifacts"
                )
            if canonical_id in provider_ids:
                raise CreatorCandidateRegistryIntegrityError(
                    "historical candidate ID maps to multiple artifacts"
                )
            provider_ids.add(entry.candidate_id)
            canonical_ids.add(canonical_id)
    return tuple(sorted(provider_ids | canonical_ids))


__all__ = [
    "CreatorCandidateRegistryIntegrityError",
    "CreatorCandidateRegistryNotFoundError",
    "VerifiedCreatorCandidateRegistry",
    "collect_verified_creator_candidate_ids",
    "load_verified_creator_candidate_registry",
]
