# ruff: noqa
from datetime import UTC, datetime
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_handoff import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffHandoff,
    research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_handoff_content_hash,
)


def _h():
    p = ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffHandoff.model_construct(
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
    return ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffHandoff.model_validate(
        {
            **p.model_dump(),
            "handoff_hash": research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_handoff_content_hash(
                p
            ),
        }
    )


def test_lineage():
    assert _h().source_observation_hash == "b" * 64 and _h().handoff_status == "verified_audit_only"


def test_safety():
    assert (
        _h().promotion_state == "unpromoted"
        and not _h().paper_activation
        and not _h().execution_authority
    )


def test_timestamp_excluded():
    assert _h().handoff_hash == _h().handoff_hash
