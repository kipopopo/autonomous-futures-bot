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
from autonomous_futures.research_lab.research_observation_integrity_handoff import (
    ResearchObservationIntegrityHandoff,
    build_verified_research_observation_integrity_handoff,
)
from autonomous_futures.research_lab.research_observation_integrity_persistence import (
    write_research_observation_integrity_review,
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


def test_verified_integrity_handoff_contains_only_verified_audit_facts(tmp_path: Path) -> None:
    evaluation = _evaluation()
    review = _review(evaluation)
    path = tmp_path / "research-run-0001.json"
    write_research_observation_integrity_review(path, review)
    source_bytes = path.read_bytes()

    handoff = build_verified_research_observation_integrity_handoff(path, evaluation=evaluation)

    assert isinstance(handoff, ResearchObservationIntegrityHandoff)
    assert handoff.handoff_status == "verified_audit_only"
    assert handoff.research_run_id == review.research_run_id
    assert handoff.source_review_hash == review.review_hash
    assert handoff.source_evaluation_input_hash == evaluation.evaluation_input_hash
    assert handoff.check_count == 3
    assert handoff.promotion_state == "unpromoted"
    assert handoff.paper_activation is False
    assert handoff.execution_authority is False
    assert path.read_bytes() == source_bytes


def test_verified_integrity_handoff_rejects_invalid_evaluation(tmp_path: Path) -> None:
    evaluation = _evaluation()
    path = tmp_path / "research-run-0001.json"
    write_research_observation_integrity_review(path, _review(evaluation))
    invalid = evaluation.model_copy(update={"evaluation_input_hash": "0" * 64})

    with pytest.raises(DomainViolation, match="evaluation input hash mismatch"):
        build_verified_research_observation_integrity_handoff(path, evaluation=invalid)


def test_integrity_handoff_hash_excludes_creation_time(tmp_path: Path) -> None:
    evaluation = _evaluation()
    path = tmp_path / "research-run-0001.json"
    write_research_observation_integrity_review(path, _review(evaluation))

    first = build_verified_research_observation_integrity_handoff(
        path,
        evaluation=evaluation,
        created_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    second = build_verified_research_observation_integrity_handoff(
        path,
        evaluation=evaluation,
        created_at=datetime(2026, 8, 9, 1, tzinfo=UTC),
    )

    assert first.handoff_hash == second.handoff_hash
    assert first.created_at != second.created_at
