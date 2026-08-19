import json


def test_testnet_completion_cli_reports_unavailable_without_creating_journals(
    tmp_path, capsys
) -> None:
    from autonomous_futures.testnet_completion_cli import main

    paths = [
        tmp_path / name for name in ("audits.sqlite3", "observations.sqlite3", "reviews.sqlite3")
    ]
    exit_code = main(
        [
            "--audit-path",
            str(paths[0]),
            "--observation-path",
            str(paths[1]),
            "--review-path",
            str(paths[2]),
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"
    assert all(not path.exists() for path in paths)
