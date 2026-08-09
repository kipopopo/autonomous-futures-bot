# ruff: noqa
from __future__ import annotations

from pathlib import Path

from ..domain.errors import DomainViolation
from .research_observation_integrity_evaluation_observation import (
    ResearchObservationIntegrityEvaluationObservationInput,
)
from .research_observation_integrity_evaluation_observation_result import (
    ResearchObservationIntegrityEvaluationObservationReview,
)
from .research_observation_integrity_evaluation_observation_result_persistence import (
    read_research_observation_integrity_evaluation_observation_review,
)


def load_verified_research_observation_integrity_evaluation_observation_review(
    path: Path, *, observation_input: ResearchObservationIntegrityEvaluationObservationInput
) -> ResearchObservationIntegrityEvaluationObservationReview:
    """Load a persisted Phase 3AZ review only after exact Phase 3AY binding."""
    try:
        verified_input = ResearchObservationIntegrityEvaluationObservationInput.model_validate(
            observation_input.model_dump()
        )
    except ValueError as exc:
        raise DomainViolation(
            "research integrity evaluation observation input hash mismatch"
        ) from exc
    review = read_research_observation_integrity_evaluation_observation_review(path)
    if (
        review.research_run_id != verified_input.research_run_id
        or review.source_observation_input_hash != verified_input.input_hash
        or review.source_evaluation_input_hash != verified_input.source_evaluation_input_hash
        or review.source_observation_hash != verified_input.source_observation_hash
    ):
        raise DomainViolation("research integrity evaluation observation review binding is invalid")
    return review


__all__ = ["load_verified_research_observation_integrity_evaluation_observation_review"]
