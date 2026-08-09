# ruff: noqa
from __future__ import annotations
import json
from datetime import datetime
from hashlib import sha256
from typing import Literal
from pydantic import Field, model_validator
from ..domain.contracts import DomainModel


class ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservationReview(
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
    check_ids: tuple[
        Literal["audit_only_status", "audit_integrity_scope", "safety_locks"],
        Literal["audit_only_status", "audit_integrity_scope", "safety_locks"],
        Literal["audit_only_status", "audit_integrity_scope", "safety_locks"],
    ]
    check_count: Literal[3] = 3
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    reviewed_at: datetime
    review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def valid(
        self,
    ) -> ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservationReview:
        if (
            len(set(self.check_ids)) != 3
            or research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_review_content_hash(
                self
            )
            != self.review_hash
        ):
            raise ValueError("review hash mismatch")
        return self


def research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_review_content_hash(
    r: ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservationReview,
) -> str:
    return sha256(
        json.dumps(
            r.model_dump(mode="json", exclude={"reviewed_at", "review_hash"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
