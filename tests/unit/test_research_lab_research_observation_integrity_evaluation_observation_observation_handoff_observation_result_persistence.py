# ruff: noqa
from datetime import UTC, datetime
from pathlib import Path
import pytest
from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_handoff_observation_result import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReview,
    research_observation_integrity_evaluation_observation_observation_handoff_observation_review_content_hash,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_handoff_observation_result_persistence import (
    write_research_observation_integrity_evaluation_observation_observation_handoff_observation_review,
    read_research_observation_integrity_evaluation_observation_observation_handoff_observation_review,
)


def _review(run="research-run-0001"):
    p = ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReview.model_construct(
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
    return ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReview.model_validate(
        {
            **p.model_dump(),
            "review_hash": research_observation_integrity_evaluation_observation_observation_handoff_observation_review_content_hash(
                p
            ),
        }
    )


def test_round_trip(tmp_path: Path):
    p = tmp_path / "review.json"
    r = _review()
    write_research_observation_integrity_evaluation_observation_observation_handoff_observation_review(
        p, r
    )
    assert (
        read_research_observation_integrity_evaluation_observation_observation_handoff_observation_review(
            p
        )
        == r
    )
    write_research_observation_integrity_evaluation_observation_observation_handoff_observation_review(
        p, r
    )


def test_conflict_rejected(tmp_path: Path):
    p = tmp_path / "review.json"
    write_research_observation_integrity_evaluation_observation_observation_handoff_observation_review(
        p, _review()
    )
    with pytest.raises(DomainViolation, match="immutable"):
        write_research_observation_integrity_evaluation_observation_observation_handoff_observation_review(
            p, _review("research-run-0002")
        )


def test_tamper_rejected(tmp_path: Path):
    p = tmp_path / "review.json"
    write_research_observation_integrity_evaluation_observation_observation_handoff_observation_review(
        p, _review()
    )
    p.write_text(p.read_text().replace("verified", "tampered"), encoding="utf-8")
    with pytest.raises((DomainViolation, DataQualityError)):
        read_research_observation_integrity_evaluation_observation_observation_handoff_observation_review(
            p
        )
