from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain.errors import DomainViolation
from .research_evidence_availability_4c import ResearchEvidenceAvailability4c
from .research_evidence_status_4d import ResearchEvidenceScope4d, ResearchEvidenceStatus4d


class ResearchEvidenceSourceLineage4e(BaseModel):
    model_config = ConfigDict(frozen=True)

    scope_id: str = Field(min_length=1)
    availability_status: str
    reason: str | None
    expected_research_run_ids: tuple[str, ...]
    observed_research_run_ids: tuple[str, ...]
    summary_hash: str | None
    availability_hash: str


class ResearchEvidenceLineageProjection4e(BaseModel):
    model_config = ConfigDict(frozen=True)

    projection_version: int = 1
    status: str
    reason: str | None
    scope_ids: tuple[str, ...]
    lineage: tuple[ResearchEvidenceSourceLineage4e, ...]
    data_source: str = "cached_only"
    exchange_access: bool = False
    promotion_state: str = "unpromoted"
    paper_activation: bool = False
    execution_authority: bool = False
    projected_at: datetime
    projection_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_contract(self) -> ResearchEvidenceLineageProjection4e:
        if self.status not in {"AVAILABLE", "UNAVAILABLE"}:
            raise ValueError("invalid projection status")
        if self.status == "AVAILABLE" and self.reason is not None:
            raise ValueError("available projection cannot have reason")
        if self.status == "UNAVAILABLE" and self.reason is None:
            raise ValueError("unavailable projection requires reason")
        if (
            self.data_source,
            self.exchange_access,
            self.promotion_state,
            self.paper_activation,
            self.execution_authority,
        ) != ("cached_only", False, "unpromoted", False, False):
            raise ValueError("invalid projection safety state")
        return self

    @staticmethod
    def content_hash(value: ResearchEvidenceLineageProjection4e) -> str:
        payload = value.model_dump(mode="json", exclude={"projected_at", "projection_hash"})
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()


def project_research_evidence_lineage_4e(
    status: ResearchEvidenceStatus4d,
    scopes: Sequence[ResearchEvidenceScope4d],
    *,
    projected_at: datetime,
) -> ResearchEvidenceLineageProjection4e:
    if ResearchEvidenceStatus4d.content_hash(status) != status.status_hash:
        raise DomainViolation("status hash mismatch")
    ordered = tuple(sorted(scopes, key=lambda item: item.scope_id))
    scope_ids = tuple(item.scope_id for item in ordered)
    if scope_ids != status.scope_ids or set(scope_ids) != set(status.expected_scope_ids):
        raise DomainViolation("source scope binding mismatch")
    lineage: list[ResearchEvidenceSourceLineage4e] = []
    for item in ordered:
        availability = item.availability
        if (
            ResearchEvidenceAvailability4c.content_hash(availability)
            != availability.availability_hash
        ):
            raise DomainViolation("availability hash mismatch")
        lineage.append(
            ResearchEvidenceSourceLineage4e(
                scope_id=item.scope_id,
                availability_status=availability.availability_status,
                reason=availability.reason,
                expected_research_run_ids=availability.expected_research_run_ids,
                observed_research_run_ids=availability.observed_research_run_ids,
                summary_hash=availability.summary_hash,
                availability_hash=availability.availability_hash,
            )
        )
    draft = ResearchEvidenceLineageProjection4e.model_construct(
        status=status.status,
        reason=status.reason,
        scope_ids=scope_ids,
        lineage=tuple(lineage),
        projected_at=projected_at,
        projection_hash="0" * 64,
    )
    return ResearchEvidenceLineageProjection4e.model_validate(
        {
            **draft.model_dump(),
            "projection_hash": ResearchEvidenceLineageProjection4e.content_hash(draft),
        }
    )
