# ruff: noqa
from datetime import UTC, datetime
import pytest
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_handoff_observation import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationInput,
    research_observation_integrity_evaluation_observation_observation_handoff_observation_content_hash,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_handoff_observation_result import (
    build_research_observation_integrity_evaluation_observation_observation_handoff_observation_review,
)


def _obs():
    p = ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationInput.model_construct(
        observation_version=1,
        observation_status="audit_only",
        research_run_id="research-run-0001",
        source_handoff_hash="a" * 64,
        source_review_hash="b" * 64,
        source_observation_hash="c" * 64,
        source_evaluation_input_hash="d" * 64,
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        observed_at=datetime(2026, 8, 9, tzinfo=UTC),
        observation_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationInput.model_validate(
        {
            **p.model_dump(),
            "observation_hash": research_observation_integrity_evaluation_observation_observation_handoff_observation_content_hash(
                p
            ),
        }
    )


def test_review_preserves_lineage():
    o = _obs()
    r = build_research_observation_integrity_evaluation_observation_observation_handoff_observation_review(
        o, reviewed_at=datetime(2026, 8, 9, tzinfo=UTC)
    )
    assert (
        r.review_status == "verified"
        and r.source_observation_hash == o.observation_hash
        and not r.execution_authority
    )


def test_review_rejects_tampered_observation():
    with pytest.raises(DomainViolation, match="observation hash mismatch"):
        build_research_observation_integrity_evaluation_observation_observation_handoff_observation_review(
            _obs().model_copy(update={"observation_hash": "0" * 64})
        )


def test_review_hash_excludes_timestamp():
    o = _obs()
    a = build_research_observation_integrity_evaluation_observation_observation_handoff_observation_review(
        o, reviewed_at=datetime(2026, 8, 9, tzinfo=UTC)
    )
    b = build_research_observation_integrity_evaluation_observation_observation_handoff_observation_review(
        o, reviewed_at=datetime(2026, 8, 9, 1, tzinfo=UTC)
    )
    assert a.review_hash == b.review_hash
