from __future__ import annotations

from datetime import UTC, datetime

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity_handoff import (
    ResearchObservationIntegrityHandoff,
    research_observation_integrity_handoff_content_hash,
)
from autonomous_futures.research_lab.research_observation_integrity_observation import (
    ResearchObservationIntegrityObservationInput,
    build_research_observation_integrity_observation_input,
)


def _handoff() -> ResearchObservationIntegrityHandoff:
    provisional = ResearchObservationIntegrityHandoff.model_construct(
        handoff_version=1,
        handoff_status="verified_audit_only",
        research_run_id="research-run-0001",
        source_review_hash="a" * 64,
        source_evaluation_input_hash="b" * 64,
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        created_at=datetime(2026, 8, 9, tzinfo=UTC),
        handoff_hash="0" * 64,
    )
    return ResearchObservationIntegrityHandoff.model_validate(
        {
            **provisional.model_dump(),
            "handoff_hash": research_observation_integrity_handoff_content_hash(provisional),
        }
    )


def test_integrity_observation_input_preserves_verified_integrity_provenance() -> None:
    handoff = _handoff()

    observation = build_research_observation_integrity_observation_input(handoff)

    assert isinstance(observation, ResearchObservationIntegrityObservationInput)
    assert observation.observation_status == "audit_only"
    assert observation.research_run_id == handoff.research_run_id
    assert observation.source_handoff_hash == handoff.handoff_hash
    assert observation.source_review_hash == handoff.source_review_hash
    assert observation.source_evaluation_input_hash == handoff.source_evaluation_input_hash
    assert observation.check_count == 3
    assert observation.promotion_state == "unpromoted"
    assert observation.paper_activation is False
    assert observation.execution_authority is False


def test_integrity_observation_input_rejects_tampered_handoff() -> None:
    tampered = _handoff().model_copy(update={"check_count": 2})

    with pytest.raises(DomainViolation, match="handoff hash mismatch"):
        build_research_observation_integrity_observation_input(tampered)


def test_integrity_observation_input_hash_excludes_preparation_time() -> None:
    handoff = _handoff()
    first = build_research_observation_integrity_observation_input(
        handoff,
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    second = build_research_observation_integrity_observation_input(
        handoff,
        prepared_at=datetime(2026, 8, 9, 1, tzinfo=UTC),
    )

    assert first.input_hash == second.input_hash
    assert first.prepared_at != second.prepared_at
