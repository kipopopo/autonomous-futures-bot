# ruff: noqa
from datetime import UTC, datetime
import pytest
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_result_handoff import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoff,
    research_observation_integrity_evaluation_observation_observation_handoff_content_hash,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_handoff_observation import (
    build_research_observation_integrity_evaluation_observation_observation_handoff_observation_input,
)


def _handoff():
    p = ResearchObservationIntegrityEvaluationObservationObservationHandoff.model_construct(
        handoff_version=1,
        handoff_status="verified_audit_only",
        research_run_id="research-run-0001",
        source_review_hash="a" * 64,
        source_observation_hash="b" * 64,
        source_handoff_hash="c" * 64,
        source_evaluation_input_hash="d" * 64,
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        created_at=datetime(2026, 8, 9, tzinfo=UTC),
        handoff_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationObservationHandoff.model_validate(
        {
            **p.model_dump(),
            "handoff_hash": research_observation_integrity_evaluation_observation_observation_handoff_content_hash(
                p
            ),
        }
    )


def test_observation_preserves_lineage():
    h = _handoff()
    o = build_research_observation_integrity_evaluation_observation_observation_handoff_observation_input(
        h, observed_at=datetime(2026, 8, 9, tzinfo=UTC)
    )
    assert (
        o.observation_status == "audit_only"
        and o.source_handoff_hash == h.handoff_hash
        and not o.execution_authority
    )


def test_observation_rejects_tampered_handoff():
    with pytest.raises(DomainViolation, match="handoff hash mismatch"):
        build_research_observation_integrity_evaluation_observation_observation_handoff_observation_input(
            _handoff().model_copy(update={"handoff_hash": "0" * 64})
        )


def test_observation_hash_excludes_timestamp():
    h = _handoff()
    a = build_research_observation_integrity_evaluation_observation_observation_handoff_observation_input(
        h, observed_at=datetime(2026, 8, 9, tzinfo=UTC)
    )
    b = build_research_observation_integrity_evaluation_observation_observation_handoff_observation_input(
        h, observed_at=datetime(2026, 8, 9, 1, tzinfo=UTC)
    )
    assert a.observation_hash == b.observation_hash
