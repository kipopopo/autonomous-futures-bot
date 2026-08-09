from __future__ import annotations

from datetime import UTC, datetime

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity_evaluation_handoff import (
    ResearchObservationIntegrityEvaluationHandoff,
    research_observation_integrity_evaluation_handoff_content_hash,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation import (
    ResearchObservationIntegrityEvaluationObservationInput,
    build_research_observation_integrity_evaluation_observation_input,
)


def _handoff() -> ResearchObservationIntegrityEvaluationHandoff:
    provisional = ResearchObservationIntegrityEvaluationHandoff.model_construct(
        handoff_version=1,
        handoff_status="verified_audit_only",
        research_run_id="research-run-0001",
        source_review_hash="a" * 64,
        source_evaluation_input_hash="b" * 64,
        source_observation_hash="c" * 64,
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        created_at=datetime(2026, 8, 9, tzinfo=UTC),
        handoff_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationHandoff.model_validate(
        {
            **provisional.model_dump(),
            "handoff_hash": research_observation_integrity_evaluation_handoff_content_hash(
                provisional
            ),
        }
    )


def test_integrity_evaluation_observation_input_preserves_provenance() -> None:
    handoff = _handoff()

    input_data = build_research_observation_integrity_evaluation_observation_input(
        handoff,
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert isinstance(input_data, ResearchObservationIntegrityEvaluationObservationInput)
    assert input_data.observation_status == "audit_only"
    assert input_data.research_run_id == handoff.research_run_id
    assert input_data.source_handoff_hash == handoff.handoff_hash
    assert input_data.source_review_hash == handoff.source_review_hash
    assert input_data.source_evaluation_input_hash == handoff.source_evaluation_input_hash
    assert input_data.source_observation_hash == handoff.source_observation_hash
    assert input_data.check_count == 3
    assert input_data.promotion_state == "unpromoted"
    assert input_data.paper_activation is False
    assert input_data.execution_authority is False


def test_integrity_evaluation_observation_input_rejects_tampered_handoff() -> None:
    handoff = _handoff().model_copy(update={"handoff_hash": "0" * 64})

    with pytest.raises(DomainViolation, match="handoff hash mismatch"):
        build_research_observation_integrity_evaluation_observation_input(handoff)


def test_integrity_evaluation_observation_input_hash_excludes_prepared_at() -> None:
    handoff = _handoff()
    first = build_research_observation_integrity_evaluation_observation_input(
        handoff,
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    second = build_research_observation_integrity_evaluation_observation_input(
        handoff,
        prepared_at=datetime(2026, 8, 9, 1, tzinfo=UTC),
    )

    assert first.input_hash == second.input_hash
    assert first.prepared_at != second.prepared_at
