from __future__ import annotations

import json
import os
from datetime import UTC, datetime
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
from .learner_metric_quality_decision import (
    LearnerMetricQualityDecision,
    LearnerMetricQualityPolicy,
)
from .learner_metric_quality_qualification_input import (
    LearnerMetricQualityQualificationInput,
    build_verified_learner_metric_quality_qualification_input,
    learner_metric_quality_qualification_input_content_hash,
)

LearnerMetricQualityQualificationDecision = Literal["qualified", "rejected"]


class LearnerMetricQualityQualificationPolicy(DomainModel):
    """Separate policy for deriving qualification evidence from verified quality evidence."""

    policy_version: Literal[1] = 1
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    required_metric_quality_policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    required_metric_quality_policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    minimum_windows: int = Field(ge=1, strict=True)


class LearnerMetricQualityQualificationGateResult(DomainModel):
    gate_id: Literal["metric_quality_decision", "minimum_windows"]
    passed: bool
    observed_windows: int | None = Field(default=None, ge=0, strict=True)
    minimum_windows: int | None = Field(default=None, ge=1, strict=True)
    source_decision: LearnerMetricQualityDecision | None = None
    required_decision: Literal["passed"] | None = None
    reason_code: str = Field(pattern=r"^[a-z0-9_.-]{1,63}$")

    @model_validator(mode="after")
    def validate_gate_shape(self) -> LearnerMetricQualityQualificationGateResult:
        if self.gate_id == "minimum_windows":
            if (
                self.observed_windows is None
                or self.minimum_windows is None
                or self.source_decision is not None
                or self.required_decision is not None
            ):
                raise ValueError("minimum window gate has invalid evidence")
        elif (
            self.source_decision is None
            or self.required_decision is None
            or self.observed_windows is not None
            or self.minimum_windows is not None
        ):
            raise ValueError("metric-quality decision gate has invalid evidence")
        return self


