from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from autonomous_futures.paper.observation import PaperObservation
from autonomous_futures.paper.sqlite_observation import SqlitePaperObservations

CANDIDATE_ID = "cand-scope-rsi-adx-001"
CANDIDATE_HASH = "a" * 64


def test_maturity_inspect_cli_reports_mature_journal_without_mutation(tmp_path, capsys) -> None:
    path = tmp_path / "observations.sqlite3"
    store = SqlitePaperObservations(path)
    first = datetime(2026, 8, 1, tzinfo=UTC)
    for index in range(28):
        store.append(
            PaperObservation(
                candidate_id=CANDIDATE_ID,
                candidate_artifact_hash=CANDIDATE_HASH,
                observed_at=first + timedelta(hours=6 * index),
                equity=Decimal("100"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                peak_equity=Decimal("100"),
                drawdown_pct=Decimal("0"),
                open_position_count=0,
                quote_exposure=Decimal("0"),
                cumulative_fees=Decimal("0"),
                cumulative_slippage=Decimal("0"),
                accounting_complete=True,
                reason_codes=("paper_observation_complete",),
            )
        )
    before = len(store.read(CANDIDATE_ID, CANDIDATE_HASH))

    from autonomous_futures.paper.maturity_inspect_cli import main

    exit_code = main(
        [
            "--observation-path",
            str(path),
            "--candidate-id",
            CANDIDATE_ID,
            "--candidate-artifact-hash",
            CANDIDATE_HASH,
            "--as-of",
            "2026-08-08T00:00:00Z",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "mature"
    assert payload["observed_slots"] == 28
    assert payload["paper_activation"] is False
    assert payload["execution_authority"] is False
    assert payload["exchange_access"] is False
    assert len(store.read(CANDIDATE_ID, CANDIDATE_HASH)) == before


def test_maturity_inspect_cli_reports_unavailable_without_creating_journal(
    tmp_path, capsys
) -> None:
    from autonomous_futures.paper.maturity_inspect_cli import main

    path = tmp_path / "absent.sqlite3"
    exit_code = main(
        [
            "--observation-path",
            str(path),
            "--candidate-id",
            CANDIDATE_ID,
            "--candidate-artifact-hash",
            CANDIDATE_HASH,
            "--as-of",
            "2026-08-08T00:00:00Z",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"
    assert not path.exists()
