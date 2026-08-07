from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .creator_artifacts import CreatorCandidateArtifact

QualificationDecision = Literal["rejected", "qualified"]
QualificationComparator = Literal["gte", "lte", "eq", "present", "bool"]


class QualificationMetric(DomainModel):
    metric_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")
    value: Decimal

    @field_validator("value")
    @classmethod
    def value_is_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("qualification metric value must be finite")
        return value


class QualificationGateResult(DomainModel):
    gate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")
    passed: bool
    observed: Decimal | None = None
    threshold: Decimal | None = None
    comparator: QualificationComparator
    reason_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,63}$")

    @field_validator("observed", "threshold")
    @classmethod
    def optional_values_are_finite(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError("qualification gate values must be finite")
        return value


class CreatorCandidateQualificationArtifact(DomainModel):
    qualification_version: Literal[1] = 1
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_run_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    evaluator_version: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    decision: QualificationDecision
    metrics: tuple[QualificationMetric, ...] = Field(min_length=1)
    gates: tuple[QualificationGateResult, ...] = Field(min_length=1)
    windows_evaluated: int = Field(ge=0)
    source: Literal["creator_evaluator"] = "creator_evaluator"
    evaluated_at: datetime
    promotion_state: Literal["unpromoted"] = "unpromoted"
    execution_authority: Literal[False] = False
    qualification_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("evaluated_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_evidence_contract(self) -> CreatorCandidateQualificationArtifact:
        metric_ids = tuple(metric.metric_id for metric in self.metrics)
        if len(set(metric_ids)) != len(metric_ids) or metric_ids != tuple(sorted(metric_ids)):
            raise ValueError("qualification metrics must be sorted and unique")
        gate_ids = tuple(gate.gate_id for gate in self.gates)
        if len(set(gate_ids)) != len(gate_ids) or gate_ids != tuple(sorted(gate_ids)):
            raise ValueError("qualification gates must be sorted and unique")
        if self.decision == "qualified":
            if self.windows_evaluated < 1:
                raise ValueError("qualified decision requires at least one evaluated window")
            if not all(gate.passed for gate in self.gates):
                raise ValueError("qualified decision requires every gate to pass")
        return self


def _qualification_content_hash(artifact: CreatorCandidateQualificationArtifact) -> str:
    payload = artifact.model_dump(mode="json", exclude={"evaluated_at", "qualification_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def build_creator_candidate_qualification_artifact(
    *,
    candidate: CreatorCandidateArtifact,
    evaluator_run_id: str,
    evaluator_version: str,
    decision: QualificationDecision,
    metrics: Sequence[QualificationMetric],
    gates: Sequence[QualificationGateResult],
    windows_evaluated: int,
    evaluated_at: datetime,
) -> CreatorCandidateQualificationArtifact:
    if candidate.state != "testing":
        raise DataQualityError("only testing candidates may be qualified")
    try:
        provisional = CreatorCandidateQualificationArtifact(
            candidate_id=candidate.candidate_id,
            candidate_artifact_hash=candidate.artifact_hash,
            bundle_hash=candidate.bundle_hash,
            dataset_registry_hash=candidate.dataset_registry_hash,
            evaluator_run_id=evaluator_run_id,
            evaluator_version=evaluator_version,
            decision=decision,
            metrics=tuple(sorted(metrics, key=lambda metric: metric.metric_id)),
            gates=tuple(sorted(gates, key=lambda gate: gate.gate_id)),
            windows_evaluated=windows_evaluated,
            evaluated_at=evaluated_at,
            qualification_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError("invalid creator qualification artifact: " + str(exc)) from None
    return provisional.model_copy(
        update={"qualification_hash": _qualification_content_hash(provisional)}
    )


def read_creator_candidate_qualification_artifact(
    path: Path,
) -> CreatorCandidateQualificationArtifact:
    artifact = CreatorCandidateQualificationArtifact.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    if _qualification_content_hash(artifact) != artifact.qualification_hash:
        raise DomainViolation(f"creator qualification artifact hash mismatch: {path}")
    return artifact


def write_creator_candidate_qualification_artifact(
    path: Path, artifact: CreatorCandidateQualificationArtifact
) -> CreatorCandidateQualificationArtifact:
    if path.exists():
        existing = read_creator_candidate_qualification_artifact(path)
        if existing != artifact:
            raise DomainViolation(f"creator qualification artifact path is immutable: {path}")
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(artifact.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(payload, encoding="utf-8", newline="\n")
    temporary_path.replace(path)
    return artifact


__all__ = [
    "CreatorCandidateQualificationArtifact",
    "QualificationComparator",
    "QualificationDecision",
    "QualificationGateResult",
    "QualificationMetric",
    "build_creator_candidate_qualification_artifact",
    "read_creator_candidate_qualification_artifact",
    "write_creator_candidate_qualification_artifact",
]
