from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel
from .model_policy import ResearchModelPolicy
from .research_run_audit_input import load_verified_research_run_audit_envelope


class ResearchRunAuditHandoff(DomainModel):
    """Non-authoritative summary handoff for already verified audit evidence."""

    handoff_version: Literal[1] = 1
    handoff_status: Literal["verified_audit_only"] = "verified_audit_only"
    research_run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    source_envelope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    audit_count: int = Field(ge=1, le=32, strict=True)
    succeeded_count: int = Field(ge=0, strict=True)
    failed_count: int = Field(ge=0, strict=True)
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    created_at: datetime
    handoff_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("created_at")
    @classmethod
    def created_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("research run audit handoff created_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_counts_and_hash(self) -> ResearchRunAuditHandoff:
        if self.succeeded_count + self.failed_count != self.audit_count:
            raise ValueError("research run audit handoff counts are inconsistent")
        if research_run_audit_handoff_content_hash(self) != self.handoff_hash:
            raise ValueError("research run audit handoff hash mismatch")
        return self


def research_run_audit_handoff_content_hash(handoff: ResearchRunAuditHandoff) -> str:
    payload = handoff.model_dump(mode="json", exclude={"created_at", "handoff_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def build_verified_research_run_audit_handoff(
    path: Path,
    *,
    policy: ResearchModelPolicy,
    created_at: datetime | None = None,
) -> ResearchRunAuditHandoff:
    """Build an audit-only handoff from the shared verified persisted loader."""
    envelope = load_verified_research_run_audit_envelope(path, policy=policy)
    succeeded_count = sum(audit.outcome == "succeeded" for audit in envelope.audits)
    failed_count = len(envelope.audits) - succeeded_count
    timestamp = created_at or datetime.now(UTC)
    provisional = ResearchRunAuditHandoff.model_construct(
        handoff_version=1,
        handoff_status="verified_audit_only",
        research_run_id=envelope.research_run_id,
        source_envelope_hash=envelope.envelope_hash,
        audit_count=len(envelope.audits),
        succeeded_count=succeeded_count,
        failed_count=failed_count,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        created_at=timestamp,
        handoff_hash="0" * 64,
    )
    return ResearchRunAuditHandoff.model_validate(
        {
            "research_run_id": envelope.research_run_id,
            "source_envelope_hash": envelope.envelope_hash,
            "audit_count": len(envelope.audits),
            "succeeded_count": succeeded_count,
            "failed_count": failed_count,
            "created_at": timestamp,
            "handoff_hash": research_run_audit_handoff_content_hash(provisional),
        }
    )


__all__ = [
    "ResearchRunAuditHandoff",
    "build_verified_research_run_audit_handoff",
    "research_run_audit_handoff_content_hash",
]
