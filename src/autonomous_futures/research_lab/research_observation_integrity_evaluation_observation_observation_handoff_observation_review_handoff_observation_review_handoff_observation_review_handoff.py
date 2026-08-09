# ruff: noqa
from __future__ import annotations
import json
from datetime import datetime
from hashlib import sha256
from typing import Literal
from pydantic import Field, model_validator
from ..domain.contracts import DomainModel


class ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoff(
    DomainModel
):
    handoff_version: Literal[1] = 1
    handoff_status: Literal["verified_audit_only"] = "verified_audit_only"
    research_run_id: str
    source_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_handoff_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evaluation_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    check_count: Literal[3] = 3
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    created_at: datetime
    handoff_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def valid(
        self,
    ) -> ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoff:
        if (
            research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_content_hash(
                self
            )
            != self.handoff_hash
        ):
            raise ValueError("handoff hash mismatch")
        return self


def research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_content_hash(
    h: ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoff,
) -> str:
    return sha256(
        json.dumps(
            h.model_dump(mode="json", exclude={"created_at", "handoff_hash"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
