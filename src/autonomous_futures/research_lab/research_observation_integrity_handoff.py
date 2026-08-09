from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel
from .research_observation_evaluation import ResearchObservationEvaluationInput
from .research_observation_integrity_input import (
    load_verified_research_observation_integrity_review,
)


class ResearchObservationIntegrityHandoff(DomainModel):
    """Non-authoritative bounded handoff for a verified integrity review."""

    handoff_version: Literal[1] = 1
    handoff_status: Literal["verified_audit_only"] = "verified_audit_only"
    research_run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    source_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evaluation_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
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
                "research observation integrity handoff created_at must be timezone-aware UTC"
            )
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_hash(self) -> ResearchObservationIntegrityHandoff:
        if research_observation_integrity_handoff_content_hash(self) != self.handoff_hash:
            raise ValueError("research observation integrity handoff hash mismatch")
        return self


def research_observation_integrity_handoff_content_hash(
    handoff: ResearchObservationIntegrityHandoff,
) -> str:
    payload = handoff.model_dump(mode="json", exclude={"created_at", "handoff_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def build_verified_research_observation_integrity_handoff(
    path: Path,
    *,
    evaluation: ResearchObservationEvaluationInput,
    created_at: datetime | None = None,
) -> ResearchObservationIntegrityHandoff:
    """Build an audit-only handoff from the shared verified persisted loader."""
    review = load_verified_research_observation_integrity_review(path, evaluation=evaluation)
    timestamp = created_at or datetime.now(UTC)
    provisional = ResearchObservationIntegrityHandoff.model_construct(
        handoff_version=1,
        handoff_status="verified_audit_only",
        research_run_id=review.research_run_id,
        source_review_hash=review.review_hash,
        source_evaluation_input_hash=review.source_evaluation_input_hash,
        check_count=len(review.check_ids),
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        created_at=timestamp,
        handoff_hash="0" * 64,
    )
    return ResearchObservationIntegrityHandoff.model_validate(
        {
            "research_run_id": review.research_run_id,
            "source_review_hash": review.review_hash,
            "source_evaluation_input_hash": review.source_evaluation_input_hash,
            "check_count": len(review.check_ids),
            "created_at": timestamp,
            "handoff_hash": research_observation_integrity_handoff_content_hash(provisional),
        }
    )


__all__ = [
    "ResearchObservationIntegrityHandoff",
    "build_verified_research_observation_integrity_handoff",
    "research_observation_integrity_handoff_content_hash",
]
