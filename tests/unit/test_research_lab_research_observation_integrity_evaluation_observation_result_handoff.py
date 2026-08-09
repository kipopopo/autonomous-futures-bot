# ruff: noqa
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab import (
    research_observation_integrity_evaluation_observation_result as result,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_result_handoff import (
    ResearchObservationIntegrityEvaluationObservationHandoff,
    build_verified_research_observation_integrity_evaluation_observation_handoff,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_result_persistence import (
    write_research_observation_integrity_evaluation_observation_review,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_result_input import (
    ResearchObservationIntegrityEvaluationObservationInput,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation import (
    research_observation_integrity_evaluation_observation_content_hash,
)


def _input() -> ResearchObservationIntegrityEvaluationObservationInput:
    p = ResearchObservationIntegrityEvaluationObservationInput.model_construct(
        input_version=1,
        observation_status="audit_only",
        research_run_id="research-run-0001",
        source_handoff_hash="a" * 64,
        source_review_hash="b" * 64,
        source_evaluation_input_hash="c" * 64,
        source_observation_hash="d" * 64,
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
        input_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationInput.model_validate(
        {
            **p.model_dump(),
            "input_hash": research_observation_integrity_evaluation_observation_content_hash(p),
        }
    )


def _review(
    i: ResearchObservationIntegrityEvaluationObservationInput,
) -> result.ResearchObservationIntegrityEvaluationObservationReview:
    p = result.ResearchObservationIntegrityEvaluationObservationReview.model_construct(
        review_version=1,
        review_status="verified",
        review_scope="audit_integrity_only",
        research_run_id=i.research_run_id,
        source_observation_input_hash=i.input_hash,
        source_evaluation_input_hash=i.source_evaluation_input_hash,
        source_observation_hash=i.source_observation_hash,
        check_ids=("audit_only_status", "audit_integrity_scope", "safety_locks"),
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        reviewed_at=datetime(2026, 8, 9, tzinfo=UTC),
        review_hash="0" * 64,
    )
    return result.ResearchObservationIntegrityEvaluationObservationReview.model_validate(
        {
            **p.model_dump(),
            "review_hash": result.research_observation_integrity_evaluation_observation_review_content_hash(
                p
            ),
        }
    )


def test_handoff_preserves_verified_lineage(tmp_path: Path) -> None:
    i = _input()
    path = tmp_path / "review.json"
    r = _review(i)
    write_research_observation_integrity_evaluation_observation_review(path, r)
    h = build_verified_research_observation_integrity_evaluation_observation_handoff(
        path, observation_input=i, created_at=datetime(2026, 8, 9, tzinfo=UTC)
    )
    assert isinstance(h, ResearchObservationIntegrityEvaluationObservationHandoff)
    assert h.handoff_status == "verified_audit_only"
    assert h.source_review_hash == r.review_hash
    assert h.source_observation_input_hash == i.input_hash
    assert h.check_count == 3
    assert (
        h.promotion_state == "unpromoted"
        and h.paper_activation is False
        and h.execution_authority is False
    )


def test_handoff_rejects_invalid_input(tmp_path: Path) -> None:
    i = _input()
    path = tmp_path / "review.json"
    write_research_observation_integrity_evaluation_observation_review(path, _review(i))
    with pytest.raises(DomainViolation, match="observation input hash mismatch"):
        build_verified_research_observation_integrity_evaluation_observation_handoff(
            path, observation_input=i.model_copy(update={"input_hash": "0" * 64})
        )


def test_handoff_hash_excludes_created_at(tmp_path: Path) -> None:
    i = _input()
    path = tmp_path / "review.json"
    write_research_observation_integrity_evaluation_observation_review(path, _review(i))
    a = build_verified_research_observation_integrity_evaluation_observation_handoff(
        path, observation_input=i, created_at=datetime(2026, 8, 9, tzinfo=UTC)
    )
    b = build_verified_research_observation_integrity_evaluation_observation_handoff(
        path, observation_input=i, created_at=datetime(2026, 8, 9, 1, tzinfo=UTC)
    )
    assert a.handoff_hash == b.handoff_hash and a.created_at != b.created_at
