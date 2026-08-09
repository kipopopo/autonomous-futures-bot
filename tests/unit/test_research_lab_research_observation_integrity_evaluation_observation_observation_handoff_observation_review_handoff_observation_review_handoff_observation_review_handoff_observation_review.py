# ruff: noqa
from datetime import UTC, datetime
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_review import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservationReview,
    research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_review_content_hash,
)


def _r(t=datetime(2026, 8, 10, tzinfo=UTC)):
    p = ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservationReview.model_construct(
        review_version=1,
        review_status="verified",
        review_scope="audit_integrity_only",
        research_run_id="research-run-0001",
        source_observation_hash="a" * 64,
        source_handoff_hash="b" * 64,
        source_review_hash="c" * 64,
        source_evaluation_input_hash="d" * 64,
        check_ids=("audit_only_status", "audit_integrity_scope", "safety_locks"),
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        reviewed_at=t,
        review_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservationReview.model_validate(
        {
            **p.model_dump(),
            "review_hash": research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_review_content_hash(
                p
            ),
        }
    )


def test_review_scope_and_checks():
    assert _r().review_scope == "audit_integrity_only" and _r().check_count == 3


def test_timestamp_does_not_change_hash():
    assert _r().review_hash == _r(datetime(2026, 8, 11, tzinfo=UTC)).review_hash


def test_safety_locks():
    assert (
        _r().promotion_state == "unpromoted"
        and not _r().paper_activation
        and not _r().execution_authority
    )
