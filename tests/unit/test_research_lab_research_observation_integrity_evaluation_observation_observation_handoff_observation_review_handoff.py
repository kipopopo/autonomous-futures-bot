# ruff: noqa
from datetime import UTC, datetime
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoff,
    research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_content_hash,
)


def _handoff():
    p = ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoff.model_construct(
        handoff_version=1,
        handoff_status="verified_audit_only",
        research_run_id="research-run-0001",
        source_review_hash="a" * 64,
        source_observation_hash="b" * 64,
        source_handoff_hash="c" * 64,
        source_review_lineage_hash="d" * 64,
        source_evaluation_input_hash="e" * 64,
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        created_at=datetime(2026, 8, 9, tzinfo=UTC),
        handoff_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoff.model_validate(
        {
            **p.model_dump(),
            "handoff_hash": research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_content_hash(
                p
            ),
        }
    )


def test_handoff_preserves_lineage():
    assert (
        _handoff().source_observation_hash == "b" * 64
        and _handoff().handoff_status == "verified_audit_only"
    )


def test_handoff_has_safety_locks():
    assert (
        _handoff().promotion_state == "unpromoted"
        and not _handoff().paper_activation
        and not _handoff().execution_authority
    )


def test_handoff_hash_excludes_timestamp():
    a = _handoff()
    b = a.model_copy(update={"created_at": datetime(2026, 8, 9, 1, tzinfo=UTC)})
    assert a.handoff_hash == b.handoff_hash
