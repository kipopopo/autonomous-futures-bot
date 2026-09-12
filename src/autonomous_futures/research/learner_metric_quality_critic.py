from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
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
    LearnerMetricQualityGateResult,
    LearnerMetricQualityPolicy,
)
from .learner_metric_quality_decision_input import load_verified_learner_metric_quality_decision

LearnerMetricQualityCriticAction = Literal[
    "add_cross_symbol_validation",
    "add_temporal_holdout",
    "change_target_definition",
    "preserve_causal_features",
    "stop_baseline",
]


class LearnerMetricQualityCriticRequest(DomainModel):
    """Verified failed learner-quality evidence prepared for one Critic request."""

    request_version: Literal[1] = 1
    critic_run_id: str = Field(pattern=r"^run-[a-z0-9][a-z0-9-]{0,63}$")
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
    source_decision: Literal["failed"] = "failed"
    failed_gates: tuple[LearnerMetricQualityGateResult, ...] = Field(min_length=1)
    failure_reason_codes: tuple[str, ...] = Field(min_length=1)
    input_evidence_refs: tuple[str, ...] = Field(min_length=1)
    output_schema_id: Literal["learner-metric-quality-critic-v1"] = (
        "learner-metric-quality-critic-v1"
    )
    attempt: Literal[1] = 1
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("failure_reason_codes", "input_evidence_refs")
    @classmethod
    def lists_are_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("critic request lists must be non-empty")
        if values != tuple(sorted(set(values))):
            raise ValueError("critic request lists must be sorted and unique")
        return values

    @model_validator(mode="after")
    def failed_gates_are_canonical(self) -> LearnerMetricQualityCriticRequest:
        gate_ids = tuple(gate.gate_id for gate in self.failed_gates)
        if gate_ids != tuple(sorted(set(gate_ids))):
            raise ValueError("critic request gates must be sorted and unique")
        if any(gate.passed for gate in self.failed_gates):
            raise ValueError("critic request gates must all be failed")
        expected_reasons = tuple(sorted({gate.reason_code for gate in self.failed_gates}))
        if self.failure_reason_codes != expected_reasons:
            raise ValueError("critic request failure reasons must match failed gates")
        return self


