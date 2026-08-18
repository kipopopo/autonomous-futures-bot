from datetime import UTC, datetime

import pytest

from autonomous_futures.paper.cohort import (
    PaperCohortCandidateStatus,
    PaperCohortReadinessReport,
)
from autonomous_futures.paper.review import create_paper_review_checkpoint


def _checkpoint():
    report = PaperCohortReadinessReport(
        cohort_status="ready_for_human_review",
        expected_candidate_count=1,
        reported_candidate_count=1,
        healthy_candidate_count=1,
        mature_candidate_count=1,
        attention_candidate_count=0,
        maturing_candidate_count=0,
        blocked_candidate_count=0,
        all_mature=True,
        all_accounting_complete=True,
        candidates=(
            PaperCohortCandidateStatus(
                candidate_id="cand-alpha-1",
                candidate_artifact_hash="a" * 64,
                health_status="healthy",
                maturity_status="mature",
                accounting_complete=True,
                reason_codes=("paper_health_healthy",),
            ),
        ),
        reason_codes=("paper_cohort_ready_for_human_review",),
    )
    return create_paper_review_checkpoint(
        report,
        review_id="review-001",
        reviewer_id="human-reviewer-1",
        reviewed_at=datetime(2026, 8, 8, 1, tzinfo=UTC),
        decision="accept_paper_observation",
        review_notes="Reviewed the complete paper evidence cohort.",
    )


def test_sqlite_review_journal_rehydrates_and_idempotently_retries(tmp_path) -> None:
    from autonomous_futures.paper.sqlite_review import SqlitePaperReviews

    path = tmp_path / "reviews.sqlite3"
    store = SqlitePaperReviews(path)
    checkpoint = _checkpoint()
    store.append(checkpoint)
    store.append(checkpoint)

    reopened = SqlitePaperReviews(path)
    assert reopened.get("review-001") == checkpoint
    assert reopened.read() == (checkpoint,)

    with pytest.raises(ValueError, match="conflicting review ID"):
        store.append(checkpoint.model_copy(update={"review_notes": "changed"}))


def test_sqlite_review_absent_read_does_not_create_database(tmp_path) -> None:
    from autonomous_futures.paper.sqlite_review import SqlitePaperReviews

    path = tmp_path / "absent.sqlite3"
    assert SqlitePaperReviews(path).get("review-001") is None
    assert SqlitePaperReviews(path).read() == ()
    assert not path.exists()
