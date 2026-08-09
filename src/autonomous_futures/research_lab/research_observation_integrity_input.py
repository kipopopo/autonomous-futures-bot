from __future__ import annotations

from pathlib import Path

from ..domain.errors import DomainViolation
from .research_observation_evaluation import ResearchObservationEvaluationInput
from .research_observation_integrity import ResearchObservationIntegrityReview
from .research_observation_integrity_persistence import (
    read_research_observation_integrity_review,
)


def load_verified_research_observation_integrity_review(
    path: Path,
    *,
    evaluation: ResearchObservationEvaluationInput,
) -> ResearchObservationIntegrityReview:
    """Load a persisted review only after exact upstream evaluation binding."""
    try:
        verified_evaluation = ResearchObservationEvaluationInput.model_validate(
            evaluation.model_dump()
        )
    except ValueError as exc:
        raise DomainViolation("research observation evaluation input hash mismatch") from exc

    review = read_research_observation_integrity_review(path)
    if (
        review.research_run_id != verified_evaluation.research_run_id
        or review.source_evaluation_input_hash != verified_evaluation.evaluation_input_hash
    ):
        raise DomainViolation("research observation integrity review evaluation binding is invalid")
    return review


__all__ = ["load_verified_research_observation_integrity_review"]
