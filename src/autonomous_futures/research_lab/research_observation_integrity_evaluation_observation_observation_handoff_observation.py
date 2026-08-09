# ruff: noqa
from __future__ import annotations
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal
from pydantic import Field, model_validator, field_validator
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .research_observation_integrity_evaluation_observation_observation_result_handoff import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoff,
    research_observation_integrity_evaluation_observation_observation_handoff_content_hash,
)


class ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationInput(
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

    @field_validator("observed_at")
    @classmethod
    def utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() != timedelta(0):
            raise ValueError("observed_at must be UTC")
        return v.astimezone(UTC)

    @model_validator(mode="after")
    def valid(
        self,
    ) -> ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationInput:
        if (
            research_observation_integrity_evaluation_observation_observation_handoff_observation_content_hash(
                self
            )
            != self.observation_hash
        ):
            raise ValueError("observation hash mismatch")
        return self


def research_observation_integrity_evaluation_observation_observation_handoff_observation_content_hash(
    o: ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationInput,
) -> str:
    return sha256(
        json.dumps(
            o.model_dump(mode="json", exclude={"observed_at", "observation_hash"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def build_research_observation_integrity_evaluation_observation_observation_handoff_observation_input(
    handoff: ResearchObservationIntegrityEvaluationObservationObservationHandoff,
    *,
    observed_at: datetime | None = None,
) -> ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationInput:
    try:
        ResearchObservationIntegrityEvaluationObservationObservationHandoff.model_validate(
            handoff.model_dump()
        )
    except ValueError as e:
        raise DomainViolation("handoff hash mismatch") from e
    p = ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationInput.model_construct(
        observation_version=1,
        observation_status="audit_only",
        research_run_id=handoff.research_run_id,
        source_handoff_hash=handoff.handoff_hash,
        source_review_hash=handoff.source_review_hash,
        source_observation_hash=handoff.source_observation_hash,
        source_evaluation_input_hash=handoff.source_evaluation_input_hash,
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        observed_at=observed_at or datetime.now(UTC),
        observation_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationInput.model_validate(
        {
            **p.model_dump(),
            "observation_hash": research_observation_integrity_evaluation_observation_observation_handoff_observation_content_hash(
                p
            ),
        }
    )
