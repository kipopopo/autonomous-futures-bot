"""Injected, non-authoritative Learner/Critic review boundary."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from hashlib import sha256
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_core import PydanticCustomError

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from .creator_failure_feedback import CreatorQualificationFailureFeedback


class LearnerCriticRequest(DomainModel):
    research_run_id: str = Field(pattern=r"^run-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    feedback: CreatorQualificationFailureFeedback
    input_evidence_refs: tuple[str, ...] = Field(min_length=1)
    output_schema_id: Literal["learner-critic-v1"] = "learner-critic-v1"
    attempt: int = Field(ge=1, strict=True)

    @field_validator("input_evidence_refs")
    @classmethod
    def evidence_refs_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("critic evidence references must be non-empty")
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ValueError("critic evidence references must be sorted and unique")
        return values

    @model_validator(mode="after")
    def feedback_binding_matches(self) -> LearnerCriticRequest:
        if (
            self.feedback.candidate_id != self.candidate_id
            or self.feedback.candidate_artifact_hash != self.candidate_artifact_hash
        ):
            raise ValueError("critic feedback candidate binding mismatch")
        return self


class LearnerCritique(DomainModel):
    review_version: Literal[1] = 1
    review_id: str = Field(pattern=r"^review-[a-z0-9][a-z0-9-]{0,63}$")
    research_run_id: str = Field(pattern=r"^run-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    decision: Literal["revise", "stop"]
    failure_reason_codes: tuple[str, ...] = Field(min_length=1)
    revision_actions: tuple[str, ...] = Field(min_length=1)
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
            raise PydanticCustomError("critic_lists_empty", "critic lists must be non-empty")
        if values != tuple(sorted(set(values))):
            raise PydanticCustomError(
                "critic_list_not_canonical",
                "critic list must be sorted and unique",
                {"field": "list"},
            )
        return values


def learner_critique_content_hash(critique: LearnerCritique) -> str:
    payload = critique.model_dump(mode="json", exclude={"review_hash"})
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def parse_learner_critique(payload: Mapping[str, object]) -> LearnerCritique:
    try:
        provisional = LearnerCritique.model_validate({**payload, "review_hash": "0" * 64})
    except Exception as exc:
        raise DataQualityError("invalid Learner critic review") from exc
    return provisional.model_copy(
        update={"review_hash": learner_critique_content_hash(provisional)}
    )


def learner_critic_schema_diagnostics(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Return field/type diagnostics without returning untrusted input values."""
    try:
        LearnerCritique.model_validate({**payload, "review_hash": "0" * 64})
    except ValidationError as exc:
        diagnostics = {
            f"{'.'.join(str(part) for part in error['loc']) or 'root'}:{error['type']}"
            for error in exc.errors()
        }
        return tuple(sorted(diagnostics))
    return ()


class LearnerCriticResult(DomainModel):
    decision: Literal["accepted", "rejected"]
    critique: LearnerCritique | None = None
    reason_codes: tuple[str, ...] = Field(min_length=1)
    schema_diagnostics: tuple[str, ...] = ()
    raw_output: None = None
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False

    @field_validator("reason_codes")
    @classmethod
    def reason_codes_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))) or any(not value for value in values):
            raise ValueError("critic reason codes must be sorted and unique")
        return values

    @field_validator("schema_diagnostics")
    @classmethod
    def schema_diagnostics_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))) or any(not value for value in values):
            raise ValueError("critic schema diagnostics must be sorted and unique")
        return values

    @model_validator(mode="after")
    def decision_matches_critique(self) -> LearnerCriticResult:
        if (self.decision == "accepted") != (self.critique is not None):
            raise ValueError("critic accepted result requires critique")
        return self


CriticTransport = Callable[[LearnerCriticRequest], Mapping[str, object]]


class LearnerCritic:
    def __init__(self, transport: CriticTransport) -> None:
        self.transport = transport

    def review(self, request: LearnerCriticRequest) -> LearnerCriticResult:
        try:
            payload = self.transport(request)
        except Exception as exc:
            code = getattr(exc, "code", None)
            reason = (
                code if isinstance(code, str) and code.startswith("provider_") else "provider_error"
            )
            return LearnerCriticResult(decision="rejected", reason_codes=(reason,))
        try:
            critique = parse_learner_critique(payload)
        except DataQualityError:
            return LearnerCriticResult(
                decision="rejected",
                reason_codes=("schema_rejected",),
                schema_diagnostics=learner_critic_schema_diagnostics(payload),
            )
        if critique.research_run_id != request.research_run_id:
            return LearnerCriticResult(decision="rejected", reason_codes=("research_run_mismatch",))
        if critique.candidate_id != request.candidate_id:
            return LearnerCriticResult(decision="rejected", reason_codes=("candidate_mismatch",))
        if critique.failure_reason_codes != request.feedback.failure_reason_codes:
            return LearnerCriticResult(decision="rejected", reason_codes=("feedback_mismatch",))
        return LearnerCriticResult(
            decision="accepted", critique=critique, reason_codes=("critic_review_valid",)
        )


__all__ = [
    "CriticTransport",
    "LearnerCritic",
    "LearnerCriticRequest",
    "LearnerCriticResult",
    "LearnerCritique",
    "learner_critique_content_hash",
    "learner_critic_schema_diagnostics",
    "parse_learner_critique",
]
