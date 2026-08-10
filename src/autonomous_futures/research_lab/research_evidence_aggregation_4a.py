from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain.errors import DomainViolation
from .research_observation_integrity_review_3cb_handoff import (
    ResearchObservationIntegrityReview3cbHandoff,
)


class ResearchEvidenceAggregation4a(BaseModel):
    model_config = ConfigDict(frozen=True)

    aggregation_version: int = 1
    aggregation_status: str = "verified_audit_only"
    evidence_count: int = Field(gt=0)
    research_run_ids: tuple[str, ...]
    source_review_hashes: tuple[str, ...]
    source_observation_hashes: tuple[str, ...]
    source_handoff_hashes: tuple[str, ...]
    source_evaluation_input_hashes: tuple[str, ...]
    total_check_count: int = Field(gt=0)
    data_source: str = "cached_only"
    exchange_access: bool = False
    promotion_state: str = "unpromoted"
    paper_activation: bool = False
    execution_authority: bool = False
    aggregated_at: datetime
    summary_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_safety(self) -> ResearchEvidenceAggregation4a:
        if (
            self.aggregation_status,
            self.data_source,
            self.exchange_access,
            self.promotion_state,
            self.paper_activation,
            self.execution_authority,
        ) != ("verified_audit_only", "cached_only", False, "unpromoted", False, False):
            raise ValueError("invalid aggregation safety state")
        return self

    @staticmethod
    def content_hash(value: ResearchEvidenceAggregation4a) -> str:
        payload = value.model_dump(mode="json", exclude={"aggregated_at", "summary_hash"})
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()


def aggregate_research_evidence_4a(
    handoffs: Sequence[ResearchObservationIntegrityReview3cbHandoff],
    *,
    aggregated_at: datetime,
) -> ResearchEvidenceAggregation4a:
    if not handoffs:
        raise DomainViolation("cannot aggregate empty research evidence")
    ordered = tuple(sorted(handoffs, key=lambda item: item.research_run_id))
    run_ids = tuple(item.research_run_id for item in ordered)
    if len(set(run_ids)) != len(run_ids):
        raise DomainViolation("duplicate research run in evidence aggregation")
    for item in ordered:
        if (
            item.handoff_status,
            item.review_status,
            item.review_scope,
            item.promotion_state,
            item.paper_activation,
            item.execution_authority,
        ) != (
            "verified_audit_only",
            "verified",
            "audit_integrity_only",
            "unpromoted",
            False,
            False,
        ):
            raise DomainViolation("evidence safety state is invalid")
    draft = ResearchEvidenceAggregation4a.model_construct(
        evidence_count=len(ordered),
        research_run_ids=run_ids,
        source_review_hashes=tuple(item.source_review_hash for item in ordered),
        source_observation_hashes=tuple(item.source_observation_hash for item in ordered),
        source_handoff_hashes=tuple(item.source_handoff_hash for item in ordered),
        source_evaluation_input_hashes=tuple(item.source_evaluation_input_hash for item in ordered),
        total_check_count=sum(item.check_count for item in ordered),
        aggregated_at=aggregated_at,
        summary_hash="0" * 64,
    )
    return ResearchEvidenceAggregation4a.model_validate(
        {**draft.model_dump(), "summary_hash": ResearchEvidenceAggregation4a.content_hash(draft)}
    )
