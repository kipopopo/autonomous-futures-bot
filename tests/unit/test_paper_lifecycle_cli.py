from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from autonomous_futures.paper.ledger import PaperLedgerEntry
from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger
from autonomous_futures.paper.sqlite_lifecycle import SqlitePaperLifecycle


def test_lifecycle_mark_cli_records_explicit_mark(tmp_path, capsys) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    lifecycle_path = tmp_path / "lifecycle.sqlite3"
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
            occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
            approval_id="approval-open-001",
            entry_fee=Decimal("0.004"),
            slippage_cost=Decimal("0.002"),
        )
    )

    from autonomous_futures.paper.lifecycle_cli import main

    exit_code = main(
        [
            "--ledger-path",
            str(ledger_path),
            "--lifecycle-path",
            str(lifecycle_path),
            "--candidate-id",
            "cand-scope-rsi-adx-001",
            "--candidate-artifact-hash",
            "a" * 64,
            "--trade-id",
            "paper-001",
            "--mark-price",
            "110",
            "--marked-at",
            "2026-08-01T01:00:00Z",
            "--previous-peak-pnl",
            "0.5",
            "--take-profit-price",
            "108",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "recorded"
    assert payload["lifecycle_status"] == "exit_ready"
    assert payload["take_profit_hit"] is True
    assert (
        SqlitePaperLifecycle(lifecycle_path).latest(
            candidate_id="cand-scope-rsi-adx-001",
            candidate_artifact_hash="a" * 64,
            trade_id="paper-001",
        )
        is not None
    )


def test_lifecycle_mark_cli_reports_missing_open_without_creating_journal(tmp_path, capsys) -> None:
    from autonomous_futures.paper.lifecycle_cli import main

    ledger_path = tmp_path / "absent-ledger.sqlite3"
    lifecycle_path = tmp_path / "lifecycle.sqlite3"
    exit_code = main(
        [
            "--ledger-path",
            str(ledger_path),
            "--lifecycle-path",
            str(lifecycle_path),
            "--candidate-id",
            "cand-scope-rsi-adx-001",
            "--candidate-artifact-hash",
            "a" * 64,
            "--trade-id",
            "paper-001",
            "--mark-price",
            "110",
            "--marked-at",
            "2026-08-01T01:00:00Z",
            "--previous-peak-pnl",
            "0",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "reason_codes": ["durable_open_position_missing"],
        "status": "unavailable",
    }
    assert not lifecycle_path.exists()
