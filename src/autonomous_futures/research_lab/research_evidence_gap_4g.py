from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain.errors import DomainViolation
from .research_evidence_lineage_4e import ResearchEvidenceLineageProjection4e


class ResearchEvidenceGapReport4g(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    gap_scope_ids: tuple[str, ...]
    unavailable_scope_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    data_source: str = "cached_only"
    exchange_access: bool = False
    promotion_state: str = "unpromoted"
    paper_activation: bool = False
    execution_authority: bool = False
    reported_at: datetime
    report_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_contract(self) -> ResearchEvidenceGapReport4g:
        if self.status not in {"COMPLETE", "INCOMPLETE"}:
            raise ValueError("invalid gap status")
        if self.status == "COMPLETE" and (
            self.gap_scope_ids or self.unavailable_scope_ids or self.reasons
        ):
            raise ValueError("complete report cannot contain gaps")
        if (
            self.data_source,
            self.exchange_access,
            self.promotion_state,
            self.paper_activation,
            self.execution_authority,
        ) != ("cached_only", False, "unpromoted", False, False):
            raise ValueError("invalid gap safety state")
        return self

    @staticmethod
    def content_hash(value: ResearchEvidenceGapReport4g) -> str:
        payload = value.model_dump(mode="json", exclude={"reported_at", "report_hash"})
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def report_research_evidence_gaps_4g(
    projection: ResearchEvidenceLineageProjection4e,
    *,
    expected_scope_ids: tuple[str, ...],
    reported_at: datetime,
) -> ResearchEvidenceGapReport4g:
    if ResearchEvidenceLineageProjection4e.content_hash(projection) != projection.projection_hash:
        raise DomainViolation("projection hash mismatch")
    expected = tuple(sorted(expected_scope_ids))
    observed = set(projection.scope_ids)
    missing = tuple(scope for scope in expected if scope not in observed)
    unavailable = tuple(
        item.scope_id for item in projection.lineage if item.availability_status == "UNAVAILABLE"
    )
    reasons = ["incomplete_scope"] if missing else []
    reasons.extend(f"{scope}:missing_scope" for scope in missing)
    reasons.extend(
        f"{item.scope_id}:{item.reason}"
        for item in projection.lineage
        if item.availability_status == "UNAVAILABLE" and item.reason
    )
    reasons = list(dict.fromkeys(reasons))
    draft = ResearchEvidenceGapReport4g.model_construct(
        status="COMPLETE" if not reasons else "INCOMPLETE",
        gap_scope_ids=missing,
        unavailable_scope_ids=unavailable,
        reasons=tuple(reasons),
        reported_at=reported_at,
        report_hash="0" * 64,
    )
    return ResearchEvidenceGapReport4g.model_validate(
        {**draft.model_dump(), "report_hash": ResearchEvidenceGapReport4g.content_hash(draft)}
    )
