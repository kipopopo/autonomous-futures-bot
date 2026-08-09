# ruff: noqa
from datetime import UTC, datetime
from pathlib import Path
import pytest
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoff,
    research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_content_hash,
    build_verified_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff,
)


def _handoff():
    p = ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoff.model_construct(
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
    return ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationReviewHandoffObservationReviewHandoff.model_validate(
        {
            **p.model_dump(),
            "handoff_hash": research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff_content_hash(
                p
            ),
        }
    )


def test_audit_only_handoff_preserves_all_lineage():
    h = _handoff()
    assert (
        h.research_run_id,
        h.source_review_hash,
        h.source_observation_hash,
        h.source_handoff_hash,
        h.source_review_lineage_hash,
        h.source_evaluation_input_hash,
    ) == ("research-run-0001", "a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64)


def test_handoff_is_locked_and_hash_excludes_timestamp():
    h = _handoff()
    changed = h.model_copy(update={"created_at": datetime(2026, 8, 10, tzinfo=UTC)})
    assert h.handoff_status == "verified_audit_only" and h.promotion_state == "unpromoted"
    assert h.paper_activation is False and h.execution_authority is False
    assert h.handoff_hash == changed.handoff_hash


def test_missing_verified_review_fails_closed(tmp_path: Path):
    with pytest.raises(Exception):
        build_verified_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_observation_review_handoff(
            tmp_path / "missing.json", observation=None
        )
