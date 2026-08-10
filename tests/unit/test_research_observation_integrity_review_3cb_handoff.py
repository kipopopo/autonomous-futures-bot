# ruff: noqa
from datetime import UTC, datetime
import pytest
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity_review_3cb_handoff import (
    ResearchObservationIntegrityReview3cbHandoff,
    handoff_verified_research_observation_integrity_review_3cb,
    research_observation_integrity_review_3cb_content_hash,
)
from autonomous_futures.research_lab import (
    research_observation_integrity_review_3cb_handoff as module,
)


def _review():
    return type(
        "Review",
        (),
        {
            "research_run_id": "research-run-0001",
            "review_hash": "a" * 64,
            "source_observation_hash": "b" * 64,
            "source_handoff_hash": "c" * 64,
            "source_evaluation_input_hash": "d" * 64,
            "reviewed_at": datetime(2026, 8, 10, tzinfo=UTC),
        },
    )()


def test_handoff_is_deterministic_and_ignores_created_at(monkeypatch):
    monkeypatch.setattr(
        module,
        "load_verified_research_observation_integrity_review_3ca",
        lambda *args, **kwargs: _review(),
    )
    a = handoff_verified_research_observation_integrity_review_3cb(
        review_path=None, observation=None
    )
    b = handoff_verified_research_observation_integrity_review_3cb(
        review_path=None, observation=None
    )
    assert a == b and a.handoff_hash == research_observation_integrity_review_3cb_content_hash(a)


def test_lineage_and_safety_fields_are_retained(monkeypatch):
    monkeypatch.setattr(
        module,
        "load_verified_research_observation_integrity_review_3ca",
        lambda *args, **kwargs: _review(),
    )
    h = handoff_verified_research_observation_integrity_review_3cb(
        review_path=None, observation=None
    )
    assert (
        h.research_run_id == "research-run-0001"
        and h.source_review_hash == "a" * 64
        and h.handoff_status == "verified_audit_only"
        and h.promotion_state == "unpromoted"
        and not h.paper_activation
        and not h.execution_authority
    )


def test_invalid_safety_state_rejected():
    with pytest.raises(ValueError):
        ResearchObservationIntegrityReview3cbHandoff.model_validate(
            {
                "research_run_id": "x",
                "source_review_hash": "a" * 64,
                "source_observation_hash": "b" * 64,
                "source_handoff_hash": "c" * 64,
                "source_evaluation_input_hash": "d" * 64,
                "created_at": "2026-08-10T00:00:00Z",
                "handoff_hash": "e" * 64,
                "execution_authority": True,
            }
        )
