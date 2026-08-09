from __future__ import annotations

from datetime import UTC, datetime

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_evaluation import (
    ResearchObservationEvaluationInput,
    build_research_observation_evaluation_input,
)
from autonomous_futures.research_lab.research_run_observation import (
    ResearchObservationInput,
    research_observation_input_content_hash,
)


def _observation() -> ResearchObservationInput:
    provisional = ResearchObservationInput.model_construct(
        input_version=1,
        observation_status="audit_only",
        research_run_id="research-run-0001",
        source_handoff_hash="a" * 64,
        audit_count=2,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
        input_hash="0" * 64,
    )
    return ResearchObservationInput.model_validate(
        {
            **provisional.model_dump(),
            "input_hash": research_observation_input_content_hash(provisional),
        }
    )


def test_evaluation_input_is_fixed_to_audit_integrity_scope() -> None:
    evaluation = build_research_observation_evaluation_input(_observation())

    assert isinstance(evaluation, ResearchObservationEvaluationInput)
    assert evaluation.evaluation_status == "audit_only"
    assert evaluation.review_scope == "audit_integrity_only"
    assert evaluation.research_run_id == "research-run-0001"
    assert evaluation.source_observation_hash == _observation().input_hash
    assert evaluation.promotion_state == "unpromoted"
    assert evaluation.paper_activation is False
    assert evaluation.execution_authority is False


def test_evaluation_input_rejects_tampered_observation() -> None:
    tampered = _observation().model_copy(update={"audit_count": 3})

    with pytest.raises(DomainViolation, match="observation input hash mismatch"):
        build_research_observation_evaluation_input(tampered)


def test_evaluation_input_hash_excludes_preparation_time() -> None:
    observation = _observation()
    first = build_research_observation_evaluation_input(
        observation,
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    second = build_research_observation_evaluation_input(
        observation,
        prepared_at=datetime(2026, 8, 9, 1, tzinfo=UTC),
    )

    assert first.evaluation_input_hash == second.evaluation_input_hash
    assert first.prepared_at != second.prepared_at
