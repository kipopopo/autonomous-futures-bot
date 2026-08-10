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


def test_lineage_is_deterministic_and_preserves_source_identity():
    a = ResearchEvidenceScope4d(
        scope_id="z", availability=_availability("AVAILABLE", None, "run-z")
    )
    b = ResearchEvidenceScope4d(
        scope_id="a", availability=_availability("UNAVAILABLE", "missing_evidence", "run-a")
    )
    status = compose_research_evidence_status_4d(
        [a, b], expected_scope_ids=("a", "z"), reported_at=datetime(2026, 8, 10, tzinfo=UTC)
    )
    result = project_research_evidence_lineage_4e(
        status, [a, b], projected_at=datetime(2026, 8, 11, tzinfo=UTC)
    )
    assert (
        result.scope_ids == ("a", "z")
        and result.lineage[0].availability_status == "UNAVAILABLE"
        and result.lineage[1].summary_hash == "a" * 64
        and result.status == "UNAVAILABLE"
        and not result.execution_authority
    )


def test_tampered_source_availability_fails_closed():
    source = ResearchEvidenceScope4d(
        scope_id="a", availability=_availability("AVAILABLE", None, "run-a")
    )
    status = compose_research_evidence_status_4d(
        [source], expected_scope_ids=("a",), reported_at=datetime(2026, 8, 10, tzinfo=UTC)
    )
    bad = source.model_copy(
        update={
            "availability": source.availability.model_copy(update={"availability_hash": "f" * 64})
        }
    )
    with pytest.raises(DomainViolation, match="hash"):
        project_research_evidence_lineage_4e(
            status, [bad], projected_at=datetime(2026, 8, 10, tzinfo=UTC)
        )


def test_status_binding_mismatch_fails_closed():
    source = ResearchEvidenceScope4d(
        scope_id="a", availability=_availability("AVAILABLE", None, "run-a")
    )
    status = compose_research_evidence_status_4d(
        [source], expected_scope_ids=("a",), reported_at=datetime(2026, 8, 10, tzinfo=UTC)
    ).model_copy(update={"status_hash": "f" * 64})
    with pytest.raises(DomainViolation, match="status hash"):
        project_research_evidence_lineage_4e(
            status, [source], projected_at=datetime(2026, 8, 10, tzinfo=UTC)
        )
