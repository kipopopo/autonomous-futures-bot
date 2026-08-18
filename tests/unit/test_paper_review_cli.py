from __future__ import annotations

import json

from autonomous_futures.paper.cohort import (
    PaperCohortCandidateStatus,
    PaperCohortReadinessReport,
)
from autonomous_futures.paper.sqlite_review import SqlitePaperReviews


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


def test_paper_review_cli_records_explicit_checkpoint(tmp_path, capsys) -> None:
    report_path = tmp_path / "cohort-report.json"
    review_path = tmp_path / "reviews.sqlite3"
    report_path.write_text(
        _report().model_dump_json(),
        encoding="utf-8",
    )

    from autonomous_futures.paper.review_cli import main

    exit_code = main(
        [
            "--report-path",
            str(report_path),
            "--review-path",
            str(review_path),
            "--review-id",
            "review-001",
            "--reviewer-id",
            "human-reviewer-1",
            "--reviewed-at",
            "2026-08-08T01:00:00Z",
            "--decision",
            "accept_paper_observation",
            "--review-notes",
            "Reviewed the complete paper evidence cohort.",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "recorded"
    assert payload["decision"] == "accept_paper_observation"
    assert len(payload["cohort_report_hash"]) == 64
    assert SqlitePaperReviews(review_path).get("review-001") is not None


def test_paper_review_cli_rejects_acceptance_of_unready_report_without_write(
    tmp_path, capsys
) -> None:
    report_path = tmp_path / "cohort-report.json"
    review_path = tmp_path / "reviews.sqlite3"
    report_path.write_text(_report("not_ready").model_dump_json(), encoding="utf-8")

    from autonomous_futures.paper.review_cli import main

    exit_code = main(
        [
            "--report-path",
            str(report_path),
            "--review-path",
            str(review_path),
            "--review-id",
            "review-001",
            "--reviewer-id",
            "human-reviewer-1",
            "--reviewed-at",
            "2026-08-08T01:00:00Z",
            "--decision",
            "accept_paper_observation",
            "--review-notes",
            "Not accepted.",
        ]
    )

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out) == {
        "error_code": "invalid_input",
        "status": "error",
    }
    assert not review_path.exists()
