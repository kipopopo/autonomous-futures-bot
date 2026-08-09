from __future__ import annotations

from datetime import UTC, datetime

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity_evaluation import (
    ResearchObservationIntegrityEvaluationInput,
    research_observation_integrity_evaluation_content_hash,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_result import (
    ResearchObservationIntegrityEvaluationReview,
    review_research_observation_integrity_evaluation,
)


def _evaluation() -> ResearchObservationIntegrityEvaluationInput:
    provisional = ResearchObservationIntegrityEvaluationInput.model_construct(
        evaluation_version=1,
        evaluation_status="audit_only",
        review_scope="audit_integrity_only",
        research_run_id="research-run-0001",
        source_observation_hash="a" * 64,
        source_review_hash="b" * 64,
        source_evaluation_input_hash="c" * 64,
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
        evaluation_input_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationInput.model_validate(
        {
            **provisional.model_dump(),
            "evaluation_input_hash": research_observation_integrity_evaluation_content_hash(
                provisional
            ),
        }
    )


def test_integrity_evaluation_review_verifies_boundary_only() -> None:
    evaluation = _evaluation()

    review = review_research_observation_integrity_evaluation(evaluation)

    assert isinstance(review, ResearchObservationIntegrityEvaluationReview)
    assert review.review_status == "verified"
    assert review.research_run_id == evaluation.research_run_id
    assert review.source_evaluation_input_hash == evaluation.evaluation_input_hash
    assert review.source_observation_hash == evaluation.source_observation_hash
    assert review.check_ids == (
        "audit_only_status",
        "audit_integrity_scope",
        "safety_locks",
    )
    assert review.promotion_state == "unpromoted"
    assert review.paper_activation is False
    assert review.execution_authority is False


def test_integrity_evaluation_review_rejects_tampered_input() -> None:
    tampered = _evaluation().model_copy(update={"check_count": 2})

    with pytest.raises(DomainViolation, match="evaluation input hash mismatch"):
        review_research_observation_integrity_evaluation(tampered)


def test_integrity_evaluation_review_hash_excludes_review_time() -> None:
    evaluation = _evaluation()
    first = review_research_observation_integrity_evaluation(
        evaluation,
        reviewed_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    second = review_research_observation_integrity_evaluation(
        evaluation,
        reviewed_at=datetime(2026, 8, 9, 1, tzinfo=UTC),
    )

    assert first.review_hash == second.review_hash
    assert first.reviewed_at != second.reviewed_at
