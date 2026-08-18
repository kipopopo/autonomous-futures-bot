"""Immutable human-review checkpoint for paper cohort evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel
from .cohort import PaperCohortReadinessReport


class PaperReviewCheckpoint(DomainModel):
    review_id: str = Field(pattern=r"^review-[A-Za-z0-9._-]+$")
    reviewer_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    reviewed_at: datetime
    decision: Literal["accept_paper_observation", "needs_attention", "reject"]
    review_notes: str = Field(min_length=1, max_length=2000)
    cohort_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    cohort_report: PaperCohortReadinessReport
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False

    @field_validator("reviewed_at")
    @classmethod
    def reviewed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("review timestamp must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def binding_and_decision_are_valid(self) -> PaperReviewCheckpoint:
        if self.cohort_report_hash != hash_paper_cohort_report(self.cohort_report):
            raise ValueError("cohort report hash mismatch")
        if (
            self.decision == "accept_paper_observation"
            and self.cohort_report.cohort_status != "ready_for_human_review"
        ):
            raise ValueError("acceptance requires ready_for_human_review")
        return self


def hash_paper_cohort_report(report: PaperCohortReadinessReport) -> str:
    canonical = json.dumps(
        report.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def create_paper_review_checkpoint(
    report: PaperCohortReadinessReport,
    *,
    review_id: str,
    reviewer_id: str,
    reviewed_at: datetime,
    decision: Literal["accept_paper_observation", "needs_attention", "reject"],
    review_notes: str,
) -> PaperReviewCheckpoint:
    return PaperReviewCheckpoint(
        review_id=review_id,
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
        decision=decision,
        review_notes=review_notes,
        cohort_report_hash=hash_paper_cohort_report(report),
        cohort_report=report,
    )
