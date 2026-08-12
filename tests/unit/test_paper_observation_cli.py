from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from autonomous_futures.paper.ledger import PaperLedgerEntry
from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger
from autonomous_futures.paper.sqlite_observation import SqlitePaperObservations


def test_observation_cli_captures_explicit_inputs_without_external_access(tmp_path, capsys) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    observation_path = tmp_path / "observations.sqlite3"
    marks_path = tmp_path / "marks.json"
    marks_path.write_text('{"BTCUSDT":"110"}\n', encoding="utf-8")
    SqlitePaperLedger(ledger_path).append(
        PaperLedgerEntry(
            event="open",
            trade_id="paper-001",
            candidate_id="cand-scope-rsi-adx-001",
            candidate_artifact_hash="a" * 64,
            symbol="BTCUSDT",
            side="LONG",
            quantity=Decimal("0.1"),
            fill_price=Decimal("100"),
            occurred_at=datetime(2026, 8, 11, tzinfo=UTC),
            entry_fee=Decimal("0.01"),
            slippage_cost=Decimal("0.02"),
        )
    )

    from autonomous_futures.paper.observation_cli import main

    exit_code = main(
        [
            "--ledger-path",
            str(ledger_path),
            "--observation-path",
            str(observation_path),
            "--candidate-id",
            "cand-scope-rsi-adx-001",
            "--candidate-artifact-hash",
            "a" * 64,
            "--starting-equity",
            "100",
            "--previous-peak-equity",
            "100",
            "--marks-path",
            str(marks_path),
            "--observed-at",
            "2026-08-11T01:00:00Z",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "captured"
    assert payload["paper_activation"] is False
    assert payload["execution_authority"] is False
    assert payload["exchange_access"] is False
    assert payload["accounting_complete"] is True
    assert SqlitePaperObservations(observation_path).read("cand-scope-rsi-adx-001", "a" * 64)[
        0
    ].equity == Decimal("100.99")
