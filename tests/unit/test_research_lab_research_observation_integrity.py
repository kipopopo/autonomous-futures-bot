from __future__ import annotations

from datetime import UTC, datetime

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_evaluation import (
    ResearchObservationEvaluationInput,
    research_observation_evaluation_content_hash,
)
from autonomous_futures.research_lab.research_observation_integrity import (
    ResearchObservationIntegrityReview,
    review_research_observation_integrity,
)


def _evaluation() -> ResearchObservationEvaluationInput:
    provisional = ResearchObservationEvaluationInput.model_construct(
        evaluation_version=1,
        evaluation_status="audit_only",
        review_scope="audit_integrity_only",
        research_run_id="research-run-0001",
        source_observation_hash="a" * 64,
        audit_count=2,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
        evaluation_input_hash="0" * 64,
    )
    return ResearchObservationEvaluationInput.model_validate(
        {
            **provisional.model_dump(),
            "evaluation_input_hash": research_observation_evaluation_content_hash(provisional),
        }
    )


def test_integrity_review_verifies_boundary_only() -> None:
    review = review_research_observation_integrity(_evaluation())

    assert isinstance(review, ResearchObservationIntegrityReview)
    assert review.review_status == "verified"
    assert review.research_run_id == "research-run-0001"
    assert review.source_evaluation_input_hash == _evaluation().evaluation_input_hash
    assert review.check_ids == (
        "audit_only_status",
        "audit_integrity_scope",
        "safety_locks",
    )
    assert review.promotion_state == "unpromoted"
    assert review.paper_activation is False
    assert review.execution_authority is False


def test_integrity_review_rejects_tampered_evaluation_input() -> None:
    tampered = _evaluation().model_copy(update={"audit_count": 3})

    with pytest.raises(DomainViolation, match="evaluation input hash mismatch"):
        review_research_observation_integrity(tampered)


def test_integrity_review_hash_excludes_review_time() -> None:
    evaluation = _evaluation()
    first = review_research_observation_integrity(
        evaluation,
        reviewed_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    second = review_research_observation_integrity(
        evaluation,
        reviewed_at=datetime(2026, 8, 9, 1, tzinfo=UTC),
    )

    assert first.review_hash == second.review_hash
    assert first.reviewed_at != second.reviewed_at
