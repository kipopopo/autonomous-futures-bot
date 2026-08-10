# ruff: noqa
from datetime import UTC, datetime
import pytest
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_evidence_availability_4c import (
    ResearchEvidenceAvailability4c,
)
from autonomous_futures.research_lab.research_evidence_status_4d import (
    compose_research_evidence_status_4d,
    ResearchEvidenceScope4d,
)
from autonomous_futures.research_lab.research_evidence_lineage_4e import (
    project_research_evidence_lineage_4e,
)
from autonomous_futures.research_lab.research_evidence_lineage_consumer_4f import (
    consume_research_evidence_lineage_4f,
)


def _availability(status: str, reason: str | None, run: str):
    draft = ResearchEvidenceAvailability4c.model_construct(
        availability_status=status,
        reason=reason,
        evidence_count=1 if status == "AVAILABLE" else 0,
        expected_research_run_ids=(run,),
        observed_research_run_ids=(run,) if status == "AVAILABLE" else (),
        summary_hash="a" * 64 if status == "AVAILABLE" else None,
        assessed_at=datetime(2026, 8, 10, tzinfo=UTC),
        availability_hash="0" * 64,
    )
    return ResearchEvidenceAvailability4c.model_validate(
        {
            **draft.model_dump(),
            "availability_hash": ResearchEvidenceAvailability4c.content_hash(draft),
        }
    )


def _projection(status: str, reason: str | None):
    source = ResearchEvidenceScope4d(
        scope_id="a", availability=_availability(status, reason, "run-a")
    )
    aggregate = compose_research_evidence_status_4d(
        [source], expected_scope_ids=("a",), reported_at=datetime(2026, 8, 10, tzinfo=UTC)
    )
    return project_research_evidence_lineage_4e(
        aggregate, [source], projected_at=datetime(2026, 8, 10, tzinfo=UTC)
    )


def test_consumer_preserves_unavailable_and_source_hashes():
    result = consume_research_evidence_lineage_4f(
        _projection("UNAVAILABLE", "missing_evidence"),
        consumed_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    assert (
        result.status == "UNAVAILABLE"
        and result.reason == "missing_evidence"
        and result.unavailable_scope_count == 1
        and len(result.source_availability_hashes) == 1
        and not result.execution_authority
    )


def test_consumer_reports_available_projection():
    result = consume_research_evidence_lineage_4f(
        _projection("AVAILABLE", None), consumed_at=datetime(2026, 8, 11, tzinfo=UTC)
    )
    assert (
        result.status == "AVAILABLE"
        and result.reason is None
        and result.available_scope_count == 1
        and result.unavailable_scope_count == 0
    )


def test_tampered_projection_fails_closed():
    bad = _projection("AVAILABLE", None).model_copy(update={"projection_hash": "f" * 64})
    with pytest.raises(DomainViolation, match="projection hash"):
        consume_research_evidence_lineage_4f(bad, consumed_at=datetime(2026, 8, 11, tzinfo=UTC))
