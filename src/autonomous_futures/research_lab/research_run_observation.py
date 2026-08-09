from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .research_run_audit_handoff import ResearchRunAuditHandoff


class ResearchObservationInput(DomainModel):
    """Non-authoritative audit-only input for a downstream research observer."""

    input_version: Literal[1] = 1
    observation_status: Literal["audit_only"] = "audit_only"
    research_run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    source_handoff_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    audit_count: int = Field(ge=1, le=32, strict=True)
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    prepared_at: datetime
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("prepared_at")
    @classmethod
    def prepared_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("research observation input prepared_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_hash(self) -> ResearchObservationInput:
        if research_observation_input_content_hash(self) != self.input_hash:
            raise ValueError("research observation input hash mismatch")
        return self


def research_observation_input_content_hash(input_data: ResearchObservationInput) -> str:
    payload = input_data.model_dump(mode="json", exclude={"prepared_at", "input_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def build_research_observation_input(
    handoff: ResearchRunAuditHandoff,
    *,
    prepared_at: datetime | None = None,
) -> ResearchObservationInput:
    """Accept only a hash-verified audit handoff as downstream input."""
    try:
        verified_handoff = ResearchRunAuditHandoff.model_validate(handoff.model_dump())
    except ValueError as exc:
        raise DomainViolation("research audit handoff hash mismatch") from exc

    timestamp = prepared_at or datetime.now(UTC)
    provisional = ResearchObservationInput.model_construct(
        input_version=1,
        observation_status="audit_only",
        research_run_id=verified_handoff.research_run_id,
        source_handoff_hash=verified_handoff.handoff_hash,
        audit_count=verified_handoff.audit_count,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        prepared_at=timestamp,
        input_hash="0" * 64,
    )
    return ResearchObservationInput.model_validate(
        {
            "research_run_id": verified_handoff.research_run_id,
            "source_handoff_hash": verified_handoff.handoff_hash,
            "audit_count": verified_handoff.audit_count,
            "prepared_at": timestamp,
            "input_hash": research_observation_input_content_hash(provisional),
        }
    )


__all__ = [
    "ResearchObservationInput",
    "build_research_observation_input",
    "research_observation_input_content_hash",
]
