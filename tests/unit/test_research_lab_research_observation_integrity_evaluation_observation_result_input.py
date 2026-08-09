# ruff: noqa
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab import (
    research_observation_integrity_evaluation_observation_result as result,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_result_persistence import (
    write_research_observation_integrity_evaluation_observation_review,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_result_input import (
    load_verified_research_observation_integrity_evaluation_observation_review,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation import (
    ResearchObservationIntegrityEvaluationObservationInput,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation import (
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
    from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation import (
        research_observation_integrity_evaluation_observation_content_hash,
    )

    return ResearchObservationIntegrityEvaluationObservationInput.model_validate(
        {
            **provisional.model_dump(),
            "input_hash": research_observation_integrity_evaluation_observation_content_hash(
                provisional
            ),
        }
    )


def _review(
    input_data: ResearchObservationIntegrityEvaluationObservationInput,
) -> result.ResearchObservationIntegrityEvaluationObservationReview:
    provisional = result.ResearchObservationIntegrityEvaluationObservationReview.model_construct(
        review_version=1,
        review_status="verified",
        review_scope="audit_integrity_only",
        research_run_id=input_data.research_run_id,
        source_observation_input_hash=input_data.input_hash,
        source_evaluation_input_hash=input_data.source_evaluation_input_hash,
        source_observation_hash=input_data.source_observation_hash,
        check_ids=("audit_only_status", "audit_integrity_scope", "safety_locks"),
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        reviewed_at=datetime(2026, 8, 9, tzinfo=UTC),
        review_hash="0" * 64,
    )
    return result.ResearchObservationIntegrityEvaluationObservationReview.model_validate(
        {
            **provisional.model_dump(),
            "review_hash": result.research_observation_integrity_evaluation_observation_review_content_hash(
                provisional
            ),
        }
    )


def test_loader_returns_exactly_bound_review(tmp_path: Path) -> None:
    input_data = _input()
    path = tmp_path / "review.json"
    review = _review(input_data)
    write_research_observation_integrity_evaluation_observation_review(path, review)
    assert (
        load_verified_research_observation_integrity_evaluation_observation_review(
            path, observation_input=input_data
        )
        == review
    )


def test_loader_rejects_tampered_caller(tmp_path: Path) -> None:
    input_data = _input()
    path = tmp_path / "review.json"
    write_research_observation_integrity_evaluation_observation_review(path, _review(input_data))
    with pytest.raises(DomainViolation, match="observation input hash mismatch"):
        load_verified_research_observation_integrity_evaluation_observation_review(
            path, observation_input=input_data.model_copy(update={"input_hash": "0" * 64})
        )


def test_loader_rejects_wrong_lineage(tmp_path: Path) -> None:
    input_data = _input()
    path = tmp_path / "review.json"
    write_research_observation_integrity_evaluation_observation_review(path, _review(input_data))
    wrong = _input().model_copy(update={"source_observation_hash": "e" * 64})
    wrong = wrong.model_copy(
        update={
            "input_hash": research_observation_integrity_evaluation_observation_content_hash(wrong)
        }
    )
    with pytest.raises(DomainViolation, match="review binding is invalid"):
        load_verified_research_observation_integrity_evaluation_observation_review(
            path, observation_input=wrong
        )
