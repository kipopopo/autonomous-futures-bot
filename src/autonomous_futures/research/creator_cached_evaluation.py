"""Cached-only evaluation handoff for accepted Creator candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import Field, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from .cached_evaluation import CachedEvaluationWindow
from .cached_oos_walk_forward import CachedSimulator, evaluate_cached_oos_walk_forward
from .creator_batch import CreatorBatchResult
from .walk_forward import WalkForwardAggregation


class CreatorCandidateCachedEvaluation(DomainModel):
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    status: Literal["evaluated", "blocked"]
    aggregation: WalkForwardAggregation | None = None
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def status_matches_aggregation(self) -> CreatorCandidateCachedEvaluation:
        if (self.status == "evaluated") != (self.aggregation is not None):
            raise ValueError(
                "evaluated candidates require aggregation and blocked candidates forbid it"
            )
        return self


class CreatorCachedEvaluationResult(DomainModel):
    evaluations: tuple[CreatorCandidateCachedEvaluation, ...] = Field(min_length=1)
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False


def evaluate_creator_batch_cached(
    batch: CreatorBatchResult,
    *,
    windows_by_candidate: Mapping[str, Sequence[CachedEvaluationWindow]],
    simulator: CachedSimulator,
) -> CreatorCachedEvaluationResult:
    evaluations: list[CreatorCandidateCachedEvaluation] = []
    for candidate in batch.accepted_candidates:
        windows = windows_by_candidate.get(candidate.candidate_id, ())
        if not windows:
            evaluations.append(
                CreatorCandidateCachedEvaluation(
                    candidate_id=candidate.candidate_id,
                    status="blocked",
                    reason_codes=("missing_cached_windows",),
                )
            )
            continue
        try:
            aggregation = evaluate_cached_oos_walk_forward(
                candidate,
                windows,
                simulator=simulator,
            )
        except DataQualityError, ValueError:
            evaluations.append(
                CreatorCandidateCachedEvaluation(
                    candidate_id=candidate.candidate_id,
                    status="blocked",
                    reason_codes=("cached_evaluation_failed",),
                )
            )
            continue
        evaluations.append(
            CreatorCandidateCachedEvaluation(
                candidate_id=candidate.candidate_id,
                status="evaluated",
                aggregation=aggregation,
                reason_codes=("cached_oos_aggregation_built",),
            )
        )
    if not evaluations:
        raise ValueError("Creator cached evaluation requires accepted candidates")
    return CreatorCachedEvaluationResult(evaluations=tuple(evaluations))


__all__ = [
    "CreatorCandidateCachedEvaluation",
    "CreatorCachedEvaluationResult",
    "evaluate_creator_batch_cached",
]
