from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel, StrategySpec
from ..domain.errors import DomainViolation

CandidateState = Literal["testing"]


class CreatorCandidateArtifact(DomainModel):
    artifact_version: Literal[1] = 1
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    state: CandidateState = "testing"
    strategy: StrategySpec
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    creator_run_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    research_seed: int = Field(ge=0)
    source: Literal["creator_research"] = "creator_research"
    created_at: datetime
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("created_at")
    @classmethod
    def created_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("created_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_candidate_contract(self) -> CreatorCandidateArtifact:
        if self.strategy.strategy_id != self.candidate_id:
            raise ValueError("strategy_id must match candidate_id")
        symbols = self.strategy.universe.symbols
        if symbols != tuple(sorted(symbols)) or len(set(symbols)) != len(symbols):
            raise ValueError("strategy universe symbols must be sorted and unique")
        if self.state != "testing":
            raise ValueError("creator candidates must start in testing state")
        return self


class CreatorCandidateRegistryEntry(DomainModel):
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_ref: str = Field(min_length=1)
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    strategy_id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    symbols: tuple[str, ...] = Field(min_length=1)
    state: CandidateState = "testing"
    creator_run_id: str = Field(min_length=1)
    created_at: datetime

    @field_validator("artifact_ref")
    @classmethod
    def artifact_ref_is_relative(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError("artifact_ref must be a relative POSIX path")
        return value

    @field_validator("created_at")
    @classmethod
    def created_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("created_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_registry_entry(self) -> CreatorCandidateRegistryEntry:
        if self.state != "testing":
            raise ValueError("creator registry entries must start in testing state")
        if self.symbols != tuple(sorted(self.symbols)) or len(set(self.symbols)) != len(
            self.symbols
        ):
            raise ValueError("registry symbols must be sorted and unique")
        return self


class CreatorCandidateRegistry(DomainModel):
    registry_version: Literal[1] = 1
    venue: Literal["BINANCE_USDS_M_FUTURES"] = "BINANCE_USDS_M_FUTURES"
    created_at: datetime
    entries: tuple[CreatorCandidateRegistryEntry, ...] = Field(min_length=1)
    registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("created_at")
    @classmethod
    def created_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("created_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_entries(self) -> CreatorCandidateRegistry:
        ids = tuple(entry.candidate_id for entry in self.entries)
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate creator candidate identity")
        if ids != tuple(sorted(ids)):
            raise ValueError("creator registry entries must be sorted")
        return self


def _artifact_content_hash(artifact: CreatorCandidateArtifact) -> str:
    payload = artifact.model_dump(mode="json", exclude={"created_at", "artifact_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def _registry_content_hash(registry: CreatorCandidateRegistry) -> str:
    payload = registry.model_dump(mode="json", exclude={"created_at", "registry_hash"})
    for entry in payload["entries"]:
        entry.pop("created_at", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def _write_json_once(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(payload, encoding="utf-8", newline="\n")
    temporary_path.replace(path)


def build_creator_candidate_artifact(
    *,
    candidate_id: str,
    strategy: StrategySpec,
    bundle_hash: str,
    dataset_registry_hash: str,
    creator_run_id: str,
    research_seed: int,
    created_at: datetime,
) -> CreatorCandidateArtifact:
    try:
        provisional = CreatorCandidateArtifact(
            candidate_id=candidate_id,
            strategy=strategy,
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
            creator_run_id=creator_run_id,
            research_seed=research_seed,
            created_at=created_at,
            artifact_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError("invalid creator candidate artifact: " + str(exc)) from None
    return provisional.model_copy(update={"artifact_hash": _artifact_content_hash(provisional)})


def read_creator_candidate_artifact(path: Path) -> CreatorCandidateArtifact:
    artifact = CreatorCandidateArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    if _artifact_content_hash(artifact) != artifact.artifact_hash:
        raise DomainViolation(f"creator candidate artifact hash mismatch: {path}")
    return artifact


def write_creator_candidate_artifact(
    path: Path, artifact: CreatorCandidateArtifact
) -> CreatorCandidateArtifact:
    if path.exists():
        existing = read_creator_candidate_artifact(path)
        if existing != artifact:
            raise DomainViolation(f"creator candidate artifact path is immutable: {path}")
        return existing
    payload = json.dumps(artifact.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    _write_json_once(path, payload)
    return artifact


def _registry_entry(
    artifact: CreatorCandidateArtifact, artifact_ref: str
) -> CreatorCandidateRegistryEntry:
    return CreatorCandidateRegistryEntry(
        candidate_id=artifact.candidate_id,
        artifact_hash=artifact.artifact_hash,
        artifact_ref=artifact_ref,
        bundle_hash=artifact.bundle_hash,
        dataset_registry_hash=artifact.dataset_registry_hash,
        strategy_id=artifact.strategy.strategy_id,
        family=artifact.strategy.family,
        symbols=artifact.strategy.universe.symbols,
        state=artifact.state,
        creator_run_id=artifact.creator_run_id,
        created_at=artifact.created_at,
    )


def build_creator_candidate_registry(
    artifacts: Sequence[tuple[CreatorCandidateArtifact, str]],
    *,
    created_at: datetime,
) -> CreatorCandidateRegistry:
    if not artifacts:
        raise DataQualityError("creator candidate registry requires at least one artifact")
    bindings = {(artifact.bundle_hash, artifact.dataset_registry_hash) for artifact, _ in artifacts}
    if len(bindings) != 1:
        raise DataQualityError("creator candidates must share the same dataset binding")
    entries = tuple(_registry_entry(artifact, artifact_ref) for artifact, artifact_ref in artifacts)
    provisional = CreatorCandidateRegistry(
        created_at=created_at,
        entries=tuple(sorted(entries, key=lambda entry: entry.candidate_id)),
        registry_hash="0" * 64,
    )
    return provisional.model_copy(update={"registry_hash": _registry_content_hash(provisional)})


def read_creator_candidate_registry(path: Path) -> CreatorCandidateRegistry:
    registry = CreatorCandidateRegistry.model_validate_json(path.read_text(encoding="utf-8"))
    if _registry_content_hash(registry) != registry.registry_hash:
        raise DomainViolation(f"creator candidate registry hash mismatch: {path}")
    return registry


def write_creator_candidate_registry(
    path: Path, registry: CreatorCandidateRegistry
) -> CreatorCandidateRegistry:
    if path.exists():
        existing = read_creator_candidate_registry(path)
        if existing != registry:
            raise DomainViolation(f"creator candidate registry path is immutable: {path}")
        return existing
    payload = json.dumps(registry.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    _write_json_once(path, payload)
    return registry


def find_creator_candidate(
    registry: CreatorCandidateRegistry, *, candidate_id: str
) -> CreatorCandidateRegistryEntry | None:
    return next(
        (entry for entry in registry.entries if entry.candidate_id == candidate_id),
        None,
    )


__all__ = [
    "CandidateState",
    "CreatorCandidateArtifact",
    "CreatorCandidateRegistry",
    "CreatorCandidateRegistryEntry",
    "build_creator_candidate_artifact",
    "build_creator_candidate_registry",
    "find_creator_candidate",
    "read_creator_candidate_artifact",
    "read_creator_candidate_registry",
    "write_creator_candidate_artifact",
    "write_creator_candidate_registry",
]
