# ruff: noqa
from __future__ import annotations
import json
from datetime import datetime
from hashlib import sha256
from typing import Literal
from pydantic import Field, model_validator
from ..domain.contracts import DomainModel


class ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservation(
    DomainModel
):
    observation_version: Literal[1] = 1
    observation_status: Literal["audit_only"] = "audit_only"
    research_run_id: str
    source_handoff_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evaluation_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    check_count: Literal[3] = 3
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    observed_at: datetime
    observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def valid(
        self,
    ) -> ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservation:
        if (
            research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_content_hash(
                self
            )
            != self.observation_hash
        ):
            raise ValueError("observation hash mismatch")
        return self


def research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_content_hash(
    o: ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservation,
) -> str:
    return sha256(
        json.dumps(
            o.model_dump(mode="json", exclude={"observed_at", "observation_hash"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
