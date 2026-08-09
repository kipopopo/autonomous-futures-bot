# ruff: noqa: E501
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab import (
    research_observation_integrity_evaluation_observation_result as result,
)
from autonomous_futures.research_lab.research_observation_integrity_evaluation_observation_result_persistence import (  # noqa: E501
    read_research_observation_integrity_evaluation_observation_review,
    write_research_observation_integrity_evaluation_observation_review,
)


def _review() -> result.ResearchObservationIntegrityEvaluationObservationReview:
    provisional = result.ResearchObservationIntegrityEvaluationObservationReview.model_construct(
        review_version=1,
        review_status="verified",
        review_scope="audit_integrity_only",
        research_run_id="research-run-0001",
        source_observation_input_hash="a" * 64,
        source_evaluation_input_hash="b" * 64,
        source_observation_hash="c" * 64,
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
            **provisional.model_dump(),
            "review_hash": result.research_observation_integrity_evaluation_observation_review_content_hash(
                provisional
            ),
        }
    )


def test_persistence_round_trips_review(tmp_path: Path) -> None:
    review = _review()
    path = tmp_path / "review.json"
    assert (
        write_research_observation_integrity_evaluation_observation_review(path, review) == review
    )
    assert read_research_observation_integrity_evaluation_observation_review(path) == review


def test_persistence_is_idempotent_and_immutable(tmp_path: Path) -> None:
    review = _review()
    path = tmp_path / "review.json"
    write_research_observation_integrity_evaluation_observation_review(path, review)
    assert (
        write_research_observation_integrity_evaluation_observation_review(path, review) == review
    )
    changed = review.model_copy(update={"research_run_id": "research-run-0002"})
    changed = changed.model_copy(
        update={
            "review_hash": result.research_observation_integrity_evaluation_observation_review_content_hash(
                changed
            )
        }
    )
    with pytest.raises(DomainViolation, match="path is immutable"):
        write_research_observation_integrity_evaluation_observation_review(path, changed)


def test_persistence_rejects_tampered_malformed_and_bad_input(tmp_path: Path) -> None:
    review = _review()
    path = tmp_path / "review.json"
    bad = review.model_copy(update={"review_hash": "0" * 64})
    with pytest.raises(DomainViolation, match="hash mismatch"):
        write_research_observation_integrity_evaluation_observation_review(path, bad)
    write_research_observation_integrity_evaluation_observation_review(path, review)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(DataQualityError):
        read_research_observation_integrity_evaluation_observation_review(path)
