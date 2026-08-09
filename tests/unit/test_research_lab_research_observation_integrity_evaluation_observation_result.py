from __future__ import annotations

from datetime import UTC, datetime

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab import (
    research_observation_integrity_evaluation_observation_result as result,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation import (
    ResearchObservationIntegrityEvaluationObservationInput,
    research_observation_integrity_evaluation_observation_content_hash,
)


def _input() -> ResearchObservationIntegrityEvaluationObservationInput:
    provisional = ResearchObservationIntegrityEvaluationObservationInput.model_construct(
        input_version=1,
        observation_status="audit_only",
        research_run_id="research-run-0001",
        source_handoff_hash="a" * 64,
        source_review_hash="b" * 64,
        source_evaluation_input_hash="c" * 64,
        source_observation_hash="d" * 64,
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
        input_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationInput.model_validate(
        {
            **provisional.model_dump(),
            "input_hash": research_observation_integrity_evaluation_observation_content_hash(
                provisional
            ),
        }
    )


def test_integrity_evaluation_observation_review_preserves_lineage() -> None:
    input_data = _input()

    review = result.review_research_observation_integrity_evaluation_observation(
        input_data,
        reviewed_at=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert isinstance(review, result.ResearchObservationIntegrityEvaluationObservationReview)
    assert review.review_status == "verified"
    assert review.review_scope == "audit_integrity_only"
    assert review.research_run_id == input_data.research_run_id
    assert review.source_observation_input_hash == input_data.input_hash
    assert review.source_evaluation_input_hash == input_data.source_evaluation_input_hash
    assert review.source_observation_hash == input_data.source_observation_hash
    assert review.check_count == 3
    assert review.promotion_state == "unpromoted"
    assert review.paper_activation is False
    assert review.execution_authority is False


def test_integrity_evaluation_observation_review_rejects_tampered_input() -> None:
    tampered = _input().model_copy(update={"input_hash": "0" * 64})

    with pytest.raises(DomainViolation, match="observation input hash mismatch"):
        result.review_research_observation_integrity_evaluation_observation(tampered)


def test_integrity_evaluation_observation_review_hash_excludes_reviewed_at() -> None:
    input_data = _input()
    first = result.review_research_observation_integrity_evaluation_observation(
        input_data,
        reviewed_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    second = result.review_research_observation_integrity_evaluation_observation(
        input_data,
        reviewed_at=datetime(2026, 8, 9, 1, tzinfo=UTC),
    )

    assert first.review_hash == second.review_hash
    assert first.reviewed_at != second.reviewed_at
    assert (
        result.research_observation_integrity_evaluation_observation_review_content_hash(first)
        == first.review_hash
    )
