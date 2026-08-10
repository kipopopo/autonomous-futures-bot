# ruff: noqa
from datetime import UTC, datetime
from pathlib import Path

from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservation,
    research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_content_hash,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_review import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservationReview,
    research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_review_content_hash,
)
from autonomous_futures.research_lab.research_observation_integrity_review_3bz_persistence import (
    write_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_review,
)
from autonomous_futures.research_lab.research_observation_integrity_review_3ca_input import (
    load_verified_research_observation_integrity_review_3ca,
)
from autonomous_futures.research_lab.research_observation_integrity_review_3cb_handoff import (
    handoff_verified_research_observation_integrity_review_3cb,
)


def _observation() -> (
    ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservation
):
    draft = ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservation.model_construct(
        observation_version=1,
        observation_status="audit_only",
        research_run_id="research-run-closure-0001",
        source_handoff_hash="a" * 64,
        source_review_hash="b" * 64,
        source_observation_hash="c" * 64,
        source_evaluation_input_hash="d" * 64,
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        observed_at=datetime(2026, 8, 10, tzinfo=UTC),
        observation_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservation.model_validate(
        {
            **draft.model_dump(),
            "observation_hash": research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_content_hash(
                draft
            ),
        }
    )


def _review(
    observation: ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservation,
) -> ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservationReview:
    draft = ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservationReview.model_construct(
        review_version=1,
        review_status="verified",
        review_scope="audit_integrity_only",
        research_run_id=observation.research_run_id,
        source_observation_hash=observation.observation_hash,
        source_handoff_hash=observation.source_handoff_hash,
        source_review_hash=observation.source_review_hash,
        source_evaluation_input_hash=observation.source_evaluation_input_hash,
        check_ids=("audit_only_status", "audit_integrity_scope", "safety_locks"),
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        reviewed_at=datetime(2026, 8, 10, tzinfo=UTC),
        review_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservationReview.model_validate(
        {
            **draft.model_dump(),
            "review_hash": research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_review_content_hash(
                draft
            ),
        }
    )


def test_phase_3_persisted_review_to_handoff_preserves_verified_audit_only_lineage(
    tmp_path: Path,
) -> None:
    observation = _observation()
    review = _review(observation)
    review_path = tmp_path / "review.json"

    write_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_review(
        review_path, review
    )
    loaded = load_verified_research_observation_integrity_review_3ca(
        review_path, observation=observation
    )
    handoff = handoff_verified_research_observation_integrity_review_3cb(
        review_path=review_path, observation=observation
    )

    assert loaded == review
    assert handoff.research_run_id == observation.research_run_id
    assert handoff.source_review_hash == review.review_hash
    assert handoff.source_observation_hash == observation.observation_hash
    assert handoff.check_count == 3
    assert handoff.handoff_status == "verified_audit_only"
    assert handoff.promotion_state == "unpromoted"
    assert handoff.paper_activation is False
    assert handoff.execution_authority is False
