# ruff: noqa
from __future__ import annotations
import json
from hashlib import sha256
from datetime import datetime
from pathlib import Path
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..domain.errors import DomainViolation
from .research_observation_integrity_review_3ca_input import (
    load_verified_research_observation_integrity_review_3ca,
)


class ResearchObservationIntegrityReview3cbHandoff(BaseModel):
    model_config = ConfigDict(frozen=True)
    handoff_version: int = 1
    handoff_status: str = "verified_audit_only"
    review_status: str = "verified"
    review_scope: str = "audit_integrity_only"
    research_run_id: str
    source_review_hash: str = Field(min_length=64, max_length=64)
    source_observation_hash: str = Field(min_length=64, max_length=64)
    source_handoff_hash: str = Field(min_length=64, max_length=64)
    source_evaluation_input_hash: str = Field(min_length=64, max_length=64)
    check_count: int = 3
    promotion_state: str = "unpromoted"
    paper_activation: bool = False
    execution_authority: bool = False
    created_at: datetime
    handoff_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_safety(self) -> "ResearchObservationIntegrityReview3cbHandoff":
        if (
            self.handoff_status,
            self.review_status,
            self.review_scope,
            self.promotion_state,
            self.paper_activation,
            self.execution_authority,
        ) != (
            "verified_audit_only",
            "verified",
            "audit_integrity_only",
            "unpromoted",
            False,
            False,
        ):
            raise ValueError("invalid audit-only handoff safety state")
        return self


def research_observation_integrity_review_3cb_content_hash(
    value: ResearchObservationIntegrityReview3cbHandoff,
) -> str:
    payload = value.model_dump(mode="json", exclude={"created_at", "handoff_hash"})
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def handoff_verified_research_observation_integrity_review_3cb(
    *, review_path: Path, observation: Any
) -> ResearchObservationIntegrityReview3cbHandoff:
    review = load_verified_research_observation_integrity_review_3ca(
        review_path, observation=observation
    )
    payload = ResearchObservationIntegrityReview3cbHandoff.model_construct(
        research_run_id=review.research_run_id,
        source_review_hash=review.review_hash,
        source_observation_hash=review.source_observation_hash,
        source_handoff_hash=review.source_handoff_hash,
        source_evaluation_input_hash=review.source_evaluation_input_hash,
        created_at=review.reviewed_at,
        handoff_hash="0" * 64,
    )
    return ResearchObservationIntegrityReview3cbHandoff.model_validate(
        {
            **payload.model_dump(),
            "handoff_hash": research_observation_integrity_review_3cb_content_hash(payload),
        }
    )
