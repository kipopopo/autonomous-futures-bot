# ruff: noqa
from __future__ import annotations
from datetime import UTC, datetime
from pathlib import Path
import pytest
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_result_input import (
    ResearchObservationIntegrityEvaluationObservationObservationInput,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_result_persistence import (
    write_research_observation_integrity_evaluation_observation_observation_review,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_result import (
    ResearchObservationIntegrityEvaluationObservationObservationReview,
    research_observation_integrity_evaluation_observation_observation_review_content_hash,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation_result_input import (
    load_verified_research_observation_integrity_evaluation_observation_observation_review,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_observation import (
    research_observation_integrity_evaluation_observation_observation_content_hash,
)


def _observation(source="a" * 64):
    p = ResearchObservationIntegrityEvaluationObservationObservationInput.model_construct(
        observation_version=1,
        observation_status="audit_only",
        research_run_id="research-run-0001",
        source_handoff_hash="b" * 64,
        source_review_hash="c" * 64,
        source_evaluation_input_hash="d" * 64,
        source_observation_hash=source,
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        observed_at=datetime(2026, 8, 9, tzinfo=UTC),
        observation_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationObservationInput.model_validate(
        {
            **p.model_dump(),
            "observation_hash": research_observation_integrity_evaluation_observation_observation_content_hash(
                p
            ),
        }
    )


def _review(o):
    p = ResearchObservationIntegrityEvaluationObservationObservationReview.model_construct(
        review_version=1,
        review_status="verified",
        review_scope="audit_integrity_only",
        research_run_id=o.research_run_id,
        source_observation_hash=o.observation_hash,
        source_handoff_hash=o.source_handoff_hash,
        source_review_hash=o.source_review_hash,
        source_evaluation_input_hash=o.source_evaluation_input_hash,
        check_ids=("audit_only_status", "audit_integrity_scope", "safety_locks"),
        check_count=3,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        reviewed_at=datetime(2026, 8, 9, tzinfo=UTC),
        review_hash="0" * 64,
    )
    return ResearchObservationIntegrityEvaluationObservationObservationReview.model_validate(
        {
            **p.model_dump(),
            "review_hash": research_observation_integrity_evaluation_observation_observation_review_content_hash(
                p
            ),
        }
    )


def test_loader_binds_observation(tmp_path: Path):
    o = _observation()
    p = tmp_path / "review.json"
    r = _review(o)
    write_research_observation_integrity_evaluation_observation_observation_review(p, r)
    assert (
        load_verified_research_observation_integrity_evaluation_observation_observation_review(
            p, observation=o
        )
        == r
    )


def test_loader_rejects_tampered_observation(tmp_path: Path):
    o = _observation()
    p = tmp_path / "review.json"
    write_research_observation_integrity_evaluation_observation_observation_review(p, _review(o))
    with pytest.raises(DomainViolation, match="observation hash mismatch"):
        load_verified_research_observation_integrity_evaluation_observation_observation_review(
            p, observation=o.model_copy(update={"observation_hash": "0" * 64})
        )


def test_loader_rejects_wrong_lineage(tmp_path: Path):
    o = _observation()
    p = tmp_path / "review.json"
    write_research_observation_integrity_evaluation_observation_observation_review(p, _review(o))
    with pytest.raises(DomainViolation, match="binding is invalid"):
        load_verified_research_observation_integrity_evaluation_observation_observation_review(
            p, observation=_observation("e" * 64)
        )
