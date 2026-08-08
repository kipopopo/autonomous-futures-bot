from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .creator_artifacts import CreatorCandidateArtifact

LearnerArtifactState = Literal["testing"]


class LearnerArtifact(DomainModel):
    artifact_version: Literal[1] = 1
    learner_id: str = Field(pattern=r"^learner-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    symbols: tuple[str, ...] = Field(min_length=1)
    primary_interval: Literal["5m"] = "5m"
    context_interval: Literal["15m"] = "15m"
    learner_run_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    learner_version: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    model_family: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    feature_ids: tuple[str, ...] = Field(min_length=1)
    training_window_start: datetime
    training_window_end: datetime
    model_artifact_ref: str = Field(min_length=1)
    model_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: LearnerArtifactState = "testing"
    source: Literal["learner_research"] = "learner_research"
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    created_at: datetime
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("symbols")
    @classmethod
    def symbols_are_sorted_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or value != value.upper() for value in values):
            raise ValueError("learner symbols must be uppercase")
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ValueError("learner symbols must be sorted and unique")
        return values

    @field_validator("feature_ids")
    @classmethod
    def feature_ids_are_sorted_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or value != value.strip() for value in values):
            raise ValueError("learner feature IDs must be non-empty")
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ValueError("learner feature IDs must be sorted and unique")
        return values

    @field_validator("model_artifact_ref")
    @classmethod
    def model_artifact_ref_is_relative(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or path == PurePosixPath(".") or ".." in path.parts or "\\" in value:
            raise ValueError("model_artifact_ref must be a relative POSIX path")
        return value

    @field_validator("training_window_start", "training_window_end", "created_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("learner timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_learner_contract(self) -> LearnerArtifact:
        if self.training_window_end <= self.training_window_start:
            raise ValueError("training_window_end must be after training_window_start")
        if self.state != "testing":
            raise ValueError("learner artifacts must start in testing state")
        return self


def _learner_content_hash(artifact: LearnerArtifact) -> str:
    payload = artifact.model_dump(mode="json", exclude={"created_at", "artifact_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def _model_path(model_root: Path, model_artifact_ref: str) -> Path:
    root = model_root.resolve()
    path = (root / PurePosixPath(model_artifact_ref)).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise DomainViolation("learner model artifact path escapes model root") from None
    return path


def _model_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_model_file(artifact: LearnerArtifact, *, model_root: Path) -> None:
    path = _model_path(model_root, artifact.model_artifact_ref)
    if not path.is_file():
        raise DomainViolation(f"learner model artifact missing: {path}")
    if _model_hash(path) != artifact.model_artifact_hash:
        raise DomainViolation(f"learner model artifact hash mismatch: {path}")


def verify_learner_artifact_binding(
    artifact: LearnerArtifact, candidate: CreatorCandidateArtifact
) -> None:
    if candidate.state != "testing":
        raise DomainViolation("learner artifact candidate binding requires testing candidate")
    if (
        artifact.candidate_id != candidate.candidate_id
        or artifact.candidate_artifact_hash != candidate.artifact_hash
        or artifact.bundle_hash != candidate.bundle_hash
        or artifact.dataset_registry_hash != candidate.dataset_registry_hash
        or artifact.symbols != candidate.strategy.universe.symbols
        or artifact.primary_interval != candidate.strategy.universe.timeframe
        or artifact.context_interval != candidate.strategy.universe.regime_context_timeframe
    ):
        raise DomainViolation("learner artifact candidate binding mismatch")


def build_learner_artifact(
    *,
    candidate: CreatorCandidateArtifact,
    learner_id: str,
    learner_run_id: str,
    learner_version: str,
    model_family: str,
    feature_ids: Sequence[str],
    training_window_start: datetime,
    training_window_end: datetime,
    model_artifact_ref: str,
    model_artifact_hash: str,
    created_at: datetime,
) -> LearnerArtifact:
    if candidate.state != "testing":
        raise DataQualityError("only testing candidates may produce learner artifacts")
    try:
        provisional = LearnerArtifact(
            learner_id=learner_id,
            candidate_id=candidate.candidate_id,
            candidate_artifact_hash=candidate.artifact_hash,
            bundle_hash=candidate.bundle_hash,
            dataset_registry_hash=candidate.dataset_registry_hash,
            symbols=candidate.strategy.universe.symbols,
            primary_interval=candidate.strategy.universe.timeframe,
            context_interval=candidate.strategy.universe.regime_context_timeframe,
            learner_run_id=learner_run_id,
            learner_version=learner_version,
            model_family=model_family,
            feature_ids=tuple(sorted(feature_ids)),
            training_window_start=training_window_start,
            training_window_end=training_window_end,
            model_artifact_ref=model_artifact_ref,
            model_artifact_hash=model_artifact_hash,
            created_at=created_at,
            artifact_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError("invalid learner artifact: " + str(exc)) from None
    return provisional.model_copy(update={"artifact_hash": _learner_content_hash(provisional)})


def _read_learner_artifact_json(path: Path) -> LearnerArtifact:
    artifact = LearnerArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    if _learner_content_hash(artifact) != artifact.artifact_hash:
        raise DomainViolation(f"learner artifact hash mismatch: {path}")
    return artifact


def read_learner_artifact(path: Path, *, model_root: Path) -> LearnerArtifact:
    artifact = _read_learner_artifact_json(path)
    _verify_model_file(artifact, model_root=model_root)
    return artifact


def _write_json_once(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(payload, encoding="utf-8", newline="\n")
    temporary_path.replace(path)


def write_learner_artifact(
    path: Path, artifact: LearnerArtifact, *, model_root: Path
) -> LearnerArtifact:
    if path.exists():
        existing = _read_learner_artifact_json(path)
        if existing != artifact:
            raise DomainViolation(f"learner artifact path is immutable: {path}")
        _verify_model_file(existing, model_root=model_root)
        return existing
    _verify_model_file(artifact, model_root=model_root)
    payload = json.dumps(artifact.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    _write_json_once(path, payload)
    return artifact


__all__ = [
    "LearnerArtifact",
    "LearnerArtifactState",
    "build_learner_artifact",
    "read_learner_artifact",
    "verify_learner_artifact_binding",
    "write_learner_artifact",
]
