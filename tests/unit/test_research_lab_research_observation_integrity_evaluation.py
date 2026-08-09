from __future__ import annotations

from datetime import UTC, datetime

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity_evaluation import (
    ResearchObservationIntegrityEvaluationInput,
    build_research_observation_integrity_evaluation_input,
)
from autonomous_futures.research_lab.research_observation_integrity_observation import (
    ResearchObservationIntegrityObservationInput,
    research_observation_integrity_observation_content_hash,
)


def _observation() -> ResearchObservationIntegrityObservationInput:
    provisional = ResearchObservationIntegrityObservationInput.model_construct(
        input_version=1,
        observation_status="audit_only",
        research_run_id="research-run-0001",
        source_handoff_hash="a" * 64,
        source_review_hash="b" * 64,
        source_evaluation_input_hash="c" * 64,
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
        input_hash="0" * 64,
    )
    return ResearchObservationIntegrityObservationInput.model_validate(
        {
            **provisional.model_dump(),
            "input_hash": research_observation_integrity_observation_content_hash(provisional),
        }
    )


def test_integrity_evaluation_input_preserves_audit_only_provenance() -> None:
    observation = _observation()

    evaluation = build_research_observation_integrity_evaluation_input(observation)

    assert isinstance(evaluation, ResearchObservationIntegrityEvaluationInput)
    assert evaluation.evaluation_status == "audit_only"
    assert evaluation.review_scope == "audit_integrity_only"
    assert evaluation.research_run_id == observation.research_run_id
    assert evaluation.source_observation_hash == observation.input_hash
    assert evaluation.source_review_hash == observation.source_review_hash
    assert evaluation.source_evaluation_input_hash == observation.source_evaluation_input_hash
    assert evaluation.check_count == 3
    assert evaluation.promotion_state == "unpromoted"
    assert evaluation.paper_activation is False
    assert evaluation.execution_authority is False


def test_integrity_evaluation_input_rejects_tampered_observation() -> None:
    tampered = _observation().model_copy(update={"check_count": 2})

    with pytest.raises(DomainViolation, match="observation input hash mismatch"):
        build_research_observation_integrity_evaluation_input(tampered)


def test_integrity_evaluation_input_hash_excludes_preparation_time() -> None:
    observation = _observation()
    first = build_research_observation_integrity_evaluation_input(
        observation,
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    second = build_research_observation_integrity_evaluation_input(
        observation,
        prepared_at=datetime(2026, 8, 9, 1, tzinfo=UTC),
    )

    assert first.evaluation_input_hash == second.evaluation_input_hash
    assert first.prepared_at != second.prepared_at
