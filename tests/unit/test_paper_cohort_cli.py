from __future__ import annotations

import json


def test_cohort_cli_reports_ready_for_human_review_from_explicit_json(tmp_path, capsys) -> None:
    expected_path = tmp_path / "expected.json"
    reports_path = tmp_path / "reports.json"
    bindings = [
        {
            "candidate_id": "cand-alpha-1",
            "candidate_artifact_hash": "a" * 64,
        },
        {
            "candidate_id": "cand-beta-2",
            "candidate_artifact_hash": "b" * 64,
        },
    ]
    reports = [
        {
            **binding,
            "as_of": "2026-08-08T00:00:00Z",
            "health_status": "healthy",
            "maturity_status": "mature",
            "accounting_complete": True,
            "reason_codes": ["paper_health_healthy"],
        }
        for binding in bindings
    ]
    expected_path.write_text(json.dumps(bindings), encoding="utf-8")
    reports_path.write_text(json.dumps(reports), encoding="utf-8")

    from autonomous_futures.paper.cohort_cli import main

    exit_code = main(
        [
            "--expected-path",
            str(expected_path),
            "--reports-path",
            str(reports_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ready_for_human_review"
    assert payload["expected_candidate_count"] == 2
    assert payload["all_mature"] is True
    assert payload["paper_activation"] is False
    assert payload["execution_authority"] is False
    assert payload["exchange_access"] is False


def test_cohort_cli_rejects_invalid_json_without_writing(tmp_path, capsys) -> None:
    from autonomous_futures.paper.cohort_cli import main

    expected_path = tmp_path / "expected.json"
    reports_path = tmp_path / "reports.json"
    expected_path.write_text("not-json", encoding="utf-8")
    reports_path.write_text("[]", encoding="utf-8")

    exit_code = main(
        [
            "--expected-path",
            str(expected_path),
            "--reports-path",
            str(reports_path),
        ]
    )

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out) == {
        "error_code": "invalid_input",
        "status": "error",
    }
