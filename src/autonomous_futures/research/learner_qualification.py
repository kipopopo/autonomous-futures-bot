from __future__ import annotations

import json
import os
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
from .learner_artifacts import LearnerArtifact, verify_learner_artifact_binding
from .learner_quality_review import (
    LearnerQualityReviewEvidence,
    learner_quality_review_content_hash,
)
from .learner_training_evidence import (
    LearnerTrainingEvidence,
    learner_training_evidence_content_hash,
)

LearnerQualificationDecision = Literal["rejected", "qualified"]
LearnerQualificationComparator = Literal["gte", "lte", "eq"]


class LearnerQualificationPolicyGate(DomainModel):
    metric_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")
    comparator: LearnerQualificationComparator
    threshold: Decimal

    @field_validator("threshold")
    @classmethod
    def threshold_is_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("qualification threshold must be finite")
        return value


class LearnerQualificationPolicy(DomainModel):
    policy_version: Literal[1] = 1
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    minimum_windows: int = Field(ge=1, strict=True)
    gates: tuple[LearnerQualificationPolicyGate, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_gates(self) -> LearnerQualificationPolicy:
        metric_ids = tuple(gate.metric_id for gate in self.gates)
        if len(set(metric_ids)) != len(metric_ids) or metric_ids != tuple(sorted(metric_ids)):
            raise ValueError("qualification policy gates must be sorted and unique")
        return self


class LearnerQualificationMetric(DomainModel):
    window_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    metric_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")
    observed: Decimal | None = None

    @field_validator("observed")
    @classmethod
    def observed_is_finite(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError("qualification observed metric must be finite")
        return value


class LearnerQualificationGateResult(DomainModel):
    gate_id: str = Field(pattern=r"^(minimum_windows|window_[0-9]{4})$")
    window_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    metric_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")
    passed: bool
    observed: Decimal | None = None
    threshold: Decimal
    comparator: LearnerQualificationComparator
    reason_code: str = Field(pattern=r"^[a-z0-9_.-]{1,63}$")

    @field_validator("observed", "threshold")
    @classmethod
    def gate_values_are_finite(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError("qualification gate values must be finite")
        return value

    @model_validator(mode="after")
    def validate_gate_identity(self) -> LearnerQualificationGateResult:
        if self.gate_id == "minimum_windows":
            if self.window_id is not None or self.metric_id is not None:
                raise ValueError("minimum window gate cannot bind a metric window")
        elif self.window_id is None or self.metric_id is None:
            raise ValueError("metric gate requires window and metric identity")
        return self


class LearnerQualificationEvidence(DomainModel):
    """Immutable learner qualification evidence; it never grants execution authority."""

    qualification_version: Literal[1] = 1
    qualification_id: str = Field(pattern=r"^learner-qualification-[a-z0-9][a-z0-9-]{0,63}$")
    training_evidence_id: str = Field(pattern=r"^training-evidence-[a-z0-9][a-z0-9-]{0,63}$")
    training_evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_review_id: str = Field(pattern=r"^quality-review-[a-z0-9][a-z0-9-]{0,63}$")
    quality_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    learner_id: str = Field(pattern=r"^learner-[a-z0-9][a-z0-9-]{0,63}$")
    learner_run_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: LearnerQualificationDecision
    metrics: tuple[LearnerQualificationMetric, ...] = Field(min_length=1)
    gates: tuple[LearnerQualificationGateResult, ...] = Field(min_length=1)
    windows_evaluated: int = Field(ge=0, strict=True)
    status: Literal["evaluated"] = "evaluated"
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    evaluated_at: datetime
    qualification_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("qualification evaluated_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_evidence_contract(self) -> LearnerQualificationEvidence:
        metric_keys = tuple((metric.window_id, metric.metric_id) for metric in self.metrics)
        if len(set(metric_keys)) != len(metric_keys) or metric_keys != tuple(sorted(metric_keys)):
            raise ValueError("qualification metrics must be sorted and unique")
        gate_ids = tuple(gate.gate_id for gate in self.gates)
        if len(set(gate_ids)) != len(gate_ids) or gate_ids != tuple(sorted(gate_ids)):
            raise ValueError("qualification gates must be sorted and unique")
        if self.decision == "qualified" and not all(gate.passed for gate in self.gates):
            raise ValueError("qualified decision requires every gate to pass")
        return self


def learner_qualification_policy_content_hash(policy: LearnerQualificationPolicy) -> str:
    canonical = json.dumps(
        policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return sha256(canonical).hexdigest()


def learner_qualification_content_hash(evidence: LearnerQualificationEvidence) -> str:
    payload = evidence.model_dump(mode="json", exclude={"evaluated_at", "qualification_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def _verify_bindings(
    *,
    training_evidence: LearnerTrainingEvidence,
    quality_review: LearnerQualityReviewEvidence,
    output_artifact: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    policy: LearnerQualificationPolicy,
) -> None:
    if learner_training_evidence_content_hash(training_evidence) != training_evidence.evidence_hash:
        raise DataQualityError("training evidence hash is invalid")
    if learner_quality_review_content_hash(quality_review) != quality_review.review_hash:
        raise DataQualityError("quality review hash is invalid")
    try:
        verify_learner_artifact_binding(output_artifact, candidate)
    except DomainViolation as exc:
        raise DataQualityError("qualification output artifact binding is invalid") from exc
    if (
        training_evidence.output_artifact_hash != output_artifact.artifact_hash
        or training_evidence.learner_id != output_artifact.learner_id
        or training_evidence.learner_run_id != output_artifact.learner_run_id
        or training_evidence.candidate_id != output_artifact.candidate_id
        or training_evidence.candidate_artifact_hash != output_artifact.candidate_artifact_hash
        or training_evidence.bundle_hash != output_artifact.bundle_hash
        or training_evidence.dataset_registry_hash != output_artifact.dataset_registry_hash
    ):
        raise DataQualityError("qualification training evidence binding is invalid")
    if (
        quality_review.training_evidence_id != training_evidence.evidence_id
        or quality_review.training_evidence_hash != training_evidence.evidence_hash
        or quality_review.output_artifact_hash != output_artifact.artifact_hash
        or quality_review.learner_id != output_artifact.learner_id
        or quality_review.learner_run_id != output_artifact.learner_run_id
        or quality_review.candidate_id != output_artifact.candidate_id
        or quality_review.candidate_artifact_hash != output_artifact.candidate_artifact_hash
        or quality_review.bundle_hash != output_artifact.bundle_hash
        or quality_review.dataset_registry_hash != output_artifact.dataset_registry_hash
    ):
        raise DataQualityError("qualification quality review binding is invalid")
    if quality_review.review_conclusion != "observed_only" or quality_review.split != "holdout":
        raise DataQualityError("qualification requires observed-only holdout review evidence")
    if policy.minimum_windows < 1 or not policy.gates:
        raise DataQualityError("qualification policy is invalid")


def _compare(
    observed: Decimal | None,
    *,
    comparator: LearnerQualificationComparator,
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


def build_learner_qualification_evidence(
    *,
    training_evidence: LearnerTrainingEvidence,
    quality_review: LearnerQualityReviewEvidence,
    output_artifact: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    policy: LearnerQualificationPolicy,
    evaluated_at: datetime,
) -> LearnerQualificationEvidence:
    _verify_bindings(
        training_evidence=training_evidence,
        quality_review=quality_review,
        output_artifact=output_artifact,
        candidate=candidate,
        policy=policy,
    )
    review_metrics = {
        (window.window_id, metric.metric_id): metric.value
        for window in quality_review.windows
        for metric in window.metrics
    }
    metrics: list[LearnerQualificationMetric] = []
    gates: list[LearnerQualificationGateResult] = []
    window_count = len(quality_review.windows)
    minimum_windows_passed = window_count >= policy.minimum_windows
    gates.append(
        LearnerQualificationGateResult(
            gate_id="minimum_windows",
            passed=minimum_windows_passed,
            observed=Decimal(window_count),
            threshold=Decimal(policy.minimum_windows),
            comparator="gte",
            reason_code=(
                "minimum_windows_passed"
                if minimum_windows_passed
                else "minimum_windows_below_threshold"
            ),
        )
    )
    for window_index, window in enumerate(quality_review.windows):
        for policy_gate in policy.gates:
            observed = review_metrics.get((window.window_id, policy_gate.metric_id))
            metrics.append(
                LearnerQualificationMetric(
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
                LearnerQualificationGateResult(
                    gate_id=f"window_{window_index:04d}",
                    window_id=window.window_id,
                    metric_id=policy_gate.metric_id,
                    passed=passed,
                    observed=observed,
                    threshold=policy_gate.threshold,
                    comparator=policy_gate.comparator,
                    reason_code=reason_code,
                )
            )
    decision: LearnerQualificationDecision = (
        "qualified" if all(gate.passed for gate in gates) else "rejected"
    )
    try:
        provisional = LearnerQualificationEvidence(
            qualification_id=f"learner-qualification-{quality_review.review_run_id}",
            training_evidence_id=training_evidence.evidence_id,
            training_evidence_hash=training_evidence.evidence_hash,
            quality_review_id=quality_review.review_id,
            quality_review_hash=quality_review.review_hash,
            output_artifact_hash=output_artifact.artifact_hash,
            learner_id=output_artifact.learner_id,
            learner_run_id=output_artifact.learner_run_id,
            candidate_id=output_artifact.candidate_id,
            candidate_artifact_hash=output_artifact.candidate_artifact_hash,
            bundle_hash=output_artifact.bundle_hash,
            dataset_registry_hash=output_artifact.dataset_registry_hash,
            policy_id=policy.policy_id,
            policy_hash=learner_qualification_policy_content_hash(policy),
            decision=decision,
            metrics=tuple(sorted(metrics, key=lambda metric: (metric.window_id, metric.metric_id))),
            gates=tuple(sorted(gates, key=lambda gate: gate.gate_id)),
            windows_evaluated=window_count,
            evaluated_at=evaluated_at,
            qualification_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError("invalid learner qualification evidence: " + str(exc)) from None
    return provisional.model_copy(
        update={"qualification_hash": learner_qualification_content_hash(provisional)}
    )


def _read_evidence(path: Path) -> LearnerQualificationEvidence:
    try:
        evidence = LearnerQualificationEvidence.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError, ValueError) as exc:
        raise DomainViolation("learner qualification evidence hash or shape is invalid") from exc
    if learner_qualification_content_hash(evidence) != evidence.qualification_hash:
        raise DomainViolation("learner qualification evidence hash mismatch")
    return evidence


def _verify_persisted(
    evidence: LearnerQualificationEvidence,
    *,
    training_evidence: LearnerTrainingEvidence,
    quality_review: LearnerQualityReviewEvidence,
    output_artifact: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    policy: LearnerQualificationPolicy,
) -> None:
    _verify_bindings(
        training_evidence=training_evidence,
        quality_review=quality_review,
        output_artifact=output_artifact,
        candidate=candidate,
        policy=policy,
    )
    if (
        evidence.training_evidence_id != training_evidence.evidence_id
        or evidence.training_evidence_hash != training_evidence.evidence_hash
        or evidence.quality_review_id != quality_review.review_id
        or evidence.quality_review_hash != quality_review.review_hash
        or evidence.output_artifact_hash != output_artifact.artifact_hash
        or evidence.learner_id != output_artifact.learner_id
        or evidence.learner_run_id != output_artifact.learner_run_id
        or evidence.candidate_id != output_artifact.candidate_id
        or evidence.candidate_artifact_hash != output_artifact.candidate_artifact_hash
        or evidence.bundle_hash != output_artifact.bundle_hash
        or evidence.dataset_registry_hash != output_artifact.dataset_registry_hash
        or evidence.policy_id != policy.policy_id
        or evidence.policy_hash != learner_qualification_policy_content_hash(policy)
    ):
        raise DomainViolation("learner qualification evidence binding is invalid")


def read_learner_qualification_evidence(
    path: Path,
    *,
    training_evidence: LearnerTrainingEvidence,
    quality_review: LearnerQualityReviewEvidence,
    output_artifact: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    policy: LearnerQualificationPolicy,
) -> LearnerQualificationEvidence:
    evidence = _read_evidence(path)
    _verify_persisted(
        evidence,
        training_evidence=training_evidence,
        quality_review=quality_review,
        output_artifact=output_artifact,
        candidate=candidate,
        policy=policy,
    )
    return evidence


def write_learner_qualification_evidence(
    path: Path,
    evidence: LearnerQualificationEvidence,
    *,
    training_evidence: LearnerTrainingEvidence,
    quality_review: LearnerQualityReviewEvidence,
    output_artifact: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    policy: LearnerQualificationPolicy,
) -> LearnerQualificationEvidence:
    if path.exists():
        existing = read_learner_qualification_evidence(
            path,
            training_evidence=training_evidence,
            quality_review=quality_review,
            output_artifact=output_artifact,
            candidate=candidate,
            policy=policy,
        )
        if existing != evidence:
            raise DomainViolation(
                f"learner qualification evidence path is immutable: {path}"
            ) from None
        return existing

    if learner_qualification_content_hash(evidence) != evidence.qualification_hash:
        raise DomainViolation("learner qualification evidence hash mismatch")
    _verify_persisted(
        evidence,
        training_evidence=training_evidence,
        quality_review=quality_review,
        output_artifact=output_artifact,
        candidate=candidate,
        policy=policy,
    )
    payload = json.dumps(evidence.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(payload, encoding="utf-8", newline="\n")
    try:
        os.link(temporary_path, path)
    except FileExistsError:
        temporary_path.unlink(missing_ok=True)
        existing = read_learner_qualification_evidence(
            path,
            training_evidence=training_evidence,
            quality_review=quality_review,
            output_artifact=output_artifact,
            candidate=candidate,
            policy=policy,
        )
        if existing != evidence:
            raise DomainViolation(
                f"learner qualification evidence path is immutable: {path}"
            ) from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return read_learner_qualification_evidence(
        path,
        training_evidence=training_evidence,
        quality_review=quality_review,
        output_artifact=output_artifact,
        candidate=candidate,
        policy=policy,
    )


__all__ = [
    "LearnerQualificationComparator",
    "LearnerQualificationDecision",
    "LearnerQualificationEvidence",
    "LearnerQualificationGateResult",
    "LearnerQualificationMetric",
    "LearnerQualificationPolicy",
    "LearnerQualificationPolicyGate",
    "build_learner_qualification_evidence",
    "learner_qualification_content_hash",
    "learner_qualification_policy_content_hash",
    "read_learner_qualification_evidence",
    "write_learner_qualification_evidence",
]
