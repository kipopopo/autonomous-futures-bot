from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .research_observation_integrity_observation import (
    ResearchObservationIntegrityObservationInput,
)


class ResearchObservationIntegrityEvaluationInput(DomainModel):
    """Non-authoritative deterministic input scoped solely to audit integrity."""

    evaluation_version: Literal[1] = 1
    evaluation_status: Literal["audit_only"] = "audit_only"
    review_scope: Literal["audit_integrity_only"] = "audit_integrity_only"
    research_run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    source_observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evaluation_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    check_count: Literal[3] = 3
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    prepared_at: datetime
    evaluation_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("prepared_at")
    @classmethod
    def prepared_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError(
                "research integrity evaluation input prepared_at must be timezone-aware UTC"
            )
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_hash(self) -> ResearchObservationIntegrityEvaluationInput:
        if (
            research_observation_integrity_evaluation_content_hash(self)
            != self.evaluation_input_hash
        ):
            raise ValueError("research integrity evaluation input hash mismatch")
        return self


def research_observation_integrity_evaluation_content_hash(
    input_data: ResearchObservationIntegrityEvaluationInput,
) -> str:
    payload = input_data.model_dump(mode="json", exclude={"prepared_at", "evaluation_input_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def build_research_observation_integrity_evaluation_input(
    observation: ResearchObservationIntegrityObservationInput,
    *,
    prepared_at: datetime | None = None,
) -> ResearchObservationIntegrityEvaluationInput:
    """Accept only a hash-verified integrity observation for integrity review."""
    try:
        verified_observation = ResearchObservationIntegrityObservationInput.model_validate(
            observation.model_dump()
        )
    except ValueError as exc:
        raise DomainViolation("research integrity observation input hash mismatch") from exc

    timestamp = prepared_at or datetime.now(UTC)
    provisional = ResearchObservationIntegrityEvaluationInput.model_construct(
        evaluation_version=1,
        evaluation_status="audit_only",
        review_scope="audit_integrity_only",
        research_run_id=verified_observation.research_run_id,
        source_observation_hash=verified_observation.input_hash,
        source_review_hash=verified_observation.source_review_hash,
        source_evaluation_input_hash=verified_observation.source_evaluation_input_hash,
        check_count=verified_observation.check_count,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        prepared_at=timestamp,
        evaluation_input_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationInput.model_validate(
        {
            "research_run_id": verified_observation.research_run_id,
            "source_observation_hash": verified_observation.input_hash,
            "source_review_hash": verified_observation.source_review_hash,
            "source_evaluation_input_hash": verified_observation.source_evaluation_input_hash,
            "check_count": verified_observation.check_count,
            "prepared_at": timestamp,
            "evaluation_input_hash": research_observation_integrity_evaluation_content_hash(
                provisional
            ),
        }
    )


__all__ = [
    "ResearchObservationIntegrityEvaluationInput",
    "build_research_observation_integrity_evaluation_input",
    "research_observation_integrity_evaluation_content_hash",
]
