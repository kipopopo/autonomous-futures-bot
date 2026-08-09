from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity_evaluation import (
    ResearchObservationIntegrityEvaluationInput,
    research_observation_integrity_evaluation_content_hash,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_input import (
    load_verified_research_observation_integrity_evaluation_review,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_persistence import (
    write_research_observation_integrity_evaluation_review,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_result import (
    ResearchObservationIntegrityEvaluationReview,
    research_observation_integrity_evaluation_review_content_hash,
)


def _evaluation(observation_hash: str = "a" * 64) -> ResearchObservationIntegrityEvaluationInput:
    provisional = ResearchObservationIntegrityEvaluationInput.model_construct(
        evaluation_version=1,
        evaluation_status="audit_only",
        review_scope="audit_integrity_only",
        research_run_id="research-run-0001",
        source_observation_hash=observation_hash,
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


def _review(
    evaluation: ResearchObservationIntegrityEvaluationInput,
) -> ResearchObservationIntegrityEvaluationReview:
    provisional = ResearchObservationIntegrityEvaluationReview.model_construct(
        review_version=1,
        review_status="verified",
        research_run_id=evaluation.research_run_id,
        source_evaluation_input_hash=evaluation.evaluation_input_hash,
        source_observation_hash=evaluation.source_observation_hash,
        check_ids=("audit_only_status", "audit_integrity_scope", "safety_locks"),
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        reviewed_at=datetime(2026, 8, 9, tzinfo=UTC),
        review_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationReview.model_validate(
        {
            **provisional.model_dump(),
            "review_hash": research_observation_integrity_evaluation_review_content_hash(
                provisional
            ),
        }
    )


def test_verified_integrity_evaluation_review_loader_returns_bound_review(
    tmp_path: Path,
) -> None:
    evaluation = _evaluation()
    path = tmp_path / "research-run-0001.json"
    review = _review(evaluation)
    write_research_observation_integrity_evaluation_review(path, review)

    loaded = load_verified_research_observation_integrity_evaluation_review(
        path,
        evaluation=evaluation,
    )

    assert loaded == review


def test_verified_integrity_evaluation_review_loader_rejects_invalid_caller(
    tmp_path: Path,
) -> None:
    evaluation = _evaluation()
    path = tmp_path / "research-run-0001.json"
    write_research_observation_integrity_evaluation_review(path, _review(evaluation))
    invalid = evaluation.model_copy(update={"evaluation_input_hash": "0" * 64})

    with pytest.raises(DomainViolation, match="evaluation input hash mismatch"):
        load_verified_research_observation_integrity_evaluation_review(
            path,
            evaluation=invalid,
        )


def test_verified_integrity_evaluation_review_loader_rejects_wrong_upstream_observation(
    tmp_path: Path,
) -> None:
    stored_evaluation = _evaluation()
    path = tmp_path / "research-run-0001.json"
    write_research_observation_integrity_evaluation_review(path, _review(stored_evaluation))
    wrong_evaluation = _evaluation("d" * 64)

    with pytest.raises(DomainViolation, match="review binding is invalid"):
        load_verified_research_observation_integrity_evaluation_review(
            path,
            evaluation=wrong_evaluation,
        )
