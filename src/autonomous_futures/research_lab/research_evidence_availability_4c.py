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


class ResearchEvidenceAvailability4c(BaseModel):
    model_config = ConfigDict(frozen=True)

    availability_version: int = 1
    availability_status: str
    reason: str | None
    evidence_count: int = Field(ge=0)
    expected_research_run_ids: tuple[str, ...]
    observed_research_run_ids: tuple[str, ...]
    summary_hash: str | None = Field(default=None, min_length=64, max_length=64)
    data_source: str = "cached_only"
    exchange_access: bool = False
    promotion_state: str = "unpromoted"
    paper_activation: bool = False
    execution_authority: bool = False
    assessed_at: datetime
    availability_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_contract(self) -> ResearchEvidenceAvailability4c:
        if self.availability_status not in {"AVAILABLE", "UNAVAILABLE"}:
            raise ValueError("invalid availability status")
        if self.availability_status == "AVAILABLE" and (
            self.reason is not None or self.summary_hash is None
        ):
            raise ValueError("available evidence requires summary")
        if self.availability_status == "UNAVAILABLE" and self.summary_hash is not None:
            raise ValueError("unavailable evidence cannot have summary")
        if (
            self.data_source,
            self.exchange_access,
            self.promotion_state,
            self.paper_activation,
            self.execution_authority,
        ) != ("cached_only", False, "unpromoted", False, False):
            raise ValueError("invalid availability safety state")
        return self

    @staticmethod
    def content_hash(value: ResearchEvidenceAvailability4c) -> str:
        payload = value.model_dump(mode="json", exclude={"assessed_at", "availability_hash"})
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()


def _build_availability(
    *,
    status: str,
    reason: str | None,
    expected_ids: tuple[str, ...],
    observed_ids: tuple[str, ...],
    evidence_count: int,
    summary_hash: str | None,
    assessed_at: datetime,
) -> ResearchEvidenceAvailability4c:
    draft = ResearchEvidenceAvailability4c.model_construct(
        availability_status=status,
        reason=reason,
        evidence_count=evidence_count,
        expected_research_run_ids=expected_ids,
        observed_research_run_ids=observed_ids,
        summary_hash=summary_hash,
        assessed_at=assessed_at,
        availability_hash="0" * 64,
    )
    return ResearchEvidenceAvailability4c.model_validate(
        {
            **draft.model_dump(),
            "availability_hash": ResearchEvidenceAvailability4c.content_hash(draft),
        }
    )


def assess_research_evidence_availability_4c(
    handoffs: Sequence[ResearchObservationIntegrityReview3cbHandoff],
    *,
    expected_research_run_ids: tuple[str, ...],
    assessed_at: datetime,
) -> ResearchEvidenceAvailability4c:
    expected_ids = tuple(sorted(expected_research_run_ids))
    if len(set(expected_ids)) != len(expected_ids):
        raise DomainViolation("duplicate expected research run binding")
    if not handoffs:
        return _build_availability(
            status="UNAVAILABLE",
            reason="missing_evidence",
            expected_ids=expected_ids,
            observed_ids=(),
            evidence_count=0,
            summary_hash=None,
            assessed_at=assessed_at,
        )
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
    observed_ids = tuple(sorted(item.research_run_id for item in verified))
    if observed_ids != expected_ids:
        return _build_availability(
            status="UNAVAILABLE",
            reason="incomplete_evidence",
            expected_ids=expected_ids,
            observed_ids=observed_ids,
            evidence_count=len(verified),
            summary_hash=None,
            assessed_at=assessed_at,
        )
    summary = aggregate_research_evidence_4a(verified, aggregated_at=assessed_at)
    return _build_availability(
        status="AVAILABLE",
        reason=None,
        expected_ids=expected_ids,
        observed_ids=observed_ids,
        evidence_count=len(verified),
        summary_hash=summary.summary_hash,
        assessed_at=assessed_at,
    )
