from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain.errors import DomainViolation
from .research_evidence_lineage_4e import ResearchEvidenceLineageProjection4e


class ResearchEvidenceLineageConsumer4f(BaseModel):
    model_config = ConfigDict(frozen=True)

    consumer_version: int = 1
    status: str
    reason: str | None
    scope_ids: tuple[str, ...]
    available_scope_count: int = Field(ge=0)
    unavailable_scope_count: int = Field(ge=0)
    source_availability_hashes: tuple[str, ...]
    source_projection_hash: str
    data_source: str = "cached_only"
    exchange_access: bool = False
    promotion_state: str = "unpromoted"
    paper_activation: bool = False
    execution_authority: bool = False
    consumed_at: datetime
    consumer_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_contract(self) -> ResearchEvidenceLineageConsumer4f:
        if self.status not in {"AVAILABLE", "UNAVAILABLE"}:
            raise ValueError("invalid consumer status")
        if self.status == "AVAILABLE" and self.reason is not None:
            raise ValueError("available consumer cannot have reason")
        if self.status == "UNAVAILABLE" and self.reason is None:
            raise ValueError("unavailable consumer requires reason")
        if (
            self.data_source,
            self.exchange_access,
            self.promotion_state,
            self.paper_activation,
            self.execution_authority,
        ) != ("cached_only", False, "unpromoted", False, False):
            raise ValueError("invalid consumer safety state")
        return self

    @staticmethod
    def content_hash(value: ResearchEvidenceLineageConsumer4f) -> str:
        payload = value.model_dump(mode="json", exclude={"consumed_at", "consumer_hash"})
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()


def consume_research_evidence_lineage_4f(
    projection: ResearchEvidenceLineageProjection4e,
    *,
    consumed_at: datetime,
) -> ResearchEvidenceLineageConsumer4f:
    if ResearchEvidenceLineageProjection4e.content_hash(projection) != projection.projection_hash:
        raise DomainViolation("projection hash mismatch")
    available_count = sum(item.availability_status == "AVAILABLE" for item in projection.lineage)
    unavailable_reasons = tuple(
        item.reason for item in projection.lineage if item.availability_status == "UNAVAILABLE"
    )
    propagated_reason = (
        unavailable_reasons[0]
        if unavailable_reasons and len(set(unavailable_reasons)) == 1
        else projection.reason
    )
    draft = ResearchEvidenceLineageConsumer4f.model_construct(
        status=projection.status,
        reason=propagated_reason,
        scope_ids=projection.scope_ids,
        available_scope_count=available_count,
        unavailable_scope_count=len(projection.lineage) - available_count,
        source_availability_hashes=tuple(item.availability_hash for item in projection.lineage),
        source_projection_hash=projection.projection_hash,
        consumed_at=consumed_at,
        consumer_hash="0" * 64,
    )
    return ResearchEvidenceLineageConsumer4f.model_validate(
        {
            **draft.model_dump(),
            "consumer_hash": ResearchEvidenceLineageConsumer4f.content_hash(draft),
        }
    )
