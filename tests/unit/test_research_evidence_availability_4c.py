# ruff: noqa
from datetime import UTC, datetime
import pytest
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity_review_3cb_handoff import (
    ResearchObservationIntegrityReview3cbHandoff,
    research_observation_integrity_review_3cb_content_hash,
)
from autonomous_futures.research_lab.research_evidence_availability_4c import (
    assess_research_evidence_availability_4c,
)


def _h(run: str, suffix: str):
    draft = ResearchObservationIntegrityReview3cbHandoff.model_construct(
        research_run_id=run,
        source_review_hash=(suffix * 64)[:64],
        source_observation_hash=(chr(ord(suffix) + 1) * 64)[:64],
        source_handoff_hash=(chr(ord(suffix) + 2) * 64)[:64],
        source_evaluation_input_hash=(chr(ord(suffix) + 3) * 64)[:64],
        check_count=3,
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
        handoff_hash="0" * 64,
    )
    return ResearchObservationIntegrityReview3cbHandoff.model_validate(
        {
            **draft.model_dump(),
            "handoff_hash": research_observation_integrity_review_3cb_content_hash(draft),
        }
    )


def test_missing_evidence_is_explicitly_unavailable():
    result = assess_research_evidence_availability_4c(
        [], expected_research_run_ids=("run-a",), assessed_at=datetime(2026, 8, 10, tzinfo=UTC)
    )
    assert (
        result.availability_status == "UNAVAILABLE"
        and result.reason == "missing_evidence"
        and result.summary_hash is None
        and not result.execution_authority
    )


def test_partial_coverage_is_unavailable_without_fabrication():
    result = assess_research_evidence_availability_4c(
        [_h("run-a", "a")],
        expected_research_run_ids=("run-a", "run-b"),
        assessed_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    assert (
        result.availability_status == "UNAVAILABLE"
        and result.reason == "incomplete_evidence"
        and result.evidence_count == 1
        and result.summary_hash is None
    )


def test_complete_verified_evidence_is_available():
    result = assess_research_evidence_availability_4c(
        [_h("run-a", "a")],
        expected_research_run_ids=("run-a",),
        assessed_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    assert (
        result.availability_status == "AVAILABLE"
        and result.reason is None
        and result.summary_hash is not None
    )


def test_tampered_present_evidence_fails_closed():
    with pytest.raises(DomainViolation, match="hash"):
        assess_research_evidence_availability_4c(
            [_h("run-a", "a").model_copy(update={"handoff_hash": "f" * 64})],
            expected_research_run_ids=("run-a",),
            assessed_at=datetime(2026, 8, 10, tzinfo=UTC),
        )
