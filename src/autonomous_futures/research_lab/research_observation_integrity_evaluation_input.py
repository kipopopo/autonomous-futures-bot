from __future__ import annotations

from pathlib import Path

from ..domain.errors import DomainViolation
from .research_observation_integrity_evaluation import (
    ResearchObservationIntegrityEvaluationInput,
)
from .research_observation_integrity_evaluation_persistence import (
    read_research_observation_integrity_evaluation_review,
)
from .research_observation_integrity_evaluation_result import (
    ResearchObservationIntegrityEvaluationReview,
)


def load_verified_research_observation_integrity_evaluation_review(
    path: Path,
    *,
    evaluation: ResearchObservationIntegrityEvaluationInput,
) -> ResearchObservationIntegrityEvaluationReview:
    """Load a persisted review only after exact upstream evaluation binding."""
    try:
        verified_evaluation = ResearchObservationIntegrityEvaluationInput.model_validate(
            evaluation.model_dump()
        )
    except ValueError as exc:
        raise DomainViolation("research integrity evaluation input hash mismatch") from exc

    review = read_research_observation_integrity_evaluation_review(path)
    if (
        review.research_run_id != verified_evaluation.research_run_id
        or review.source_evaluation_input_hash != verified_evaluation.evaluation_input_hash
        or review.source_observation_hash != verified_evaluation.source_observation_hash
    ):
        raise DomainViolation("research integrity evaluation review binding is invalid")
    return review


__all__ = ["load_verified_research_observation_integrity_evaluation_review"]
