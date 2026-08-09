from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .model_audit import ModelCallAudit
from .model_policy import ResearchModelPolicy, research_model_policy_content_hash


class ResearchRunAuditEnvelope(DomainModel):
    """In-memory, non-authoritative collection of one research run's call audits."""

    envelope_version: Literal[1] = 1
    research_run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    audits: tuple[ModelCallAudit, ...] = Field(min_length=1, max_length=32)
    status: Literal["audit_only"] = "audit_only"
    prepared_at: datetime
    envelope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("prepared_at")
    @classmethod
    def prepared_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("research run audit prepared_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_audit_collection(self) -> ResearchRunAuditEnvelope:
        call_ids = tuple(audit.call_id for audit in self.audits)
        if call_ids != tuple(sorted(call_ids)) or len(set(call_ids)) != len(call_ids):
            raise ValueError("research run audit call IDs must be sorted and unique")
        for audit in self.audits:
            if audit.research_run_id != self.research_run_id:
                raise ValueError("research run audit research ID binding is invalid")
            if audit.policy_id != self.policy_id or audit.policy_hash != self.policy_hash:
                raise ValueError("research run audit policy binding is invalid")
        if research_run_audit_content_hash(self) != self.envelope_hash:
            raise ValueError("research run audit envelope hash mismatch")
        return self


def research_run_audit_content_hash(envelope: ResearchRunAuditEnvelope) -> str:
    payload = envelope.model_dump(mode="json", exclude={"prepared_at", "envelope_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def build_research_run_audit_envelope(
    *,
    research_run_id: str,
    policy: ResearchModelPolicy,
    audits: tuple[ModelCallAudit, ...],
    prepared_at: datetime,
) -> ResearchRunAuditEnvelope:
    """Build a deterministic audit-only envelope without filesystem or provider access."""
    if research_model_policy_content_hash(policy) != policy.policy_hash:
        raise DomainViolation("research model policy hash mismatch")
    ordered_audits = tuple(sorted(audits, key=lambda audit: audit.call_id))
    provisional = ResearchRunAuditEnvelope.model_construct(
        envelope_version=1,
        research_run_id=research_run_id,
        policy_id=policy.policy_id,
        policy_hash=policy.policy_hash,
        audits=ordered_audits,
        status="audit_only",
        prepared_at=prepared_at,
        envelope_hash="0" * 64,
    )
    return ResearchRunAuditEnvelope.model_validate(
        {
            "research_run_id": research_run_id,
            "policy_id": policy.policy_id,
            "policy_hash": policy.policy_hash,
            "audits": ordered_audits,
            "status": "audit_only",
            "prepared_at": prepared_at,
            "envelope_hash": research_run_audit_content_hash(provisional),
        }
    )


__all__ = [
    "ResearchRunAuditEnvelope",
    "build_research_run_audit_envelope",
    "research_run_audit_content_hash",
]
