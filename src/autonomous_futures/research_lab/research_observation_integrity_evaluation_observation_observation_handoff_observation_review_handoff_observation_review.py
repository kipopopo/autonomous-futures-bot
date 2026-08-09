# ruff: noqa
from __future__ import annotations
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal
from pydantic import Field, model_validator, field_validator
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationInput,
)


class ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReview(
    DomainModel
):
    review_version: Literal[1] = 1
    review_status: Literal["verified"] = "verified"
    review_scope: Literal["audit_integrity_only"] = "audit_integrity_only"
    research_run_id: str
    source_observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_handoff_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evaluation_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    check_ids: tuple[str, str, str] = ("audit_only_status", "audit_integrity_scope", "safety_locks")
    check_count: Literal[3] = 3
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    reviewed_at: datetime
    review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("reviewed_at")
    @classmethod
    def utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() != timedelta(0):
            raise ValueError("reviewed_at must be UTC")
        return v.astimezone(UTC)

    @model_validator(mode="after")
    def valid(
        self,
    ) -> ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReview:
        if (
            research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_content_hash(
                self
            )
            != self.review_hash
        ):
            raise ValueError("review hash mismatch")
        return self


def research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_content_hash(
    r: ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReview,
) -> str:
    return sha256(
        json.dumps(
            r.model_dump(mode="json", exclude={"reviewed_at", "review_hash"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def build_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review(
    observation: ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationInput,
    *,
    reviewed_at: datetime | None = None,
) -> ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReview:
    try:
        ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationInput.model_validate(
            observation.model_dump()
        )
    except ValueError as e:
        raise DomainViolation("observation hash mismatch") from e
    p = ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReview.model_construct(
        review_version=1,
        review_status="verified",
        review_scope="audit_integrity_only",
        research_run_id=observation.research_run_id,
        source_observation_hash=observation.observation_hash,
        source_handoff_hash=observation.source_handoff_hash,
        source_review_hash=observation.source_review_hash,
        source_evaluation_input_hash=observation.source_evaluation_input_hash,
        check_ids=("audit_only_status", "audit_integrity_scope", "safety_locks"),
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        reviewed_at=reviewed_at or datetime.now(UTC),
        review_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReview.model_validate(
        {
            **p.model_dump(),
            "review_hash": research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_content_hash(
                p
            ),
        }
    )
