"""Structured, evidence-only feedback derived from rejected Creator qualification."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from .qualification_artifacts import CreatorCandidateQualificationArtifact, QualificationGateResult


class CreatorQualificationFailureFeedback(DomainModel):
    feedback_version: Literal[1] = 1
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification_policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    failed_gates: tuple[QualificationGateResult, ...] = Field(min_length=1)
    failure_reason_codes: tuple[str, ...] = Field(min_length=1)
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_feedback(self) -> CreatorQualificationFailureFeedback:
        gate_ids = tuple(gate.gate_id for gate in self.failed_gates)
        if gate_ids != tuple(sorted(set(gate_ids))):
            raise ValueError("feedback gates must be sorted and unique")
        if self.failure_reason_codes != tuple(sorted(set(self.failure_reason_codes))):
            raise ValueError("feedback reason codes must be sorted and unique")
        return self


def build_creator_qualification_failure_feedback(
    qualification: CreatorCandidateQualificationArtifact,
) -> CreatorQualificationFailureFeedback | None:
    """Project rejected qualification gates for a future Learner/critic consumer."""
    if qualification.decision != "rejected":
        return None
    failed_gates = tuple(gate for gate in qualification.gates if not gate.passed)
    if not failed_gates:
        raise DataQualityError("rejected qualification requires failed gates")
    return CreatorQualificationFailureFeedback(
        candidate_id=qualification.candidate_id,
        candidate_artifact_hash=qualification.candidate_artifact_hash,
        bundle_hash=qualification.bundle_hash,
        dataset_registry_hash=qualification.dataset_registry_hash,
        qualification_hash=qualification.qualification_hash,
        qualification_policy_id=qualification.qualification_policy_id or "policy-unbound",
        failed_gates=tuple(sorted(failed_gates, key=lambda gate: gate.gate_id)),
        failure_reason_codes=tuple(sorted({gate.reason_code for gate in failed_gates})),
    )


__all__ = [
    "CreatorQualificationFailureFeedback",
    "build_creator_qualification_failure_feedback",
]
