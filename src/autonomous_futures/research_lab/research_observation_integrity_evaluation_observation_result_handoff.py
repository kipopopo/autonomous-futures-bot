# ruff: noqa
from __future__ import annotations
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal
from pydantic import Field, field_validator, model_validator
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .research_observation_integrity_evaluation_observation import (
    ResearchObservationIntegrityEvaluationObservationInput,
)
from .research_observation_integrity_evaluation_observation_result_input import (
    load_verified_research_observation_integrity_evaluation_observation_review,
)


class ResearchObservationIntegrityEvaluationObservationHandoff(DomainModel):
    handoff_version: Literal[1] = 1
    handoff_status: Literal["verified_audit_only"] = "verified_audit_only"
    research_run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    source_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_observation_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
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
            raise ValueError("handoff created_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_hash(
        self,
    ) -> ResearchObservationIntegrityEvaluationObservationHandoff:
        if (
            research_observation_integrity_evaluation_observation_handoff_content_hash(self)
            != self.handoff_hash
        ):
            raise ValueError("handoff hash mismatch")
        return self


def research_observation_integrity_evaluation_observation_handoff_content_hash(
    handoff: ResearchObservationIntegrityEvaluationObservationHandoff,
) -> str:
    payload = handoff.model_dump(mode="json", exclude={"created_at", "handoff_hash"})
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_verified_research_observation_integrity_evaluation_observation_handoff(
    path: Path,
    *,
    observation_input: ResearchObservationIntegrityEvaluationObservationInput,
    created_at: datetime | None = None,
) -> ResearchObservationIntegrityEvaluationObservationHandoff:
    review = load_verified_research_observation_integrity_evaluation_observation_review(
        path, observation_input=observation_input
    )
    timestamp = created_at or datetime.now(UTC)
    provisional = ResearchObservationIntegrityEvaluationObservationHandoff.model_construct(
        handoff_version=1,
        handoff_status="verified_audit_only",
        research_run_id=review.research_run_id,
        source_review_hash=review.review_hash,
        source_observation_input_hash=review.source_observation_input_hash,
        source_evaluation_input_hash=review.source_evaluation_input_hash,
        source_observation_hash=review.source_observation_hash,
        check_count=review.check_count,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        created_at=timestamp,
        handoff_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationHandoff.model_validate(
        {
            **provisional.model_dump(),
            "handoff_hash": research_observation_integrity_evaluation_observation_handoff_content_hash(
                provisional
            ),
        }
    )
