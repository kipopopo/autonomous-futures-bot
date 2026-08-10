from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain.errors import DomainViolation
from .research_evidence_availability_4c import ResearchEvidenceAvailability4c


class ResearchEvidenceScope4d(BaseModel):
    model_config = ConfigDict(frozen=True)

    scope_id: str = Field(min_length=1)
    availability: ResearchEvidenceAvailability4c


class ResearchEvidenceStatus4d(BaseModel):
    model_config = ConfigDict(frozen=True)

    status_version: int = 1
    status: str
    reason: str | None
    scope_ids: tuple[str, ...]
    expected_scope_ids: tuple[str, ...]
    available_scope_count: int = Field(ge=0)
    unavailable_scope_count: int = Field(ge=0)
    data_source: str = "cached_only"
    exchange_access: bool = False
    promotion_state: str = "unpromoted"
    paper_activation: bool = False
    execution_authority: bool = False
    reported_at: datetime
    status_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_contract(self) -> ResearchEvidenceStatus4d:
        if self.status not in {"AVAILABLE", "UNAVAILABLE"}:
            raise ValueError("invalid status")
        if self.status == "AVAILABLE" and self.reason is not None:
            raise ValueError("available status cannot have reason")
        if self.status == "UNAVAILABLE" and self.reason is None:
            raise ValueError("unavailable status requires reason")
        if (
            self.data_source,
            self.exchange_access,
            self.promotion_state,
            self.paper_activation,
            self.execution_authority,
        ) != ("cached_only", False, "unpromoted", False, False):
            raise ValueError("invalid status safety state")
        return self

    @staticmethod
    def content_hash(value: ResearchEvidenceStatus4d) -> str:
        payload = value.model_dump(mode="json", exclude={"reported_at", "status_hash"})
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()


def compose_research_evidence_status_4d(
    scopes: Sequence[ResearchEvidenceScope4d],
    *,
    expected_scope_ids: tuple[str, ...],
    reported_at: datetime,
) -> ResearchEvidenceStatus4d:
    expected = tuple(sorted(expected_scope_ids))
    if len(set(expected)) != len(expected):
        raise DomainViolation("duplicate expected scope binding")
    ordered = tuple(sorted(scopes, key=lambda item: item.scope_id))
    observed = tuple(item.scope_id for item in ordered)
    if len(set(observed)) != len(observed):
        raise DomainViolation("duplicate scope binding")
    if set(observed) - set(expected):
        raise DomainViolation("unexpected scope binding")
    for item in ordered:
        if (
            ResearchEvidenceAvailability4c.content_hash(item.availability)
            != item.availability.availability_hash
        ):
            raise DomainViolation("availability hash mismatch")
    available_count = sum(item.availability.availability_status == "AVAILABLE" for item in ordered)
    missing = set(expected) - set(observed)
    if missing:
        status, reason = "UNAVAILABLE", "missing_scope"
    elif any(item.availability.availability_status == "UNAVAILABLE" for item in ordered):
        status, reason = "UNAVAILABLE", "underlying_unavailable"
    else:
        status, reason = "AVAILABLE", None
    draft = ResearchEvidenceStatus4d.model_construct(
        status=status,
        reason=reason,
        scope_ids=observed,
        expected_scope_ids=expected,
        available_scope_count=available_count,
        unavailable_scope_count=len(ordered) - available_count,
        reported_at=reported_at,
        status_hash="0" * 64,
    )
    return ResearchEvidenceStatus4d.model_validate(
        {**draft.model_dump(), "status_hash": ResearchEvidenceStatus4d.content_hash(draft)}
    )
