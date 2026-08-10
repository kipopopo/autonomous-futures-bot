# ruff: noqa
from datetime import UTC, datetime
import pytest
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity_review_3cb_handoff import (
    ResearchObservationIntegrityReview3cbHandoff,
    research_observation_integrity_review_3cb_content_hash,
)
from autonomous_futures.research_lab.research_evidence_aggregation_4b import (
    consume_verified_research_evidence_4b,
    ResearchEvidenceConsumer4b,
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


def test_consumer_binds_expected_runs_and_is_read_only():
    out = consume_verified_research_evidence_4b(
        [_h("run-b", "b"), _h("run-a", "a")],
        expected_research_run_ids=("run-a", "run-b"),
        consumed_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    assert (
        isinstance(out, ResearchEvidenceConsumer4b)
        and out.evidence_count == 2
        and out.research_run_ids == ("run-a", "run-b")
        and out.summary_status == "verified_audit_only"
        and out.promotion_state == "unpromoted"
        and not out.paper_activation
        and not out.execution_authority
    )


def test_tampered_handoff_fails_before_consumption():
    bad = _h("run-a", "a").model_copy(update={"handoff_hash": "f" * 64})
    with pytest.raises(DomainViolation, match="hash"):
        consume_verified_research_evidence_4b(
            [bad],
            expected_research_run_ids=("run-a",),
            consumed_at=datetime(2026, 8, 10, tzinfo=UTC),
        )


def test_expected_run_binding_is_exact():
    with pytest.raises(DomainViolation, match="binding"):
        consume_verified_research_evidence_4b(
            [_h("run-a", "a")],
            expected_research_run_ids=("run-b",),
            consumed_at=datetime(2026, 8, 10, tzinfo=UTC),
        )
