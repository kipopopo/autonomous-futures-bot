from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .creator_artifacts import CreatorCandidateArtifact
from .learner_artifacts import LearnerArtifact
from .learner_metric_quality_decision import (
    LearnerMetricQualityDecisionEvidence,
    LearnerMetricQualityPolicy,
)
from .learner_metric_quality_decision_input import load_verified_learner_metric_quality_decision


class LearnerMetricQualityQualificationInput(DomainModel):
    """Verified metric-quality input; it is not learner qualification evidence."""

    input_version: Literal[1] = 1
    input_id: str = Field(pattern=r"^metric-quality-qualification-input-[a-z0-9][a-z0-9-]{0,63}$")
    decision_id: str = Field(pattern=r"^metric-quality-decision-[a-z0-9][a-z0-9-]{0,63}$")
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_id: str = Field(pattern=r"^metric-quality-review-[a-z0-9][a-z0-9-]{0,63}$")
    review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    metric_evaluation_run_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    metric_evaluation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    learner_id: str = Field(pattern=r"^learner-[a-z0-9][a-z0-9-]{0,63}$")
    learner_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["failed", "passed"]
    windows_evaluated: int = Field(ge=0, strict=True)
    status: Literal["verified_decision_only"] = "verified_decision_only"
    qualification_status: Literal["not_evaluated"] = "not_evaluated"
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    prepared_at: datetime
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("prepared_at")
    @classmethod
    def prepared_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError(
                "metric quality qualification input prepared_at must be timezone-aware UTC"
            )
        return value.astimezone(UTC)


def learner_metric_quality_qualification_input_content_hash(
    input_evidence: LearnerMetricQualityQualificationInput,
) -> str:
    payload = input_evidence.model_dump(mode="json", exclude={"prepared_at", "input_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def _input_from_decision(
    decision: LearnerMetricQualityDecisionEvidence,
    *,
    prepared_at: datetime,
) -> LearnerMetricQualityQualificationInput:
    try:
        provisional = LearnerMetricQualityQualificationInput(
            input_id=(
                "metric-quality-qualification-input-"
                + decision.decision_id.removeprefix("metric-quality-decision-")
            ),
            decision_id=decision.decision_id,
            decision_hash=decision.decision_hash,
            review_id=decision.review_id,
            review_hash=decision.review_hash,
            metric_evaluation_run_id=decision.metric_evaluation_run_id,
            metric_evaluation_hash=decision.metric_evaluation_hash,
            learner_id=decision.learner_id,
            learner_artifact_hash=decision.learner_artifact_hash,
            candidate_id=decision.candidate_id,
            candidate_artifact_hash=decision.candidate_artifact_hash,
            bundle_hash=decision.bundle_hash,
            dataset_registry_hash=decision.dataset_registry_hash,
            policy_id=decision.policy_id,
            policy_hash=decision.policy_hash,
            decision=decision.decision,
            windows_evaluated=decision.windows_evaluated,
            prepared_at=prepared_at,
            input_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError("invalid metric quality qualification input: " + str(exc)) from None
    return provisional.model_copy(
        update={"input_hash": learner_metric_quality_qualification_input_content_hash(provisional)}
    )


def build_verified_learner_metric_quality_qualification_input(
    decision_path: Path,
    review_path: Path,
    metric_evaluation_path: Path,
    *,
    learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    policy: LearnerMetricQualityPolicy,
    prepared_at: datetime,
) -> LearnerMetricQualityQualificationInput:
    """Build an in-memory handoff from a fully verified metric-quality decision."""
    if prepared_at.tzinfo is None or prepared_at.utcoffset() != UTC.utcoffset(prepared_at):
        raise DataQualityError(
            "metric quality qualification input prepared_at must be timezone-aware UTC"
        )
    decision = load_verified_learner_metric_quality_decision(
        decision_path,
        review_path,
        metric_evaluation_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
    )
    if decision.data_source != "cached_only" or decision.exchange_access is not False:
        raise DomainViolation("metric quality decision safety binding is invalid")
    return _input_from_decision(decision, prepared_at=prepared_at)


__all__ = [
    "LearnerMetricQualityQualificationInput",
    "build_verified_learner_metric_quality_qualification_input",
    "learner_metric_quality_qualification_input_content_hash",
]
