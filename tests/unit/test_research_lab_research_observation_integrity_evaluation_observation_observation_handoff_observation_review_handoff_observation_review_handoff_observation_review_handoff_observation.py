# ruff: noqa
from datetime import UTC, datetime
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservation,
    research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_content_hash,
)


def _o(t=datetime(2026, 8, 9, tzinfo=UTC)):
    p = ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservation.model_construct(
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
        observed_at=t,
        observation_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservation.model_validate(
        {
            **p.model_dump(),
            "observation_hash": research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_content_hash(
                p
            ),
        }
    )


def test_lineage_and_status():
    assert _o().source_handoff_hash == "a" * 64 and _o().observation_status == "audit_only"


def test_timestamp_does_not_change_hash():
    assert _o().observation_hash == _o(datetime(2026, 8, 10, tzinfo=UTC)).observation_hash


def test_safety_locks():
    assert (
        _o().promotion_state == "unpromoted"
        and not _o().paper_activation
        and not _o().execution_authority
    )