def learner_metric_quality_critic_content_hash(
    request: LearnerMetricQualityCriticRequest,
) -> str:
    payload = request.model_dump(mode="json", exclude={"request_hash"})
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_verified_learner_metric_quality_critic_request(
    decision_path: Path,
    review_path: Path,
    metric_evaluation_path: Path,
    *,
    learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    policy: LearnerMetricQualityPolicy,
    critic_run_id: str,
) -> LearnerMetricQualityCriticRequest:
    """Build a Critic request only from a verified failed metric-quality decision."""
    decision = load_verified_learner_metric_quality_decision(
        decision_path,
        review_path,
        metric_evaluation_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
    )
    if decision.decision != "failed":
        raise DataQualityError("learner-quality Critic request requires a failed decision")
    failed_gates = tuple(gate for gate in decision.gates if not gate.passed)
    if not failed_gates:
        raise DataQualityError("failed learner-quality decision has no failed gates")
    try:
        provisional = LearnerMetricQualityCriticRequest(
            critic_run_id=critic_run_id,
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
            failed_gates=failed_gates,
            failure_reason_codes=tuple(sorted({gate.reason_code for gate in failed_gates})),
            input_evidence_refs=tuple(
                sorted(
                    (
                        f"decision/{decision.decision_id}",
                        f"metric/{decision.metric_evaluation_run_id}",
                        f"review/{decision.review_id}",
                    )
                )
            ),
            request_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError("invalid learner-quality Critic request: " + str(exc)) from None
    return provisional.model_copy(
        update={"request_hash": learner_metric_quality_critic_content_hash(provisional)}
    )


class LearnerMetricQualityCritique(DomainModel):
    """Strict advisory response from one learner-quality Critic."""

    review_version: Literal[1] = 1
    review_id: str = Field(pattern=r"^review-learner-quality-critic-[a-z0-9][a-z0-9-]{0,63}$")
    critic_run_id: str = Field(pattern=r"^run-[a-z0-9][a-z0-9-]{0,63}$")
    decision_id: str = Field(pattern=r"^metric-quality-decision-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    decision: Literal["revise", "stop"]
    failure_reason_codes: tuple[str, ...] = Field(min_length=1)
    revision_actions: tuple[LearnerMetricQualityCriticAction, ...] = Field(min_length=1)
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("failure_reason_codes", "revision_actions")
    @classmethod
    def lists_are_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("learner-quality Critic lists must be non-empty")
        if values != tuple(sorted(set(values))):
            raise ValueError("learner-quality Critic lists must be sorted and unique")
        return values

    @model_validator(mode="after")
    def decision_matches_actions(self) -> LearnerMetricQualityCritique:
        has_stop = "stop_baseline" in self.revision_actions
        if (self.decision == "stop") != has_stop:
            raise ValueError("learner-quality Critic decision does not match actions")
        return self


def learner_metric_quality_critique_content_hash(
    critique: LearnerMetricQualityCritique,
) -> str:
    payload = critique.model_dump(mode="json", exclude={"review_hash"})
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def parse_learner_metric_quality_critique(
    payload: Mapping[str, object],
) -> LearnerMetricQualityCritique:
    try:
        provisional = LearnerMetricQualityCritique.model_validate(
            {**payload, "review_hash": "0" * 64}
        )
    except Exception as exc:
        raise DataQualityError("invalid learner-quality Critic review") from exc
    return provisional.model_copy(
        update={"review_hash": learner_metric_quality_critique_content_hash(provisional)}
    )


def verify_learner_metric_quality_critic_binding(
    *,
    request: LearnerMetricQualityCriticRequest,
    evidence: LearnerMetricQualityCritiqueEvidence,
) -> None:
    """Verify one Critic evidence artifact against its exact request."""
    if learner_metric_quality_critic_content_hash(request) != request.request_hash:
        raise DataQualityError("learner-quality Critic request hash mismatch")
    if learner_metric_quality_critic_evidence_content_hash(evidence) != evidence.evidence_hash:
        raise DataQualityError("learner-quality Critic evidence hash mismatch")
    try:
        critique = LearnerMetricQualityCritique(
            review_id=evidence.review_id,
            critic_run_id=evidence.critic_run_id,
            decision_id=evidence.decision_id,
            candidate_id=evidence.candidate_id,
            decision=evidence.critique_decision,
            failure_reason_codes=evidence.failure_reason_codes,
            revision_actions=evidence.revision_actions,
            review_hash=evidence.review_hash,
        )
    except ValidationError as exc:
        raise DataQualityError("learner-quality Critic evidence review is invalid") from exc
    if learner_metric_quality_critique_content_hash(critique) != critique.review_hash:
        raise DataQualityError("learner-quality Critic review hash mismatch")
    fields = (
        "critic_run_id",
        "decision_id",
        "decision_hash",
        "metric_evaluation_run_id",
        "metric_evaluation_hash",
        "learner_id",
        "learner_artifact_hash",
        "candidate_id",
        "candidate_artifact_hash",
        "bundle_hash",
        "dataset_registry_hash",
        "policy_id",
        "policy_hash",
        "failure_reason_codes",
        "input_evidence_refs",
    )
    for field in fields:
        request_value = getattr(request, field)
        evidence_value = getattr(evidence, field)
        if request_value != evidence_value:
            raise DataQualityError("learner-quality Critic evidence binding is invalid")


def learner_metric_quality_critic_schema_diagnostics(
    payload: Mapping[str, object],
) -> tuple[str, ...]:
    try:
        LearnerMetricQualityCritique.model_validate({**payload, "review_hash": "0" * 64})
    except ValidationError as exc:
        return tuple(
            sorted(
                {
                    f"{'.'.join(str(part) for part in error['loc']) or 'root'}:{error['type']}"
                    for error in exc.errors()
                }
            )
        )
    return ()


_SAFE_PROVIDER_METADATA_KEYS = frozenset(
    {
        "choice_count",
        "content_kind",
        "content_length",
        "content_sha256",
        "error_code",
        "error_reason",
        "error_status",
        "finish_reason",
        "response_keys",
        "status_code",
        "transport_error_type",
    }
)


def _safe_provider_metadata(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {key: value[key] for key in sorted(_SAFE_PROVIDER_METADATA_KEYS) if key in value}


LearnerMetricQualityCriticTransport = Callable[
    [LearnerMetricQualityCriticRequest], Mapping[str, object]
]


class LearnerMetricQualityCriticResult(DomainModel):
    """Safe in-memory Critic result; raw provider output is never retained."""

    decision: Literal["accepted", "rejected"]
    critique: LearnerMetricQualityCritique | None = None
    reason_codes: tuple[str, ...] = Field(min_length=1)
    schema_diagnostics: tuple[str, ...] = ()
    provider_metadata: dict[str, object] = Field(default_factory=dict)
    raw_output: None = None
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False

    @field_validator("reason_codes", "schema_diagnostics")
    @classmethod
    def diagnostics_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))) or any(not value for value in values):
            raise ValueError("Critic diagnostics must be sorted and unique")
        return values

    @model_validator(mode="after")
    def decision_matches_critique(self) -> LearnerMetricQualityCriticResult:
        if (self.decision == "accepted") != (self.critique is not None):
            raise ValueError("accepted learner-quality Critic result requires critique")
        return self


