from datetime import UTC, datetime

from autonomous_futures.paper.health import PaperHealthReport
from autonomous_futures.paper.observation import PaperObservationBinding


def _binding(candidate_id: str) -> PaperObservationBinding:
    return PaperObservationBinding(
        candidate_id=candidate_id,
        candidate_artifact_hash=("a" if candidate_id.endswith("1") else "b") * 64,
    )


def _health(binding: PaperObservationBinding, status: str = "healthy") -> PaperHealthReport:
    maturity = "mature" if status in ("healthy", "attention") else status
    return PaperHealthReport(
        candidate_id=binding.candidate_id,
        candidate_artifact_hash=binding.candidate_artifact_hash,
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
        health_status=status,
        maturity_status=maturity,
        accounting_complete=status == "healthy",
        reason_codes=(f"{status}_reason",),
    )


def test_cohort_summary_reports_ready_for_human_review_only_when_all_are_healthy() -> None:
    from autonomous_futures.paper.cohort import summarize_paper_cohort

    expected = (_binding("cand-alpha-1"), _binding("cand-beta-2"))
    report = summarize_paper_cohort(
        (_health(expected[0]), _health(expected[1])),
        expected,
    )

    assert report.cohort_status == "ready_for_human_review"
    assert report.expected_candidate_count == 2
    assert report.reported_candidate_count == 2
    assert report.healthy_candidate_count == 2
    assert report.mature_candidate_count == 2
    assert report.missing_candidate_ids == ()
    assert report.reason_codes == ("paper_cohort_ready_for_human_review",)
    assert report.paper_activation is False
    assert report.execution_authority is False
    assert report.exchange_access is False


def test_cohort_summary_reports_not_ready_for_missing_and_attention_candidates() -> None:
    from autonomous_futures.paper.cohort import summarize_paper_cohort

    expected = (_binding("cand-alpha-1"), _binding("cand-beta-2"))
    report = summarize_paper_cohort((_health(expected[0], "attention"),), expected)

    assert report.cohort_status == "not_ready"
    assert report.reported_candidate_count == 1
    assert report.attention_candidate_count == 1
    assert report.missing_candidate_ids == ("cand-beta-2",)
    assert report.reason_codes == ("paper_cohort_candidate_missing",)


def test_cohort_summary_blocks_blocked_candidate() -> None:
    from autonomous_futures.paper.cohort import summarize_paper_cohort

    expected = (_binding("cand-alpha-1"),)
    report = summarize_paper_cohort((_health(expected[0], "blocked"),), expected)

    assert report.cohort_status == "blocked"
    assert report.blocked_candidate_count == 1
    assert report.reason_codes == ("paper_cohort_candidate_blocked",)


def test_cohort_summary_blocks_duplicate_candidate_report() -> None:
    from autonomous_futures.paper.cohort import summarize_paper_cohort

    expected = (_binding("cand-alpha-1"),)
    report = summarize_paper_cohort(
        (_health(expected[0]), _health(expected[0])),
        expected,
    )

    assert report.cohort_status == "blocked"
    assert report.reason_codes == ("paper_cohort_report_binding_invalid",)


def test_cohort_summary_reports_unavailable_without_reports() -> None:
    from autonomous_futures.paper.cohort import summarize_paper_cohort

    expected = (_binding("cand-alpha-1"),)
    report = summarize_paper_cohort((), expected)

    assert report.cohort_status == "unavailable"
    assert report.missing_candidate_ids == ("cand-alpha-1",)
    assert report.reason_codes == ("paper_cohort_health_unavailable",)
