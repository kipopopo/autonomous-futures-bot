# ruff: noqa
from datetime import UTC, datetime
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_result_handoff import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoff,
    research_observation_integrity_evaluation_observation_observation_handoff_content_hash,
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


def test_handoff_preserves_lineage():
    assert _handoff().source_observation_hash == "b" * 64


def test_handoff_is_audit_only():
    assert _handoff().handoff_status == "verified_audit_only" and not _handoff().execution_authority


def test_handoff_hash_excludes_timestamp():
    a = _handoff()
    b = a.model_copy(update={"created_at": datetime(2026, 8, 9, 1, tzinfo=UTC)})
    assert a.handoff_hash == b.handoff_hash
