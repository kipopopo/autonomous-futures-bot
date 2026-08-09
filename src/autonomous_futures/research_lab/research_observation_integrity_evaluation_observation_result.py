from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .research_observation_integrity_evaluation_observation import (
    ResearchObservationIntegrityEvaluationObservationInput,
)


class ResearchObservationIntegrityEvaluationObservationReview(DomainModel):
    """Non-authoritative review result for the integrity-evaluation observer."""

    review_version: Literal[1] = 1
    review_status: Literal["verified"] = "verified"
    review_scope: Literal["audit_integrity_only"] = "audit_integrity_only"
    research_run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    source_observation_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evaluation_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    check_ids: tuple[
        Literal["audit_only_status"],
        Literal["audit_integrity_scope"],
        Literal["safety_locks"],
    ] = ("audit_only_status", "audit_integrity_scope", "safety_locks")
    check_count: Literal[3] = 3
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    reviewed_at: datetime
    review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("reviewed_at")
    @classmethod
    def reviewed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError(
                "research integrity evaluation observation review reviewed_at must be "
                "timezone-aware UTC"
            )
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_hash(self) -> ResearchObservationIntegrityEvaluationObservationReview:
        if (
            research_observation_integrity_evaluation_observation_review_content_hash(self)
            != self.review_hash
        ):
            raise ValueError("research integrity evaluation observation review hash mismatch")
        return self


def research_observation_integrity_evaluation_observation_review_content_hash(
    review: ResearchObservationIntegrityEvaluationObservationReview,
) -> str:
    payload = review.model_dump(mode="json", exclude={"reviewed_at", "review_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def review_research_observation_integrity_evaluation_observation(
    observation_input: ResearchObservationIntegrityEvaluationObservationInput,
    *,
    reviewed_at: datetime | None = None,
) -> ResearchObservationIntegrityEvaluationObservationReview:
    """Verify only fixed audit-integrity semantics; never evaluate quality."""
    try:
        verified_input = ResearchObservationIntegrityEvaluationObservationInput.model_validate(
            observation_input.model_dump()
        )
    except ValueError as exc:
        raise DomainViolation(
            "research integrity evaluation observation input hash mismatch"
        ) from exc

    timestamp = reviewed_at or datetime.now(UTC)
    provisional = ResearchObservationIntegrityEvaluationObservationReview.model_construct(
        review_version=1,
        review_status="verified",
        review_scope="audit_integrity_only",
        research_run_id=verified_input.research_run_id,
        source_observation_input_hash=verified_input.input_hash,
        source_evaluation_input_hash=verified_input.source_evaluation_input_hash,
        source_observation_hash=verified_input.source_observation_hash,
        check_ids=("audit_only_status", "audit_integrity_scope", "safety_locks"),
        check_count=verified_input.check_count,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        reviewed_at=timestamp,
        review_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationReview.model_validate(
        {
            "research_run_id": verified_input.research_run_id,
            "source_observation_input_hash": verified_input.input_hash,
            "source_evaluation_input_hash": verified_input.source_evaluation_input_hash,
            "source_observation_hash": verified_input.source_observation_hash,
            "reviewed_at": timestamp,
            "review_hash": (
                research_observation_integrity_evaluation_observation_review_content_hash(
                    provisional
                )
            ),
        }
    )


__all__ = [
    "ResearchObservationIntegrityEvaluationObservationReview",
    "research_observation_integrity_evaluation_observation_review_content_hash",
    "review_research_observation_integrity_evaluation_observation",
]
