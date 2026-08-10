# ruff: noqa
from datetime import UTC, datetime
import pytest
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity_review_3cb_handoff import (
    ResearchObservationIntegrityReview3cbHandoff,
)
from autonomous_futures.research_lab.research_evidence_aggregation_4a import (
    aggregate_research_evidence_4a,
    ResearchEvidenceAggregation4a,
)


def _h(run: str, suffix: str) -> ResearchObservationIntegrityReview3cbHandoff:
    return ResearchObservationIntegrityReview3cbHandoff.model_construct(
        research_run_id=run,
        source_review_hash=(suffix * 64)[:64],
        source_observation_hash=(chr(ord(suffix) + 1) * 64)[:64],
        source_handoff_hash=(chr(ord(suffix) + 2) * 64)[:64],
        source_evaluation_input_hash=(chr(ord(suffix) + 3) * 64)[:64],
        check_count=3,
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
        handoff_hash=(chr(ord(suffix) + 4) * 64)[:64],
    )


def test_aggregation_is_order_independent_and_hash_deterministic():
    a = aggregate_research_evidence_4a(
        [_h("run-b", "b"), _h("run-a", "a")], aggregated_at=datetime(2026, 8, 10, tzinfo=UTC)
    )
    b = aggregate_research_evidence_4a(
        [_h("run-a", "a"), _h("run-b", "b")], aggregated_at=datetime(2026, 8, 11, tzinfo=UTC)
    )
    assert (
        a.evidence_count == b.evidence_count
        and a.research_run_ids == b.research_run_ids
        and a.summary_hash == b.summary_hash
        and a.summary_hash == ResearchEvidenceAggregation4a.content_hash(a)
    )


def test_duplicate_run_is_rejected():
    with pytest.raises(DomainViolation, match="duplicate"):
        aggregate_research_evidence_4a(
            [_h("run-a", "a"), _h("run-a", "b")], aggregated_at=datetime(2026, 8, 10, tzinfo=UTC)
        )


def test_empty_or_unsafe_evidence_fails_closed():
    with pytest.raises(DomainViolation, match="empty"):
        aggregate_research_evidence_4a([], aggregated_at=datetime(2026, 8, 10, tzinfo=UTC))
    unsafe = _h("run-a", "a").model_copy(update={"execution_authority": True})
    with pytest.raises(DomainViolation, match="safety"):
        aggregate_research_evidence_4a([unsafe], aggregated_at=datetime(2026, 8, 10, tzinfo=UTC))
