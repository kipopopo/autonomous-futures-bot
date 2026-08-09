# ruff: noqa
from pathlib import Path
from ..domain.errors import DomainViolation
from .research_observation_integrity_evaluation_observation_observation_handoff_observation_result import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReview,
)
from .research_observation_integrity_evaluation_observation_observation_handoff_observation_result_persistence import (
    read_research_observation_integrity_evaluation_observation_observation_handoff_observation_review,
)
from .research_observation_integrity_evaluation_observation_observation_handoff_observation import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationInput,
)


def load_verified_research_observation_integrity_evaluation_observation_observation_handoff_observation_review(
    path: Path,
    *,
    observation: ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationInput,
) -> ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReview:
    try:
        verified = ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationInput.model_validate(
            observation.model_dump()
        )
    except ValueError as e:
        raise DomainViolation("observation hash mismatch") from e
    review = read_research_observation_integrity_evaluation_observation_observation_handoff_observation_review(
        path
    )
    if (
        review.research_run_id != verified.research_run_id
        or review.source_observation_hash != verified.observation_hash
        or review.source_handoff_hash != verified.source_handoff_hash
        or review.source_review_hash != verified.source_review_hash
        or review.source_evaluation_input_hash != verified.source_evaluation_input_hash
    ):
        raise DomainViolation("review binding is invalid")
    return review
