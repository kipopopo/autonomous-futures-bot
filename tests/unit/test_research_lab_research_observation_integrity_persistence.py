from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.research_observation_integrity import (
    ResearchObservationIntegrityReview,
    research_observation_integrity_content_hash,
)
from autonomous_futures.research_lab.research_observation_integrity_persistence import (
    read_research_observation_integrity_review,
    write_research_observation_integrity_review,
)


def _review() -> ResearchObservationIntegrityReview:
    provisional = ResearchObservationIntegrityReview.model_construct(
        review_version=1,
        review_status="verified",
        research_run_id="research-run-0001",
        source_evaluation_input_hash="a" * 64,
        check_ids=("audit_only_status", "audit_integrity_scope", "safety_locks"),
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        reviewed_at=datetime(2026, 8, 9, tzinfo=UTC),
        review_hash="0" * 64,
    )
    return ResearchObservationIntegrityReview.model_validate(
        {
            **provisional.model_dump(),
            "review_hash": research_observation_integrity_content_hash(provisional),
        }
    )


def test_integrity_review_persistence_round_trips_verified_review(tmp_path: Path) -> None:
    review = _review()
    path = tmp_path / "reviews" / "research-run-0001.json"

    assert write_research_observation_integrity_review(path, review) == review
    assert read_research_observation_integrity_review(path) == review


def test_integrity_review_persistence_is_idempotent_and_write_once(tmp_path: Path) -> None:
    review = _review()
    path = tmp_path / "research-run-0001.json"

    assert write_research_observation_integrity_review(path, review) == review
    assert write_research_observation_integrity_review(path, review) == review

    changed = review.model_copy(update={"reviewed_at": datetime(2026, 8, 9, 1, tzinfo=UTC)})
    with pytest.raises(DomainViolation, match="immutable"):
        write_research_observation_integrity_review(path, changed)


def test_integrity_review_reader_rejects_tampered_malformed_and_missing_artifacts(
    tmp_path: Path,
) -> None:
    review = _review()
    path = tmp_path / "research-run-0001.json"
    write_research_observation_integrity_review(path, review)
    path.write_text(
        path.read_text(encoding="utf-8").replace(review.review_hash, "0" * 64),
        encoding="utf-8",
    )

    with pytest.raises(DomainViolation, match="hash mismatch"):
        read_research_observation_integrity_review(path)

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not-json", encoding="utf-8")
    with pytest.raises(DataQualityError, match="invalid persisted"):
        read_research_observation_integrity_review(malformed)
    with pytest.raises(FileNotFoundError):
        read_research_observation_integrity_review(tmp_path / "missing.json")


def test_integrity_review_writer_rejects_hash_mismatch_before_filesystem_work(
    tmp_path: Path,
) -> None:
    review = _review()
    path = tmp_path / "new" / "research-run-0001.json"
    invalid = review.model_copy(update={"review_hash": "0" * 64})

    with pytest.raises(DomainViolation, match="hash mismatch"):
        write_research_observation_integrity_review(path, invalid)
    assert not path.parent.exists()


def test_integrity_review_writer_cleans_temp_file_on_link_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = _review()
    path = tmp_path / "research-run-0001.json"

    def fail_link(source: Path, destination: Path) -> None:
        raise OSError("link failed")

    monkeypatch.setattr(
        "autonomous_futures.research_lab.research_observation_integrity_persistence.os.link",
        fail_link,
    )

    with pytest.raises(OSError, match="link failed"):
        write_research_observation_integrity_review(path, review)
    assert not path.exists()
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))
