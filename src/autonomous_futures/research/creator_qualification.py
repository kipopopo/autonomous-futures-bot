"""Evidence-only Creator OOS aggregation to qualification handoff."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from .creator_artifacts import CreatorCandidateArtifact
from .creator_cached_evaluation import CreatorCachedEvaluationResult
from .qualification_artifacts import (
    CreatorCandidateQualificationArtifact,
    WalkForwardQualificationPolicy,
    build_walk_forward_qualification_artifact,
)


class CreatorQualificationFailure(DomainModel):
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    reason_code: str = Field(pattern=r"^[a-z0-9_]+$")


class CreatorQualificationResult(DomainModel):
    qualifications: tuple[CreatorCandidateQualificationArtifact, ...] = ()
    blocked_candidate_ids: tuple[str, ...] = ()
    failures: tuple[CreatorQualificationFailure, ...] = ()
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False

    @model_validator(mode="after")
    def partitions_are_consistent(self) -> CreatorQualificationResult:
        qualification_ids = tuple(item.candidate_id for item in self.qualifications)
        if qualification_ids != tuple(sorted(set(qualification_ids))):
            raise ValueError("qualification candidate IDs must be sorted and unique")
        if self.blocked_candidate_ids != tuple(sorted(set(self.blocked_candidate_ids))):
            raise ValueError("blocked candidate IDs must be sorted and unique")
        if tuple(failure.candidate_id for failure in self.failures) != self.blocked_candidate_ids:
            raise ValueError("qualification failures must match blocked candidate IDs")
        return self


def qualify_creator_cached_evaluations(
    cached_result: CreatorCachedEvaluationResult,
    *,
    candidates: Mapping[str, CreatorCandidateArtifact],
    policy: WalkForwardQualificationPolicy,
    evaluator_run_id: str,
    evaluator_version: str,
    evaluated_at: datetime,
) -> CreatorQualificationResult:
    qualifications: list[CreatorCandidateQualificationArtifact] = []
    blocked: list[str] = []
    failures: list[CreatorQualificationFailure] = []
    for evaluation in cached_result.evaluations:
        candidate = candidates.get(evaluation.candidate_id)
        if candidate is None:
            blocked.append(evaluation.candidate_id)
            failures.append(
                CreatorQualificationFailure(
                    candidate_id=evaluation.candidate_id,
                    reason_code="candidate_unavailable",
                )
            )
            continue
        if evaluation.status != "evaluated" or evaluation.aggregation is None:
            blocked.append(evaluation.candidate_id)
            failures.append(
                CreatorQualificationFailure(
                    candidate_id=evaluation.candidate_id,
                    reason_code="cached_evaluation_blocked",
                )
            )
            continue
        try:
            qualification = build_walk_forward_qualification_artifact(
                candidate=candidate,
                aggregation=evaluation.aggregation,
                policy=policy,
                evaluator_run_id=evaluator_run_id,
                evaluator_version=evaluator_version,
                evaluated_at=evaluated_at,
            )
        except DataQualityError, ValueError:
            blocked.append(evaluation.candidate_id)
            failures.append(
                CreatorQualificationFailure(
                    candidate_id=evaluation.candidate_id,
                    reason_code="qualification_evidence_failed",
                )
            )
            continue
        qualifications.append(qualification)

    ordered_qualifications = tuple(sorted(qualifications, key=lambda item: item.candidate_id))
    ordered_blocked = tuple(sorted(set(blocked)))
    ordered_failures = tuple(sorted(failures, key=lambda failure: failure.candidate_id))
    return CreatorQualificationResult(
        qualifications=ordered_qualifications,
        blocked_candidate_ids=ordered_blocked,
        failures=ordered_failures,
    )


__all__ = [
    "CreatorQualificationFailure",
    "CreatorQualificationResult",
    "qualify_creator_cached_evaluations",
]
