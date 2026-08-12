from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from autonomous_futures.paper.observation import PaperObservation
from autonomous_futures.paper.sqlite_observation import SqlitePaperObservations


def test_observation_inspect_cli_prints_latest_snapshot(tmp_path, capsys) -> None:
    path = tmp_path / "observations.sqlite3"
    store = SqlitePaperObservations(path)
    for observed_at, equity in (
        (datetime(2026, 8, 11, tzinfo=UTC), Decimal("100")),
        (datetime(2026, 8, 11, 1, tzinfo=UTC), Decimal("101")),
    ):
        store.append(
            PaperObservation(
                candidate_id="cand-scope-rsi-adx-001",
                candidate_artifact_hash="a" * 64,
                observed_at=observed_at,
                equity=equity,
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                peak_equity=equity,
                drawdown_pct=Decimal("0"),
                open_position_count=0,
                quote_exposure=Decimal("0"),
                cumulative_fees=Decimal("0"),
                cumulative_slippage=Decimal("0"),
                accounting_complete=True,
                reason_codes=("paper_observation_complete",),
            )
        )

    from autonomous_futures.paper.observation_inspect_cli import main

    exit_code = main(
        [
            "--observation-path",
            str(path),
            "--candidate-id",
            "cand-scope-rsi-adx-001",
            "--candidate-artifact-hash",
            "a" * 64,
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "available"
    assert payload["equity"] == "101"
    assert payload["paper_activation"] is False
    assert payload["execution_authority"] is False
    assert payload["exchange_access"] is False
    assert len(SqlitePaperObservations(path).read("cand-scope-rsi-adx-001", "a" * 64)) == 2


def test_observation_inspect_cli_rejects_malformed_candidate_binding(tmp_path, capsys) -> None:
    from autonomous_futures.paper.observation_inspect_cli import main

    exit_code = main(
        [
            "--observation-path",
            str(tmp_path / "observations.sqlite3"),
            "--candidate-id",
            "not-a-candidate",
            "--candidate-artifact-hash",
            "not-a-hash",
        ]
    )

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out) == {
        "error_code": "invalid_input",
        "status": "error",
    }
