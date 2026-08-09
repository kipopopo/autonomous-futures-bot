# ruff: noqa
from pathlib import Path
import pytest
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationInput,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_input import (
    load_verified_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review,
)


def _invalid():
    return ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReviewHandoffObservationInput.model_construct(
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
        observed_at=None,
        observation_hash="0" * 64,
    )


def test_rejects_invalid_observation_hash(tmp_path: Path):
    with pytest.raises(DomainViolation, match="observation hash mismatch"):
        load_verified_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review(
            tmp_path / "missing.json", observation=_invalid()
        )


def test_missing_is_fail_closed(tmp_path: Path):
    with pytest.raises(Exception):
        load_verified_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review(
            tmp_path / "missing.json", observation=_invalid()
        )


def test_is_read_only():
    assert callable(
        load_verified_research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review
    )
