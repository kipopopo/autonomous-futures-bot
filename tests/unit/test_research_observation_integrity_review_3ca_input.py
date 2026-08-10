# ruff: noqa
from datetime import UTC, datetime
from pathlib import Path
import pytest
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity_review_3ca_input import (
    load_verified_research_observation_integrity_review_3ca,
)
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


def _o():
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
        observed_at=datetime(2026, 8, 10, tzinfo=UTC),
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


def _r():
    o = _o()
    p = ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservationReview.model_construct(
        review_version=1,
        review_status="verified",
        review_scope="audit_integrity_only",
        research_run_id=o.research_run_id,
        source_observation_hash=o.observation_hash,
        source_handoff_hash=o.source_handoff_hash,
        source_review_hash=o.source_review_hash,
        source_evaluation_input_hash=o.source_evaluation_input_hash,
        check_ids=("audit_only_status", "audit_integrity_scope", "safety_locks"),
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        reviewed_at=datetime(2026, 8, 10, tzinfo=UTC),
        review_hash="0" * 64,
    )
    return (
        o,
        ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoffObservationReview.model_validate(
            {
                **p.model_dump(),
                "review_hash": research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_review_content_hash(
                    p
                ),
            }
        ),
    )


def test_verified_binding_round_trip(tmp_path: Path):
    o, r = _r()
    p = tmp_path / "review.json"
    write_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_review(
        p, r
    )
    assert load_verified_research_observation_integrity_review_3ca(p, observation=o) == r


def test_binding_drift_rejected(tmp_path: Path):
    o, r = _r()
    p = tmp_path / "review.json"
    write_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_observation_review(
        p, r
    )
    bad = o.model_copy(update={"source_handoff_hash": "e" * 64})
    with pytest.raises(DomainViolation, match="observation hash mismatch"):
        load_verified_research_observation_integrity_review_3ca(p, observation=bad)


def test_missing_is_fail_closed(tmp_path: Path):
    with pytest.raises(DomainViolation):
        load_verified_research_observation_integrity_review_3ca(
            tmp_path / "missing.json", observation=_o()
        )
