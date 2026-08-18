from datetime import UTC, datetime

import pytest

from autonomous_futures.paper.cohort import (
    PaperCohortCandidateStatus,
    PaperCohortReadinessReport,
)


def _report(status: str = "ready_for_human_review") -> PaperCohortReadinessReport:
    return PaperCohortReadinessReport(
        cohort_status=status,
        expected_candidate_count=1,
        reported_candidate_count=1,
        healthy_candidate_count=1 if status == "ready_for_human_review" else 0,
        mature_candidate_count=1 if status == "ready_for_human_review" else 0,
        attention_candidate_count=0,
        maturing_candidate_count=0,
        blocked_candidate_count=0,
        all_mature=status == "ready_for_human_review",
        all_accounting_complete=status == "ready_for_human_review",
        candidates=(
            PaperCohortCandidateStatus(
                candidate_id="cand-alpha-1",
                candidate_artifact_hash="a" * 64,
                health_status="healthy" if status == "ready_for_human_review" else "blocked",
                maturity_status="mature" if status == "ready_for_human_review" else "blocked",
                accounting_complete=status == "ready_for_human_review",
                reason_codes=("paper_health_healthy",),
            ),
        ),
        reason_codes=("paper_cohort_ready_for_human_review",),
    )


def test_paper_review_checkpoint_hashes_cohort_and_accepts_only_ready_review() -> None:
    from autonomous_futures.paper.review import create_paper_review_checkpoint

    checkpoint = create_paper_review_checkpoint(
        _report(),
        review_id="review-001",
        reviewer_id="human-reviewer-1",
        reviewed_at=datetime(2026, 8, 8, 1, tzinfo=UTC),
        decision="accept_paper_observation",
        review_notes="Reviewed the complete paper evidence cohort.",
    )

    assert len(checkpoint.cohort_report_hash) == 64
    assert checkpoint.decision == "accept_paper_observation"
    assert checkpoint.paper_activation is False
    assert checkpoint.execution_authority is False
    assert checkpoint.exchange_access is False


def test_paper_review_checkpoint_rejects_acceptance_of_unready_cohort() -> None:
    from autonomous_futures.paper.review import create_paper_review_checkpoint

    with pytest.raises(ValueError, match="ready_for_human_review"):
        create_paper_review_checkpoint(
            _report("not_ready"),
            review_id="review-001",
            reviewer_id="human-reviewer-1",
            reviewed_at=datetime(2026, 8, 8, 1, tzinfo=UTC),
            decision="accept_paper_observation",
            review_notes="Not accepted.",
        )