class LearnerMetricQualityCritic:
    def __init__(self, transport: LearnerMetricQualityCriticTransport) -> None:
        self.transport = transport

    @staticmethod
    def schema_diagnostics(payload: Mapping[str, object]) -> tuple[str, ...]:
        return learner_metric_quality_critic_schema_diagnostics(payload)

    def review(
        self, request: LearnerMetricQualityCriticRequest
    ) -> LearnerMetricQualityCriticResult:
        try:
            payload = self.transport(request)
        except Exception as exc:
            code = getattr(exc, "code", None)
            reason = (
                code if isinstance(code, str) and code.startswith("provider_") else "provider_error"
            )
            return LearnerMetricQualityCriticResult(
                decision="rejected",
                reason_codes=(reason,),
                provider_metadata=_safe_provider_metadata(getattr(exc, "metadata", None)),
            )
        provider_metadata = _safe_provider_metadata(getattr(payload, "metadata", None))
        try:
            critique = parse_learner_metric_quality_critique(payload)
        except DataQualityError:
            return LearnerMetricQualityCriticResult(
                decision="rejected",
                reason_codes=("schema_rejected",),
                schema_diagnostics=learner_metric_quality_critic_schema_diagnostics(payload),
                provider_metadata=provider_metadata,
            )
        if critique.critic_run_id != request.critic_run_id:
            return LearnerMetricQualityCriticResult(
                decision="rejected", reason_codes=("critic_run_mismatch",)
            )
        if critique.decision_id != request.decision_id:
            return LearnerMetricQualityCriticResult(
                decision="rejected", reason_codes=("decision_mismatch",)
            )
        if critique.candidate_id != request.candidate_id:
            return LearnerMetricQualityCriticResult(
                decision="rejected", reason_codes=("candidate_mismatch",)
            )
        if critique.failure_reason_codes != request.failure_reason_codes:
            return LearnerMetricQualityCriticResult(
                decision="rejected", reason_codes=("failure_feedback_mismatch",)
            )
        return LearnerMetricQualityCriticResult(
            decision="accepted",
            critique=critique,
            reason_codes=("critic_review_valid",),
            provider_metadata=provider_metadata,
        )


