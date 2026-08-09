# ruff: noqa
from __future__ import annotations
from datetime import UTC, datetime
from pathlib import Path
import pytest
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation import (
    ResearchObservationIntegrityEvaluationObservationObservationInput,
    build_research_observation_integrity_evaluation_observation_observation_input,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_result_handoff import (
    ResearchObservationIntegrityEvaluationObservationHandoff,
    research_observation_integrity_evaluation_observation_handoff_content_hash,
)


def _handoff() -> ResearchObservationIntegrityEvaluationObservationHandoff:
    p = ResearchObservationIntegrityEvaluationObservationHandoff.model_construct(
        handoff_version=1,
        handoff_status="verified_audit_only",
        research_run_id="research-run-0001",
        source_review_hash="a" * 64,
        source_observation_input_hash="b" * 64,
        source_evaluation_input_hash="c" * 64,
        source_observation_hash="d" * 64,
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        created_at=datetime(2026, 8, 9, tzinfo=UTC),
        handoff_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationHandoff.model_validate(
        {
            **p.model_dump(),
            "handoff_hash": research_observation_integrity_evaluation_observation_handoff_content_hash(
                p
            ),
        }
    )


def test_observation_preserves_lineage() -> None:
    h = _handoff()
    o = build_research_observation_integrity_evaluation_observation_observation_input(
        h, observed_at=datetime(2026, 8, 9, 1, tzinfo=UTC)
    )
    assert o.observation_status == "audit_only"
    assert o.source_handoff_hash == h.handoff_hash
    assert o.source_review_hash == h.source_review_hash
    assert o.check_count == 3
    assert (
        o.promotion_state == "unpromoted" and not o.paper_activation and not o.execution_authority
    )


def test_observation_rejects_tampered_handoff() -> None:
    h = _handoff().model_copy(update={"handoff_hash": "0" * 64})
    with pytest.raises(DomainViolation, match="handoff hash mismatch"):
        build_research_observation_integrity_evaluation_observation_observation_input(h)


def test_observation_hash_excludes_timestamp() -> None:
    h = _handoff()
    a = build_research_observation_integrity_evaluation_observation_observation_input(
        h, observed_at=datetime(2026, 8, 9, tzinfo=UTC)
    )
    b = build_research_observation_integrity_evaluation_observation_observation_input(
        h, observed_at=datetime(2026, 8, 9, 1, tzinfo=UTC)
    )
    assert a.observation_hash == b.observation_hash and a.observed_at != b.observed_at