class LearnerMetricQualityQualificationEvidence(DomainModel):
    """In-memory qualification evidence; it never changes learner or candidate state."""

    qualification_version: Literal[1] = 1
    qualification_id: str = Field(pattern=r"^metric-quality-qualification-[a-z0-9][a-z0-9-]{0,63}$")
    qualification_input_id: str = Field(
        pattern=r"^metric-quality-qualification-input-[a-z0-9][a-z0-9-]{0,63}$"
    )
    qualification_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
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
    source_policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    source_policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification_policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    qualification_policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_decision: LearnerMetricQualityDecision
    decision: LearnerMetricQualityQualificationDecision
    gates: tuple[LearnerMetricQualityQualificationGateResult, ...] = Field(
        min_length=2, max_length=2
    )
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
            raise ValueError("metric quality qualification evaluated_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_evidence_contract(self) -> LearnerMetricQualityQualificationEvidence:
        gate_ids = tuple(gate.gate_id for gate in self.gates)
        if gate_ids != ("metric_quality_decision", "minimum_windows"):
            raise ValueError("metric quality qualification gates must be canonical")
        if self.decision == "qualified" and not all(gate.passed for gate in self.gates):
            raise ValueError("qualified decision requires every gate to pass")
        if self.decision == "rejected" and all(gate.passed for gate in self.gates):
            raise ValueError("rejected decision requires a failed gate")
        return self


def learner_metric_quality_qualification_policy_content_hash(
    policy: LearnerMetricQualityQualificationPolicy,
) -> str:
    canonical = json.dumps(
        policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return sha256(canonical).hexdigest()


def learner_metric_quality_qualification_content_hash(
    evidence: LearnerMetricQualityQualificationEvidence,
) -> str:
    payload = evidence.model_dump(mode="json", exclude={"evaluated_at", "qualification_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def _verify_handoff_and_policy(
    qualification_input: LearnerMetricQualityQualificationInput,
    qualification_policy: LearnerMetricQualityQualificationPolicy,
) -> None:
    if (
        learner_metric_quality_qualification_input_content_hash(qualification_input)
        != qualification_input.input_hash
    ):
        raise DomainViolation("metric quality qualification input hash mismatch")
    if (
        qualification_input.policy_id != qualification_policy.required_metric_quality_policy_id
        or qualification_input.policy_hash
        != qualification_policy.required_metric_quality_policy_hash
    ):
        raise DomainViolation("metric quality qualification source policy binding is invalid")


def _build_qualification_evidence(
    qualification_input: LearnerMetricQualityQualificationInput,
    *,
    qualification_policy: LearnerMetricQualityQualificationPolicy,
    evaluated_at: datetime,
) -> LearnerMetricQualityQualificationEvidence:
    _verify_handoff_and_policy(qualification_input, qualification_policy)
    minimum_windows_passed = (
        qualification_input.windows_evaluated >= qualification_policy.minimum_windows
    )
    source_decision_passed = qualification_input.decision == "passed"
    gates = (
        LearnerMetricQualityQualificationGateResult(
            gate_id="metric_quality_decision",
            passed=source_decision_passed,
            source_decision=qualification_input.decision,
            required_decision="passed",
            reason_code=(
                "metric_quality_decision_passed"
                if source_decision_passed
                else "metric_quality_decision_not_passed"
            ),
        ),
        LearnerMetricQualityQualificationGateResult(
            gate_id="minimum_windows",
            passed=minimum_windows_passed,
            observed_windows=qualification_input.windows_evaluated,
            minimum_windows=qualification_policy.minimum_windows,
            reason_code=(
                "minimum_windows_passed"
                if minimum_windows_passed
                else "minimum_windows_below_threshold"
            ),
        ),
    )
    decision: LearnerMetricQualityQualificationDecision = (
        "qualified" if all(gate.passed for gate in gates) else "rejected"
    )
    try:
        provisional = LearnerMetricQualityQualificationEvidence(
            qualification_id=(
                "metric-quality-qualification-"
                + qualification_input.input_id.removeprefix("metric-quality-qualification-input-")
            ),
            qualification_input_id=qualification_input.input_id,
            qualification_input_hash=qualification_input.input_hash,
            decision_id=qualification_input.decision_id,
            decision_hash=qualification_input.decision_hash,
            review_id=qualification_input.review_id,
            review_hash=qualification_input.review_hash,
            metric_evaluation_run_id=qualification_input.metric_evaluation_run_id,
            metric_evaluation_hash=qualification_input.metric_evaluation_hash,
            learner_id=qualification_input.learner_id,
            learner_artifact_hash=qualification_input.learner_artifact_hash,
            candidate_id=qualification_input.candidate_id,
            candidate_artifact_hash=qualification_input.candidate_artifact_hash,
            bundle_hash=qualification_input.bundle_hash,
            dataset_registry_hash=qualification_input.dataset_registry_hash,
            source_policy_id=qualification_input.policy_id,
            source_policy_hash=qualification_input.policy_hash,
            qualification_policy_id=qualification_policy.policy_id,
            qualification_policy_hash=learner_metric_quality_qualification_policy_content_hash(
                qualification_policy
            ),
            source_decision=qualification_input.decision,
            decision=decision,
            gates=gates,
            windows_evaluated=qualification_input.windows_evaluated,
            evaluated_at=evaluated_at,
            qualification_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError(
            "invalid metric quality qualification evidence: " + str(exc)
        ) from None
    return provisional.model_copy(
        update={
            "qualification_hash": learner_metric_quality_qualification_content_hash(provisional)
        }
    )


def build_verified_learner_metric_quality_qualification_evidence(
    decision_path: Path,
    review_path: Path,
    metric_evaluation_path: Path,
    *,
    learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    source_policy: LearnerMetricQualityPolicy,
    qualification_policy: LearnerMetricQualityQualificationPolicy,
    evaluated_at: datetime,
) -> LearnerMetricQualityQualificationEvidence:
    """Derive non-authoritative qualification evidence only from verified decision evidence."""
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != UTC.utcoffset(evaluated_at):
        raise DataQualityError(
            "metric quality qualification evaluated_at must be timezone-aware UTC"
        )
    qualification_input = build_verified_learner_metric_quality_qualification_input(
        decision_path,
        review_path,
        metric_evaluation_path,
        learner=learner,
        candidate=candidate,
        policy=source_policy,
        prepared_at=evaluated_at,
    )
    return _build_qualification_evidence(
        qualification_input,
        qualification_policy=qualification_policy,
        evaluated_at=evaluated_at,
    )


def read_learner_metric_quality_qualification_evidence(
    path: Path,
) -> LearnerMetricQualityQualificationEvidence:
    """Read one persisted metric-quality qualification evidence artifact."""
    try:
        evidence = LearnerMetricQualityQualificationEvidence.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except (ValidationError, ValueError) as exc:
        raise DataQualityError("invalid persisted metric quality qualification evidence") from exc
    if learner_metric_quality_qualification_content_hash(evidence) != evidence.qualification_hash:
        raise DomainViolation(f"metric quality qualification evidence hash mismatch: {path}")
    return evidence


def write_learner_metric_quality_qualification_evidence(
    path: Path,
    evidence: LearnerMetricQualityQualificationEvidence,
) -> LearnerMetricQualityQualificationEvidence:
    """Persist metric-quality qualification evidence atomically and write-once."""
    if learner_metric_quality_qualification_content_hash(evidence) != evidence.qualification_hash:
        raise DomainViolation("metric quality qualification evidence hash mismatch")
    if path.exists():
        existing = read_learner_metric_quality_qualification_evidence(path)
        if existing != evidence:
            raise DomainViolation(f"metric quality qualification path is immutable: {path}")
        return existing

    payload = json.dumps(evidence.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(payload, encoding="utf-8", newline="\n")
        os.link(temporary_path, path)
    except FileExistsError:
        existing = read_learner_metric_quality_qualification_evidence(path)
        if existing != evidence:
            raise DomainViolation(
                f"metric quality qualification path is immutable: {path}"
            ) from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return read_learner_metric_quality_qualification_evidence(path)


__all__ = [
    "LearnerMetricQualityQualificationDecision",
    "LearnerMetricQualityQualificationEvidence",
    "LearnerMetricQualityQualificationGateResult",
    "LearnerMetricQualityQualificationPolicy",
    "build_verified_learner_metric_quality_qualification_evidence",
    "learner_metric_quality_qualification_content_hash",
    "learner_metric_quality_qualification_policy_content_hash",
    "read_learner_metric_quality_qualification_evidence",
    "write_learner_metric_quality_qualification_evidence",
]
