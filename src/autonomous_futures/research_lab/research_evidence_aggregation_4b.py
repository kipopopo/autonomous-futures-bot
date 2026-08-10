from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain.errors import DomainViolation
from .research_evidence_aggregation_4a import aggregate_research_evidence_4a
from .research_observation_integrity_review_3cb_handoff import (
    ResearchObservationIntegrityReview3cbHandoff,
    research_observation_integrity_review_3cb_content_hash,
)


class ResearchEvidenceConsumer4b(BaseModel):
    model_config = ConfigDict(frozen=True)

    consumer_version: int = 1
    summary_status: str = "verified_audit_only"
    aggregation_summary_hash: str = Field(min_length=64, max_length=64)
    evidence_count: int = Field(gt=0)
    research_run_ids: tuple[str, ...]
    data_source: str = "cached_only"
    exchange_access: bool = False
    promotion_state: str = "unpromoted"
    paper_activation: bool = False
    execution_authority: bool = False
    consumed_at: datetime
    consumer_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_safety(self) -> ResearchEvidenceConsumer4b:
        if (
            self.summary_status,
            self.data_source,
            self.exchange_access,
            self.promotion_state,
            self.paper_activation,
            self.execution_authority,
        ) != ("verified_audit_only", "cached_only", False, "unpromoted", False, False):
            raise ValueError("invalid consumer safety state")
        return self

    @staticmethod
    def content_hash(value: ResearchEvidenceConsumer4b) -> str:
        payload = value.model_dump(mode="json", exclude={"consumed_at", "consumer_hash"})
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()


def consume_verified_research_evidence_4b(
    handoffs: Sequence[ResearchObservationIntegrityReview3cbHandoff],
    *,
    expected_research_run_ids: tuple[str, ...],
    consumed_at: datetime,
) -> ResearchEvidenceConsumer4b:
    verified: list[ResearchObservationIntegrityReview3cbHandoff] = []
    for handoff in handoffs:
        try:
            candidate = ResearchObservationIntegrityReview3cbHandoff.model_validate(
                handoff.model_dump()
            )
        except ValueError as exc:
            raise DomainViolation("research handoff is malformed") from exc
        if (
            research_observation_integrity_review_3cb_content_hash(candidate)
            != candidate.handoff_hash
        ):
            raise DomainViolation("research handoff hash mismatch")
        verified.append(candidate)
    actual_ids = tuple(sorted(item.research_run_id for item in verified))
    expected_ids = tuple(sorted(expected_research_run_ids))
    if actual_ids != expected_ids:
        raise DomainViolation("research evidence binding is invalid")
    summary = aggregate_research_evidence_4a(verified, aggregated_at=consumed_at)
    draft = ResearchEvidenceConsumer4b.model_construct(
        aggregation_summary_hash=summary.summary_hash,
        evidence_count=summary.evidence_count,
        research_run_ids=summary.research_run_ids,
        consumed_at=consumed_at,
        consumer_hash="0" * 64,
    )
    return ResearchEvidenceConsumer4b.model_validate(
        {**draft.model_dump(), "consumer_hash": ResearchEvidenceConsumer4b.content_hash(draft)}
    )
