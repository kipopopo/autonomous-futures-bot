from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .creator_artifacts import CreatorCandidateArtifact
from .learner_artifacts import LearnerArtifact
from .learner_metric_quality_review import (
    LearnerMetricQualityReviewEvidence,
    learner_metric_quality_review_content_hash,
)
from .learner_metric_quality_review_input import load_verified_learner_metric_quality_review

LearnerMetricQualityDecision = Literal["failed", "passed"]
LearnerMetricQualityComparator = Literal["gte", "lte", "eq"]


class LearnerMetricQualityPolicyGate(DomainModel):
    metric_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")
    comparator: LearnerMetricQualityComparator
    threshold: Decimal

    @field_validator("threshold")
    @classmethod
    def threshold_is_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("metric quality policy threshold must be finite")
        return value


class LearnerMetricQualityPolicy(DomainModel):
    policy_version: Literal[1] = 1
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    minimum_windows: int = Field(ge=1, strict=True)
    gates: tuple[LearnerMetricQualityPolicyGate, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def gates_are_sorted_and_unique(self) -> LearnerMetricQualityPolicy:
        metric_ids = tuple(gate.metric_id for gate in self.gates)
        if len(set(metric_ids)) != len(metric_ids) or metric_ids != tuple(sorted(metric_ids)):
            raise ValueError("metric quality policy gates must be sorted and unique")
        return self


class LearnerMetricQualityObservation(DomainModel):
    window_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    metric_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")
    observed: Decimal | None = None

    @field_validator("observed")
    @classmethod
    def observed_is_finite(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError("metric quality observed value must be finite")
        return value


class LearnerMetricQualityGateResult(DomainModel):
    gate_id: str = Field(pattern=r"^(minimum_windows|window_[0-9]{4}_[a-z0-9][a-z0-9_]{0,63})$")
    window_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    metric_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")
    passed: bool
    observed: Decimal | None = None
    threshold: Decimal
    comparator: LearnerMetricQualityComparator
    reason_code: str = Field(pattern=r"^[a-z0-9_.-]{1,63}$")

    @field_validator("observed", "threshold")
    @classmethod
    def gate_values_are_finite(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError("metric quality gate values must be finite")
        return value

    @model_validator(mode="after")
    def gate_identity_is_valid(self) -> LearnerMetricQualityGateResult:
        if self.gate_id == "minimum_windows":
            if self.window_id is not None or self.metric_id is not None:
                raise ValueError("minimum window gate cannot bind a metric window")
        elif self.window_id is None or self.metric_id is None:
            raise ValueError("metric quality gate requires window and metric identity")
        return self


class LearnerMetricQualityDecisionEvidence(DomainModel):
    """Policy-bound metric quality evidence; it is not learner qualification."""

    decision_version: Literal[1] = 1
    decision_id: str = Field(pattern=r"^metric-quality-decision-[a-z0-9][a-z0-9-]{0,63}$")
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
    decision: LearnerMetricQualityDecision
    observations: tuple[LearnerMetricQualityObservation, ...] = Field(min_length=1)
    gates: tuple[LearnerMetricQualityGateResult, ...] = Field(min_length=1)
    windows_evaluated: int = Field(ge=0, strict=True)
    status: Literal["evaluated"] = "evaluated"
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    evaluated_at: datetime
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("metric quality decision evaluated_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def evidence_is_sorted_and_consistent(self) -> LearnerMetricQualityDecisionEvidence:
        observation_keys = tuple((item.window_id, item.metric_id) for item in self.observations)
        if len(set(observation_keys)) != len(observation_keys) or observation_keys != tuple(
            sorted(observation_keys)
        ):
            raise ValueError("metric quality observations must be sorted and unique")
        gate_ids = tuple(gate.gate_id for gate in self.gates)
        if len(set(gate_ids)) != len(gate_ids) or gate_ids != tuple(sorted(gate_ids)):
            raise ValueError("metric quality gates must be sorted and unique")
        if self.decision == "passed" and not all(gate.passed for gate in self.gates):
            raise ValueError("passed metric quality decision requires every gate to pass")
        return self


def learner_metric_quality_policy_content_hash(policy: LearnerMetricQualityPolicy) -> str:
    canonical = json.dumps(
        policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return sha256(canonical).hexdigest()


def learner_metric_quality_decision_content_hash(
    evidence: LearnerMetricQualityDecisionEvidence,
) -> str:
    payload = evidence.model_dump(mode="json", exclude={"evaluated_at", "decision_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def _compare(
    observed: Decimal | None,
    *,
    comparator: LearnerMetricQualityComparator,
    threshold: Decimal,
) -> tuple[bool, str]:
    if observed is None:
        return False, "metric_missing"
    passed = (
        observed >= threshold
        if comparator == "gte"
        else observed <= threshold
        if comparator == "lte"
        else observed == threshold
    )
    if passed:
        return True, "metric_passed"
    return (
        False,
        "metric_below_threshold"
        if comparator == "gte"
        else "metric_above_threshold"
        if comparator == "lte"
        else "metric_mismatch",
    )


def build_learner_metric_quality_decision(
    review: LearnerMetricQualityReviewEvidence,
    *,
    policy: LearnerMetricQualityPolicy,
    evaluated_at: datetime,
) -> LearnerMetricQualityDecisionEvidence:
    """Build policy-bound quality evidence from one verified review artifact."""
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != UTC.utcoffset(evaluated_at):
        raise DataQualityError("metric quality decision evaluated_at must be timezone-aware UTC")
    if learner_metric_quality_review_content_hash(review) != review.review_hash:
        raise DomainViolation("metric quality review evidence hash mismatch")

    observed_by_window = {
        (window.window_id, metric.metric_id): metric.value
        for window in review.windows
        for metric in window.metrics
    }
    observations: list[LearnerMetricQualityObservation] = []
    gates: list[LearnerMetricQualityGateResult] = []
    minimum_windows_passed = len(review.windows) >= policy.minimum_windows
    gates.append(
        LearnerMetricQualityGateResult(
            gate_id="minimum_windows",
            passed=minimum_windows_passed,
            observed=Decimal(len(review.windows)),
            threshold=Decimal(policy.minimum_windows),
            comparator="gte",
            reason_code=(
                "minimum_windows_passed"
                if minimum_windows_passed
                else "minimum_windows_below_threshold"
            ),
        )
    )
    for window_index, window in enumerate(review.windows):
        for policy_gate in policy.gates:
            observed = observed_by_window.get((window.window_id, policy_gate.metric_id))
            observations.append(
                LearnerMetricQualityObservation(
                    window_id=window.window_id,
                    metric_id=policy_gate.metric_id,
                    observed=observed,
                )
            )
            passed, reason_code = _compare(
                observed,
                comparator=policy_gate.comparator,
                threshold=policy_gate.threshold,
            )
            gates.append(
                LearnerMetricQualityGateResult(
                    gate_id=f"window_{window_index:04d}_{policy_gate.metric_id}",
                    window_id=window.window_id,
                    metric_id=policy_gate.metric_id,
                    passed=passed,
                    observed=observed,
                    threshold=policy_gate.threshold,
                    comparator=policy_gate.comparator,
                    reason_code=reason_code,
                )
            )

    decision: LearnerMetricQualityDecision = (
        "passed" if all(gate.passed for gate in gates) else "failed"
    )
    try:
        provisional = LearnerMetricQualityDecisionEvidence(
            decision_id=f"metric-quality-decision-{review.review_id.removeprefix('metric-quality-review-')}",
            review_id=review.review_id,
            review_hash=review.review_hash,
            metric_evaluation_run_id=review.metric_evaluation_run_id,
            metric_evaluation_hash=review.metric_evaluation_hash,
            learner_id=review.learner_id,
            learner_artifact_hash=review.learner_artifact_hash,
            candidate_id=review.candidate_id,
            candidate_artifact_hash=review.candidate_artifact_hash,
            bundle_hash=review.bundle_hash,
            dataset_registry_hash=review.dataset_registry_hash,
            policy_id=policy.policy_id,
            policy_hash=learner_metric_quality_policy_content_hash(policy),
            decision=decision,
            observations=tuple(
                sorted(observations, key=lambda item: (item.window_id, item.metric_id))
            ),
            gates=tuple(sorted(gates, key=lambda gate: gate.gate_id)),
            windows_evaluated=len(review.windows),
            evaluated_at=evaluated_at,
            decision_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError("invalid metric quality decision evidence: " + str(exc)) from None
    return provisional.model_copy(
        update={"decision_hash": learner_metric_quality_decision_content_hash(provisional)}
    )


def evaluate_persisted_learner_metric_quality(
    review_path: Path,
    metric_evaluation_path: Path,
    *,
    learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    policy: LearnerMetricQualityPolicy,
    evaluated_at: datetime,
) -> LearnerMetricQualityDecisionEvidence:
    """Evaluate a verified persisted review without persisting or promoting anything."""
    review = load_verified_learner_metric_quality_review(
        review_path,
        metric_evaluation_path,
        learner=learner,
        candidate=candidate,
    )
    return build_learner_metric_quality_decision(
        review,
        policy=policy,
        evaluated_at=evaluated_at,
    )


def read_learner_metric_quality_decision(
    path: Path,
) -> LearnerMetricQualityDecisionEvidence:
    """Read and verify one persisted metric-quality decision evidence artifact."""
    try:
        evidence = LearnerMetricQualityDecisionEvidence.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except (ValidationError, ValueError) as exc:
        raise DataQualityError("invalid persisted learner metric quality decision") from exc
    if learner_metric_quality_decision_content_hash(evidence) != evidence.decision_hash:
        raise DomainViolation(f"learner metric quality decision hash mismatch: {path}")
    return evidence


def write_learner_metric_quality_decision(
    path: Path,
    evidence: LearnerMetricQualityDecisionEvidence,
) -> LearnerMetricQualityDecisionEvidence:
    """Persist metric-quality decision evidence atomically and write-once."""
    if learner_metric_quality_decision_content_hash(evidence) != evidence.decision_hash:
        raise DomainViolation("learner metric quality decision hash mismatch")
    if path.exists():
        existing = read_learner_metric_quality_decision(path)
        if existing != evidence:
            raise DomainViolation(f"learner metric quality decision path is immutable: {path}")
        return existing

    payload = json.dumps(evidence.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(payload, encoding="utf-8", newline="\n")
        os.link(temporary_path, path)
    except FileExistsError:
        existing = read_learner_metric_quality_decision(path)
        if existing != evidence:
            raise DomainViolation(
                f"learner metric quality decision path is immutable: {path}"
            ) from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return read_learner_metric_quality_decision(path)


__all__ = [
    "LearnerMetricQualityComparator",
    "LearnerMetricQualityDecision",
    "LearnerMetricQualityDecisionEvidence",
    "LearnerMetricQualityGateResult",
    "LearnerMetricQualityObservation",
    "LearnerMetricQualityPolicy",
    "LearnerMetricQualityPolicyGate",
    "build_learner_metric_quality_decision",
    "evaluate_persisted_learner_metric_quality",
    "learner_metric_quality_decision_content_hash",
    "learner_metric_quality_policy_content_hash",
    "read_learner_metric_quality_decision",
    "write_learner_metric_quality_decision",
]