class LearnerMetricQualityCritiqueEvidence(DomainModel):
    """Immutable advisory evidence from a verified learner-quality Critic review."""

    evidence_version: Literal[1] = 1
    evidence_id: str = Field(pattern=r"^learner-quality-critic-evidence-[a-z0-9][a-z0-9-]{0,63}$")
    review_id: str = Field(pattern=r"^review-learner-quality-critic-[a-z0-9][a-z0-9-]{0,63}$")
    review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    critic_run_id: str = Field(pattern=r"^run-[a-z0-9][a-z0-9-]{0,63}$")
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_id: str = Field(pattern=r"^metric-quality-decision-[a-z0-9][a-z0-9-]{0,63}$")
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
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
    source_decision: Literal["failed"] = "failed"
    failure_reason_codes: tuple[str, ...] = Field(min_length=1)
    critique_decision: Literal["revise", "stop"]
    revision_actions: tuple[LearnerMetricQualityCriticAction, ...] = Field(min_length=1)
    input_evidence_refs: tuple[str, ...] = Field(min_length=1)
    provider_metadata: dict[str, object] = Field(default_factory=dict)
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    created_at: datetime
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("failure_reason_codes", "input_evidence_refs")
    @classmethod
    def lists_are_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("Critic evidence lists must be non-empty")
        if values != tuple(sorted(set(values))):
            raise ValueError("Critic evidence lists must be sorted and unique")
        return values

    @field_validator("created_at")
    @classmethod
    def created_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("Critic evidence created_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def action_decision_is_consistent(self) -> LearnerMetricQualityCritiqueEvidence:
        if (self.critique_decision == "stop") != ("stop_baseline" in self.revision_actions):
            raise ValueError("Critic evidence decision does not match actions")
        return self


def learner_metric_quality_critic_evidence_content_hash(
    evidence: LearnerMetricQualityCritiqueEvidence,
) -> str:
    payload = evidence.model_dump(mode="json", exclude={"created_at", "evidence_hash"})
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_learner_metric_quality_critic_evidence(
    *,
    request: LearnerMetricQualityCriticRequest,
    critique: LearnerMetricQualityCritique,
    evidence_id: str,
    created_at: datetime,
    provider_metadata: Mapping[str, object] | None = None,
) -> LearnerMetricQualityCritiqueEvidence:
    """Build advisory evidence from one verified request and accepted Critic response."""
    if learner_metric_quality_critic_content_hash(request) != request.request_hash:
        raise DomainViolation("learner-quality Critic request hash mismatch")
    if learner_metric_quality_critique_content_hash(critique) != critique.review_hash:
        raise DomainViolation("learner-quality Critic review hash mismatch")
    if (
        critique.critic_run_id != request.critic_run_id
        or critique.decision_id != request.decision_id
        or critique.candidate_id != request.candidate_id
        or critique.failure_reason_codes != request.failure_reason_codes
    ):
        raise DataQualityError("learner-quality Critic review binding is invalid")
    try:
        provisional = LearnerMetricQualityCritiqueEvidence(
            evidence_id=evidence_id,
            review_id=critique.review_id,
            review_hash=critique.review_hash,
            critic_run_id=request.critic_run_id,
            request_hash=request.request_hash,
            decision_id=request.decision_id,
            decision_hash=request.decision_hash,
            metric_evaluation_run_id=request.metric_evaluation_run_id,
            metric_evaluation_hash=request.metric_evaluation_hash,
            learner_id=request.learner_id,
            learner_artifact_hash=request.learner_artifact_hash,
            candidate_id=request.candidate_id,
            candidate_artifact_hash=request.candidate_artifact_hash,
            bundle_hash=request.bundle_hash,
            dataset_registry_hash=request.dataset_registry_hash,
            policy_id=request.policy_id,
            policy_hash=request.policy_hash,
            failure_reason_codes=request.failure_reason_codes,
            critique_decision=critique.decision,
            revision_actions=critique.revision_actions,
            input_evidence_refs=request.input_evidence_refs,
            provider_metadata=_safe_provider_metadata(provider_metadata),
            created_at=created_at,
            evidence_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError("invalid learner-quality Critic evidence: " + str(exc)) from None
    return provisional.model_copy(
        update={"evidence_hash": learner_metric_quality_critic_evidence_content_hash(provisional)}
    )


def read_learner_metric_quality_critic_evidence(
    path: Path,
) -> LearnerMetricQualityCritiqueEvidence:
    """Read and verify one persisted learner-quality Critic evidence artifact."""
    try:
        evidence = LearnerMetricQualityCritiqueEvidence.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except (ValidationError, ValueError) as exc:
        raise DataQualityError("invalid persisted learner-quality Critic evidence") from exc
    if learner_metric_quality_critic_evidence_content_hash(evidence) != evidence.evidence_hash:
        raise DomainViolation(f"learner-quality Critic evidence hash mismatch: {path}")
    return evidence


def persist_learner_metric_quality_critic_evidence(
    path: Path,
    evidence: LearnerMetricQualityCritiqueEvidence,
) -> LearnerMetricQualityCritiqueEvidence:
    """Persist learner-quality Critic evidence atomically and write-once."""
    if learner_metric_quality_critic_evidence_content_hash(evidence) != evidence.evidence_hash:
        raise DomainViolation("learner-quality Critic evidence hash mismatch")
    if path.exists():
        existing = read_learner_metric_quality_critic_evidence(path)
        if existing != evidence:
            raise DomainViolation(f"learner-quality Critic evidence path is immutable: {path}")
        return existing

    payload = json.dumps(evidence.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(payload, encoding="utf-8", newline="\n")
        os.link(temporary_path, path)
    except FileExistsError:
        existing = read_learner_metric_quality_critic_evidence(path)
        if existing != evidence:
            raise DomainViolation(
                f"learner-quality Critic evidence path is immutable: {path}"
            ) from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return read_learner_metric_quality_critic_evidence(path)


__all__ = [
    "LearnerMetricQualityCritic",
    "LearnerMetricQualityCriticAction",
    "LearnerMetricQualityCriticRequest",
    "LearnerMetricQualityCriticResult",
    "LearnerMetricQualityCritique",
    "LearnerMetricQualityCritiqueEvidence",
    "LearnerMetricQualityCriticTransport",
    "build_learner_metric_quality_critic_evidence",
    "build_verified_learner_metric_quality_critic_request",
    "learner_metric_quality_critic_content_hash",
    "learner_metric_quality_critic_evidence_content_hash",
    "learner_metric_quality_critic_schema_diagnostics",
    "learner_metric_quality_critique_content_hash",
    "parse_learner_metric_quality_critique",
    "persist_learner_metric_quality_critic_evidence",
    "read_learner_metric_quality_critic_evidence",
    "verify_learner_metric_quality_critic_binding",
]
