# ruff: noqa
from datetime import UTC, datetime
import pytest
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_evidence_lineage_4e import (
    ResearchEvidenceLineageProjection4e,
    ResearchEvidenceSourceLineage4e,
)
from autonomous_futures.research_lab.research_evidence_gap_4g import (
    report_research_evidence_gaps_4g,
)


def _p(
    status="UNAVAILABLE",
    reason="missing_scope",
    scope_id="a",
    source_status="UNAVAILABLE",
    source_reason="missing_evidence",
):
    lineage = ResearchEvidenceSourceLineage4e(
        scope_id=scope_id,
        availability_status=source_status,
        reason=source_reason,
        expected_research_run_ids=(scope_id,),
        observed_research_run_ids=(),
        summary_hash=None,
        availability_hash="a" * 64,
    )
    draft = ResearchEvidenceLineageProjection4e.model_construct(
        status=status,
        reason=reason,
        scope_ids=(scope_id,),
        lineage=(lineage,),
        projected_at=datetime(2026, 8, 10, tzinfo=UTC),
        projection_hash="0" * 64,
    )
    return ResearchEvidenceLineageProjection4e.model_validate(
        {
            **draft.model_dump(),
            "projection_hash": ResearchEvidenceLineageProjection4e.content_hash(draft),
        }
    )


def test_gap_report_is_deterministic_and_preserves_reasons():
    result = report_research_evidence_gaps_4g(
        _p(), expected_scope_ids=("a", "b"), reported_at=datetime(2026, 8, 11, tzinfo=UTC)
    )
    assert (
        result.status == "INCOMPLETE"
        and result.gap_scope_ids == ("b",)
        and result.unavailable_scope_ids == ("a",)
        and result.reasons == ("incomplete_scope", "b:missing_scope", "a:missing_evidence")
    )


def test_complete_projection_has_no_gaps():
    result = report_research_evidence_gaps_4g(
        _p(status="AVAILABLE", reason=None, source_status="AVAILABLE", source_reason=None),
        expected_scope_ids=("a",),
        reported_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    assert (
        result.status == "COMPLETE"
        and result.gap_scope_ids == ()
        and result.unavailable_scope_ids == ()
    )


def test_tampered_projection_fails_closed():
    with pytest.raises(DomainViolation, match="projection hash"):
        report_research_evidence_gaps_4g(
            _p().model_copy(update={"projection_hash": "f" * 64}),
            expected_scope_ids=("a",),
            reported_at=datetime(2026, 8, 11, tzinfo=UTC),
        )
