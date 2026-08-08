from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .creator_artifacts import CreatorCandidateArtifact
from .learner_artifacts import (
    LearnerArtifact,
    read_learner_artifact,
    verify_learner_artifact_binding,
)
from .learner_runs import LearnerRun, learner_run_content_hash, read_learner_run

LearnerTrainingEvidenceState = Literal["completed"]


class LearnerTrainingEvidence(DomainModel):
    """Immutable evidence that an explicit trainer produced a learner artifact."""

    evidence_version: Literal[1] = 1
    evidence_id: str = Field(pattern=r"^training-evidence-[a-z0-9][a-z0-9-]{0,63}$")
    prepared_run_id: str = Field(pattern=r"^run-[a-z0-9][a-z0-9-]{0,63}$")
    prepared_run_ref: str = Field(min_length=1)
    prepared_run_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_learner_artifact_ref: str = Field(min_length=1)
    source_learner_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_artifact_ref: str = Field(min_length=1)
    output_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    learner_id: str = Field(pattern=r"^learner-[a-z0-9][a-z0-9-]{0,63}$")
    learner_run_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_window_ids: tuple[str, ...] = Field(min_length=1)
    input_symbols: tuple[str, ...] = Field(min_length=1)
    feature_ids: tuple[str, ...] = Field(min_length=1)
    training_window_start: datetime
    training_window_end: datetime
    learner_version: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    model_family: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    status: LearnerTrainingEvidenceState = "completed"
    training_metrics: None = None
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    created_at: datetime
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("prepared_run_ref", "source_learner_artifact_ref", "output_artifact_ref")
    @classmethod
    def refs_are_relative_posix(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or path.is_absolute()
            or path == PurePosixPath(".")
            or ".." in path.parts
            or "\\" in value
        ):
            raise ValueError("evidence references must be relative POSIX paths")
        return value

    @field_validator("input_window_ids")
    @classmethod
    def input_window_ids_are_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value for value in values):
            raise ValueError("training evidence input window IDs must be non-empty")
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ValueError("training evidence input window IDs must be sorted and unique")
        return values

    @field_validator("input_symbols")
    @classmethod
    def input_symbols_are_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or value != value.upper() for value in values):
            raise ValueError("training evidence input symbols must be uppercase")
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ValueError("training evidence input symbols must be sorted and unique")
        return values

    @field_validator("feature_ids")
    @classmethod
    def feature_ids_are_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or value != value.strip() for value in values):
            raise ValueError("training evidence feature IDs must be non-empty")
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ValueError("training evidence feature IDs must be sorted and unique")
        return values

    @field_validator("training_window_start", "training_window_end", "created_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("training evidence timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_evidence_contract(self) -> LearnerTrainingEvidence:
        if self.training_window_end <= self.training_window_start:
            raise ValueError("training evidence window must end after it starts")
        if self.status != "completed":
            raise ValueError("training evidence must be completed")
        return self


def learner_training_evidence_content_hash(evidence: LearnerTrainingEvidence) -> str:
    payload = evidence.model_dump(mode="json", exclude={"created_at", "evidence_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def _validate_ref(value: str) -> None:
    try:
        LearnerTrainingEvidence.model_validate(
            {
                "evidence_id": "training-evidence-placeholder",
                "prepared_run_id": "run-placeholder",
                "prepared_run_ref": value,
                "prepared_run_hash": "0" * 64,
                "source_learner_artifact_ref": "source.json",
                "source_learner_artifact_hash": "0" * 64,
                "output_artifact_ref": "output.json",
                "output_artifact_hash": "0" * 64,
                "learner_id": "learner-placeholder",
                "learner_run_id": "source-run",
                "candidate_id": "cand-placeholder",
                "candidate_artifact_hash": "0" * 64,
                "bundle_hash": "0" * 64,
                "dataset_registry_hash": "0" * 64,
                "input_window_ids": ("input",),
                "input_symbols": ("BTCUSDT",),
                "feature_ids": ("feature",),
                "training_window_start": datetime(2026, 1, 1, tzinfo=UTC),
                "training_window_end": datetime(2026, 1, 2, tzinfo=UTC),
                "learner_version": "v1",
                "model_family": "family",
                "created_at": datetime(2026, 1, 2, tzinfo=UTC),
                "evidence_hash": "0" * 64,
            }
        )
    except ValidationError as exc:
        raise DataQualityError("evidence references must be relative POSIX paths") from exc


def _verify_prepared_run(
    *,
    prepared_run: LearnerRun,
    source_learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
) -> None:
    try:
        verify_learner_artifact_binding(source_learner, candidate)
    except DomainViolation as exc:
        raise DataQualityError("source learner artifact binding is invalid") from exc
    if learner_run_content_hash(prepared_run) != prepared_run.run_hash:
        raise DataQualityError("prepared run hash is invalid")
    if (
        prepared_run.learner_id != source_learner.learner_id
        or prepared_run.learner_artifact_hash != source_learner.artifact_hash
        or prepared_run.candidate_id != source_learner.candidate_id
        or prepared_run.candidate_artifact_hash != source_learner.candidate_artifact_hash
        or prepared_run.bundle_hash != source_learner.bundle_hash
        or prepared_run.dataset_registry_hash != source_learner.dataset_registry_hash
        or prepared_run.input_symbols != source_learner.symbols
        or prepared_run.feature_ids != source_learner.feature_ids
    ):
        raise DataQualityError("prepared run binding is invalid")


def _verify_output_artifact(
    *,
    prepared_run: LearnerRun,
    output_artifact: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
) -> None:
    try:
        verify_learner_artifact_binding(output_artifact, candidate)
    except DomainViolation as exc:
        raise DataQualityError("output learner artifact binding is invalid") from exc
    if (
        output_artifact.learner_id != prepared_run.learner_id
        or output_artifact.learner_run_id != prepared_run.run_id
        or output_artifact.candidate_id != prepared_run.candidate_id
        or output_artifact.candidate_artifact_hash != prepared_run.candidate_artifact_hash
        or output_artifact.bundle_hash != prepared_run.bundle_hash
        or output_artifact.dataset_registry_hash != prepared_run.dataset_registry_hash
        or output_artifact.symbols != prepared_run.input_symbols
        or output_artifact.feature_ids != prepared_run.feature_ids
        or output_artifact.training_window_start != prepared_run.training_window_start
        or output_artifact.training_window_end != prepared_run.training_window_end
    ):
        raise DataQualityError("output learner artifact binding is invalid")


def build_learner_training_evidence(
    *,
    prepared_run: LearnerRun,
    source_learner: LearnerArtifact,
    output_artifact: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    source_learner_artifact_ref: str,
    prepared_run_ref: str,
    output_artifact_ref: str,
    created_at: datetime,
) -> LearnerTrainingEvidence:
    _validate_ref(source_learner_artifact_ref)
    _validate_ref(prepared_run_ref)
    _validate_ref(output_artifact_ref)
    _verify_prepared_run(
        prepared_run=prepared_run, source_learner=source_learner, candidate=candidate
    )
    _verify_output_artifact(
        prepared_run=prepared_run, output_artifact=output_artifact, candidate=candidate
    )
    try:
        provisional = LearnerTrainingEvidence(
            evidence_id=f"training-evidence-{prepared_run.run_id.removeprefix('run-')}",
            prepared_run_id=prepared_run.run_id,
            prepared_run_ref=prepared_run_ref,
            prepared_run_hash=prepared_run.run_hash,
            source_learner_artifact_ref=source_learner_artifact_ref,
            source_learner_artifact_hash=source_learner.artifact_hash,
            output_artifact_ref=output_artifact_ref,
            output_artifact_hash=output_artifact.artifact_hash,
            learner_id=output_artifact.learner_id,
            learner_run_id=output_artifact.learner_run_id,
            candidate_id=output_artifact.candidate_id,
            candidate_artifact_hash=output_artifact.candidate_artifact_hash,
            bundle_hash=output_artifact.bundle_hash,
            dataset_registry_hash=output_artifact.dataset_registry_hash,
            input_window_ids=prepared_run.input_window_ids,
            input_symbols=prepared_run.input_symbols,
            feature_ids=output_artifact.feature_ids,
            training_window_start=output_artifact.training_window_start,
            training_window_end=output_artifact.training_window_end,
            learner_version=output_artifact.learner_version,
            model_family=output_artifact.model_family,
            created_at=created_at,
            evidence_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError("invalid learner training evidence: " + str(exc)) from None
    return provisional.model_copy(
        update={"evidence_hash": learner_training_evidence_content_hash(provisional)}
    )


def _resolve_ref(root: Path, reference: str) -> Path:
    root_resolved = root.resolve()
    path = (root_resolved / PurePosixPath(reference)).resolve()
    try:
        path.relative_to(root_resolved)
    except ValueError:
        raise DomainViolation("learner training evidence reference escapes root") from None
    return path


def _read_run(path: Path) -> LearnerRun:
    try:
        run = read_learner_run(path)
    except (OSError, ValidationError, ValueError) as exc:
        raise DomainViolation("learner training evidence prepared run is invalid") from exc
    return run


def _read_evidence(path: Path) -> LearnerTrainingEvidence:
    try:
        evidence = LearnerTrainingEvidence.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise DomainViolation("learner training evidence is invalid") from exc
    if learner_training_evidence_content_hash(evidence) != evidence.evidence_hash:
        raise DomainViolation("learner training evidence hash mismatch")
    return evidence


def _verify_persisted_evidence(
    evidence: LearnerTrainingEvidence,
    *,
    run_root: Path,
    artifact_root: Path,
    model_root: Path,
    candidate: CreatorCandidateArtifact,
) -> None:
    run = _read_run(_resolve_ref(run_root, evidence.prepared_run_ref))
    try:
        source = read_learner_artifact(
            _resolve_ref(artifact_root, evidence.source_learner_artifact_ref),
            model_root=model_root,
        )
        output = read_learner_artifact(
            _resolve_ref(artifact_root, evidence.output_artifact_ref),
            model_root=model_root,
        )
    except (OSError, ValueError, DomainViolation) as exc:
        raise DomainViolation("learner training evidence artifact verification failed") from exc
    try:
        _verify_prepared_run(prepared_run=run, source_learner=source, candidate=candidate)
        _verify_output_artifact(prepared_run=run, output_artifact=output, candidate=candidate)
    except DataQualityError as exc:
        raise DomainViolation("learner training evidence binding failed") from exc
    if (
        evidence.prepared_run_id != run.run_id
        or evidence.prepared_run_hash != run.run_hash
        or evidence.source_learner_artifact_hash != source.artifact_hash
        or evidence.output_artifact_hash != output.artifact_hash
        or evidence.candidate_id != output.candidate_id
        or evidence.learner_version != output.learner_version
        or evidence.model_family != output.model_family
    ):
        raise DomainViolation("learner training evidence binding failed")


def read_learner_training_evidence(
    path: Path,
    *,
    run_root: Path,
    artifact_root: Path,
    model_root: Path,
    candidate: CreatorCandidateArtifact,
) -> LearnerTrainingEvidence:
    evidence = _read_evidence(path)
    _verify_persisted_evidence(
        evidence,
        run_root=run_root,
        artifact_root=artifact_root,
        model_root=model_root,
        candidate=candidate,
    )
    return evidence


def write_learner_training_evidence(
    path: Path,
    evidence: LearnerTrainingEvidence,
    *,
    run_root: Path,
    artifact_root: Path,
    model_root: Path,
    candidate: CreatorCandidateArtifact,
) -> LearnerTrainingEvidence:
    if path.exists():
        existing = read_learner_training_evidence(
            path,
            run_root=run_root,
            artifact_root=artifact_root,
            model_root=model_root,
            candidate=candidate,
        )
        if existing != evidence:
            raise DomainViolation(f"learner training evidence path is immutable: {path}") from None
        return existing

    if learner_training_evidence_content_hash(evidence) != evidence.evidence_hash:
        raise DomainViolation("learner training evidence hash mismatch")
    _verify_persisted_evidence(
        evidence,
        run_root=run_root,
        artifact_root=artifact_root,
        model_root=model_root,
        candidate=candidate,
    )
    payload = json.dumps(evidence.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(payload, encoding="utf-8", newline="\n")
    try:
        os.link(temporary_path, path)
    except FileExistsError:
        temporary_path.unlink(missing_ok=True)
        existing = read_learner_training_evidence(
            path,
            run_root=run_root,
            artifact_root=artifact_root,
            model_root=model_root,
            candidate=candidate,
        )
        if existing != evidence:
            raise DomainViolation(f"learner training evidence path is immutable: {path}") from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return read_learner_training_evidence(
        path,
        run_root=run_root,
        artifact_root=artifact_root,
        model_root=model_root,
        candidate=candidate,
    )


__all__ = [
    "LearnerTrainingEvidence",
    "LearnerTrainingEvidenceState",
    "build_learner_training_evidence",
    "learner_training_evidence_content_hash",
    "read_learner_training_evidence",
    "write_learner_training_evidence",
]
