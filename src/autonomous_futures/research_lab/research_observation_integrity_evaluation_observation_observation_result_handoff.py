# ruff: noqa
from __future__ import annotations
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .research_observation_integrity_evaluation_observation_observation_result_input import (
    load_verified_research_observation_integrity_evaluation_observation_observation_review,
)
from .research_observation_integrity_evaluation_observation_observation import (
    ResearchObservationIntegrityEvaluationObservationObservationInput,
)


class ResearchObservationIntegrityEvaluationObservationObservationHandoff(DomainModel):
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
    def valid(self) -> ResearchObservationIntegrityEvaluationObservationObservationHandoff:
        if (
            research_observation_integrity_evaluation_observation_observation_handoff_content_hash(
                self
            )
            != self.handoff_hash
        ):
            raise ValueError("handoff hash mismatch")
        return self


def research_observation_integrity_evaluation_observation_observation_handoff_content_hash(
    h: ResearchObservationIntegrityEvaluationObservationObservationHandoff,
) -> str:
    return sha256(
        json.dumps(
            h.model_dump(mode="json", exclude={"created_at", "handoff_hash"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def build_verified_research_observation_integrity_evaluation_observation_observation_handoff(
    path: Path,
    *,
    observation: ResearchObservationIntegrityEvaluationObservationObservationInput,
    created_at: datetime | None = None,
) -> ResearchObservationIntegrityEvaluationObservationObservationHandoff:
    r = load_verified_research_observation_integrity_evaluation_observation_observation_review(
        path, observation=observation
    )
    p = ResearchObservationIntegrityEvaluationObservationObservationHandoff.model_construct(
        handoff_version=1,
        handoff_status="verified_audit_only",
        research_run_id=r.research_run_id,
        source_review_hash=r.source_review_hash,
        source_observation_hash=r.source_observation_hash,
        source_handoff_hash=r.source_handoff_hash,
        source_evaluation_input_hash=r.source_evaluation_input_hash,
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        created_at=created_at or datetime.now(UTC),
        handoff_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationObservationHandoff.model_validate(
        {
            **p.model_dump(),
            "handoff_hash": research_observation_integrity_evaluation_observation_observation_handoff_content_hash(
                p
            ),
        }
    )
