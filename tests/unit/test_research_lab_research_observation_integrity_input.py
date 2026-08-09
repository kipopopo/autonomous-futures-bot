from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_evaluation import (
    ResearchObservationEvaluationInput,
    research_observation_evaluation_content_hash,
)
from autonomous_futures.research_lab.research_observation_integrity import (
    ResearchObservationIntegrityReview,
    research_observation_integrity_content_hash,
)
from autonomous_futures.research_lab.research_observation_integrity_input import (
    load_verified_research_observation_integrity_review,
)
from autonomous_futures.research_lab.research_observation_integrity_persistence import (
    write_research_observation_integrity_review,
)


def _evaluation(source_observation_hash: str = "a" * 64) -> ResearchObservationEvaluationInput:
    provisional = ResearchObservationEvaluationInput.model_construct(
        evaluation_version=1,
        evaluation_status="audit_only",
        review_scope="audit_integrity_only",
        research_run_id="research-run-0001",
        source_observation_hash=source_observation_hash,
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


def _review(evaluation: ResearchObservationEvaluationInput) -> ResearchObservationIntegrityReview:
    provisional = ResearchObservationIntegrityReview.model_construct(
        review_version=1,
        review_status="verified",
        research_run_id=evaluation.research_run_id,
        source_evaluation_input_hash=evaluation.evaluation_input_hash,
        check_ids=("audit_only_status", "audit_integrity_scope", "safety_locks"),
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        reviewed_at=datetime(2026, 8, 9, tzinfo=UTC),
        review_hash="0" * 64,
    )
    return ResearchObservationIntegrityReview.model_validate(
        {
            **provisional.model_dump(),
            "review_hash": research_observation_integrity_content_hash(provisional),
        }
    )


def test_verified_integrity_review_loader_returns_exact_bound_review(tmp_path: Path) -> None:
    evaluation = _evaluation()
    review = _review(evaluation)
    path = tmp_path / "research-run-0001.json"
    write_research_observation_integrity_review(path, review)
    source_bytes = path.read_bytes()

    loaded = load_verified_research_observation_integrity_review(path, evaluation=evaluation)

    assert loaded == review
    assert path.read_bytes() == source_bytes


def test_verified_integrity_review_loader_rejects_invalid_or_mismatched_evaluation(
    tmp_path: Path,
) -> None:
    evaluation = _evaluation()
    path = tmp_path / "research-run-0001.json"
    write_research_observation_integrity_review(path, _review(evaluation))
    invalid = evaluation.model_copy(update={"evaluation_input_hash": "0" * 64})

    with pytest.raises(DomainViolation, match="evaluation input hash mismatch"):
        load_verified_research_observation_integrity_review(path, evaluation=invalid)

    mismatched = _evaluation("b" * 64)
    with pytest.raises(DomainViolation, match="evaluation binding is invalid"):
        load_verified_research_observation_integrity_review(path, evaluation=mismatched)
