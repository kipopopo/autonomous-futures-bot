"""Immutable persistence for accepted Learner/Critic reviews."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .learner_critic import (
    LearnerCriticRequest,
    LearnerCritique,
    learner_critique_content_hash,
)


class LearnerCritiqueEvidence(DomainModel):
    evidence_version: int = 1
    evidence_id: str = Field(pattern=r"^critic-evidence-[a-z0-9][a-z0-9-]{0,63}$")
    review_id: str = Field(pattern=r"^review-[a-z0-9][a-z0-9-]{0,63}$")
    review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    research_run_id: str = Field(pattern=r"^run-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_evidence_refs: tuple[str, ...] = Field(min_length=1)
    critique_decision: str = Field(pattern=r"^(revise|stop)$")
    failure_reason_codes: tuple[str, ...] = Field(min_length=1)
    revision_actions: tuple[str, ...] = Field(min_length=1)
    data_source: str = "cached_only"
    exchange_access: bool = False
    promotion_state: str = "unpromoted"
    paper_activation: bool = False
    execution_authority: bool = False
    created_at: datetime
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("input_evidence_refs", "failure_reason_codes", "revision_actions")
    @classmethod
    def lists_are_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("critique evidence lists must be non-empty")
        if values != tuple(sorted(set(values))):
            raise ValueError("critique evidence lists must be sorted and unique")
        return values

    @field_validator("created_at")
    @classmethod
    def created_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("critique evidence created_at must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def safety_is_fixed(self) -> LearnerCritiqueEvidence:
        if self.data_source != "cached_only":
            raise ValueError("critique evidence must be cached_only")
        if self.exchange_access or self.paper_activation or self.execution_authority:
            raise ValueError("critique evidence cannot carry execution authority")
        if self.promotion_state != "unpromoted":
            raise ValueError("critique evidence cannot carry promotion authority")
        return self


def learner_critique_evidence_content_hash(evidence: LearnerCritiqueEvidence) -> str:
    payload = evidence.model_dump(mode="json", exclude={"created_at", "evidence_hash"})
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_learner_critique_evidence(
    *,
    request: LearnerCriticRequest,
    critique: LearnerCritique,
    evidence_id: str,
    created_at: datetime,
) -> LearnerCritiqueEvidence:
    if learner_critique_content_hash(critique) != critique.review_hash:
        raise DomainViolation("Learner critique hash mismatch")
    if critique.research_run_id != request.research_run_id:
        raise DataQualityError("critique research run binding is invalid")
    if critique.candidate_id != request.candidate_id:
        raise DataQualityError("critique candidate binding is invalid")
    if critique.failure_reason_codes != request.feedback.failure_reason_codes:
        raise DataQualityError("critique feedback binding is invalid")
    provisional = LearnerCritiqueEvidence(
        evidence_id=evidence_id,
        review_id=critique.review_id,
        review_hash=critique.review_hash,
        research_run_id=request.research_run_id,
        candidate_id=request.candidate_id,
        candidate_artifact_hash=request.candidate_artifact_hash,
        qualification_hash=request.feedback.qualification_hash,
        bundle_hash=request.feedback.bundle_hash,
        dataset_registry_hash=request.feedback.dataset_registry_hash,
        input_evidence_refs=request.input_evidence_refs,
        critique_decision=critique.decision,
        failure_reason_codes=critique.failure_reason_codes,
        revision_actions=critique.revision_actions,
        created_at=created_at,
        evidence_hash="0" * 64,
    )
    return provisional.model_copy(
        update={"evidence_hash": learner_critique_evidence_content_hash(provisional)}
    )


def read_learner_critique_evidence(path: Path) -> LearnerCritiqueEvidence:
    try:
        evidence = LearnerCritiqueEvidence.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except (ValidationError, ValueError) as exc:
        raise DataQualityError("invalid persisted Learner critique evidence") from exc
    if learner_critique_evidence_content_hash(evidence) != evidence.evidence_hash:
        raise DomainViolation(f"Learner critique evidence hash mismatch: {path}")
    return evidence


def persist_learner_critique_evidence(
    path: Path, evidence: LearnerCritiqueEvidence
) -> LearnerCritiqueEvidence:
    if learner_critique_evidence_content_hash(evidence) != evidence.evidence_hash:
        raise DomainViolation("Learner critique evidence hash mismatch")
    if path.exists():
        existing = read_learner_critique_evidence(path)
        if existing != evidence:
            raise DomainViolation(f"Learner critique evidence path is immutable: {path}") from None
        return existing
    payload = json.dumps(evidence.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(payload, encoding="utf-8", newline="\n")
    try:
        os.link(temporary_path, path)
    except FileExistsError:
        temporary_path.unlink(missing_ok=True)
        existing = read_learner_critique_evidence(path)
        if existing != evidence:
            raise DomainViolation(f"Learner critique evidence path is immutable: {path}") from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return read_learner_critique_evidence(path)


__all__ = [
    "LearnerCritiqueEvidence",
    "build_learner_critique_evidence",
    "learner_critique_evidence_content_hash",
    "persist_learner_critique_evidence",
    "read_learner_critique_evidence",
]
