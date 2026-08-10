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


def _availability(status: str, reason: str | None, scope: str):
    draft = ResearchEvidenceAvailability4c.model_construct(
        availability_status=status,
        reason=reason,
        evidence_count=1 if status == "AVAILABLE" else 0,
        expected_research_run_ids=(scope,),
        observed_research_run_ids=(scope,) if status == "AVAILABLE" else (),
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


def test_status_is_order_independent_and_available_only_when_all_scopes_available():
    a = compose_research_evidence_status_4d(
        [
            ResearchEvidenceScope4d(
                scope_id="z", availability=_availability("AVAILABLE", None, "z")
            ),
            ResearchEvidenceScope4d(
                scope_id="a", availability=_availability("AVAILABLE", None, "a")
            ),
        ],
        expected_scope_ids=("a", "z"),
        reported_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    assert (
        a.status == "AVAILABLE"
        and a.scope_ids == ("a", "z")
        and a.available_scope_count == 2
        and not a.execution_authority
    )


def test_missing_scope_is_unavailable():
    result = compose_research_evidence_status_4d(
        [ResearchEvidenceScope4d(scope_id="a", availability=_availability("AVAILABLE", None, "a"))],
        expected_scope_ids=("a", "b"),
        reported_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    assert (
        result.status == "UNAVAILABLE"
        and result.reason == "missing_scope"
        and result.available_scope_count == 1
    )


def test_underlying_unavailable_is_preserved():
    result = compose_research_evidence_status_4d(
        [
            ResearchEvidenceScope4d(
                scope_id="a", availability=_availability("UNAVAILABLE", "missing_evidence", "a")
            )
        ],
        expected_scope_ids=("a",),
        reported_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    assert result.status == "UNAVAILABLE" and result.reason == "underlying_unavailable"


def test_tampered_availability_fails_closed():
    bad = _availability("AVAILABLE", None, "a").model_copy(update={"availability_hash": "f" * 64})
    with pytest.raises(DomainViolation, match="hash"):
        compose_research_evidence_status_4d(
            [ResearchEvidenceScope4d(scope_id="a", availability=bad)],
            expected_scope_ids=("a",),
            reported_at=datetime(2026, 8, 10, tzinfo=UTC),
        )
