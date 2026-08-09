from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel
from .research_observation_integrity_evaluation import (
    ResearchObservationIntegrityEvaluationInput,
)
from .research_observation_integrity_evaluation_input import (
    load_verified_research_observation_integrity_evaluation_review,
)


class ResearchObservationIntegrityEvaluationHandoff(DomainModel):
    """Non-authoritative bounded handoff for a verified integrity evaluation."""

    handoff_version: Literal[1] = 1
    handoff_status: Literal["verified_audit_only"] = "verified_audit_only"
    research_run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    source_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evaluation_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    check_count: Literal[3] = 3
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    created_at: datetime
    handoff_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("created_at")
    @classmethod
    def created_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError(
                "research integrity evaluation handoff created_at must be timezone-aware UTC"
            )
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_hash(self) -> ResearchObservationIntegrityEvaluationHandoff:
        if (
            research_observation_integrity_evaluation_handoff_content_hash(self)
            != self.handoff_hash
        ):
            raise ValueError("research integrity evaluation handoff hash mismatch")
        return self


def research_observation_integrity_evaluation_handoff_content_hash(
    handoff: ResearchObservationIntegrityEvaluationHandoff,
) -> str:
    payload = handoff.model_dump(mode="json", exclude={"created_at", "handoff_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def build_verified_research_observation_integrity_evaluation_handoff(
    path: Path,
    *,
    evaluation: ResearchObservationIntegrityEvaluationInput,
    created_at: datetime | None = None,
) -> ResearchObservationIntegrityEvaluationHandoff:
    """Build a handoff only from a Phase 3AW verified persisted review."""
    review = load_verified_research_observation_integrity_evaluation_review(
        path,
        evaluation=evaluation,
    )
    timestamp = created_at or datetime.now(UTC)
    provisional = ResearchObservationIntegrityEvaluationHandoff.model_construct(
        handoff_version=1,
        handoff_status="verified_audit_only",
        research_run_id=review.research_run_id,
        source_review_hash=review.review_hash,
        source_evaluation_input_hash=review.source_evaluation_input_hash,
        source_observation_hash=review.source_observation_hash,
        check_count=len(review.check_ids),
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        created_at=timestamp,
        handoff_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationHandoff.model_validate(
        {
            "research_run_id": review.research_run_id,
            "source_review_hash": review.review_hash,
            "source_evaluation_input_hash": review.source_evaluation_input_hash,
            "source_observation_hash": review.source_observation_hash,
            "check_count": len(review.check_ids),
            "created_at": timestamp,
            "handoff_hash": research_observation_integrity_evaluation_handoff_content_hash(
                provisional
            ),
        }
    )


__all__ = [
    "ResearchObservationIntegrityEvaluationHandoff",
    "build_verified_research_observation_integrity_evaluation_handoff",
    "research_observation_integrity_evaluation_handoff_content_hash",
]
