# ruff: noqa
from datetime import UTC, datetime
from pathlib import Path
import pytest
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReview,
    research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_content_hash,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_persistence import (
    write_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review,
    read_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review,
)


def _r(run="research-run-0001"):
    p = ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReview.model_construct(
        review_version=1,
        review_status="verified",
        review_scope="audit_integrity_only",
        research_run_id=run,
        source_observation_hash="a" * 64,
        source_handoff_hash="b" * 64,
        source_review_hash="c" * 64,
        source_evaluation_input_hash="d" * 64,
        check_ids=("audit_only_status", "audit_integrity_scope", "safety_locks"),
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        reviewed_at=datetime(2026, 8, 9, tzinfo=UTC),
        review_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReview.model_validate(
        {
            **p.model_dump(),
            "review_hash": research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_content_hash(
                p
            ),
        }
    )


def test_round_trip_idempotent(tmp_path: Path):
    p = tmp_path / "review.json"
    r = _r()
    write_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review(
        p, r
    )
    write_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review(
        p, r
    )
    assert (
        read_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review(
            p
        )
        == r
    )


def test_conflict_rejected(tmp_path: Path):
    p = tmp_path / "review.json"
    write_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review(
        p, _r()
    )
    with pytest.raises(DomainViolation, match="immutable"):
        write_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review(
            p, _r("research-run-0002")
        )


def test_tamper_rejected(tmp_path: Path):
    p = tmp_path / "review.json"
    write_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review(
        p, _r()
    )
    p.write_text(p.read_text().replace("verified", "tampered"), encoding="utf-8")
    with pytest.raises(Exception):
        read_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review(
            p
        )
