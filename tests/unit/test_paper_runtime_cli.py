from __future__ import annotations

import json

from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger


def _write_json(path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _request_payload() -> dict[str, object]:
    return {
        "candidate_id": "cand-scope-rsi-adx-001",
        "candidate_artifact_hash": "a" * 64,
        "qualified_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "symbol": "BTCUSDT",
        "side": "LONG",
        "mark_price": "100",
        "quantity": "0.1",
        "fee_rate": "0.0004",
        "slippage_bps": "2",
    }


def test_paper_runtime_cli_records_one_explicit_local_open(tmp_path, capsys) -> None:
    request_path = tmp_path / "request.json"
    evidence_path = tmp_path / "evidence.json"
    approval_path = tmp_path / "approval.json"
    ledger_path = tmp_path / "paper-ledger.sqlite3"
    _write_json(request_path, _request_payload())
    _write_json(
        evidence_path,
        {
            "candidate_id": "cand-scope-rsi-adx-001",
            "candidate_artifact_hash": "a" * 64,
            "qualification_hash": "b" * 64,
            "qualification_decision": "qualified",
            "zero_oos_liquidations": True,
        },
    )
    _write_json(
        approval_path,
        {
            "approval_id": "approval-open-001",
            "candidate_id": "cand-scope-rsi-adx-001",
            "candidate_artifact_hash": "a" * 64,
            "trade_id": "paper-001",
            "action": "open",
            "approved_at": "2026-08-13T00:00:00Z",
            "expires_at": "2026-08-13T00:01:00Z",
        },
    )

    from autonomous_futures.paper.runtime_cli import main

    exit_code = main(
        [
            "--ledger-path",
            str(ledger_path),
            "--request-path",
            str(request_path),
            "--evidence-path",
            str(evidence_path),
            "--approval-path",
            str(approval_path),
            "--action",
            "open",
            "--trade-id",
            "paper-001",
            "--occurred-at",
            "2026-08-13T00:00:00Z",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "opened"
    assert payload["paper_activation"] is False
    assert payload["execution_authority"] is False
    assert payload["exchange_access"] is False
    assert (
        SqlitePaperLedger(ledger_path).load().open_positions()[0].approval_id == "approval-open-001"
    )


def test_paper_runtime_cli_rejects_invalid_input_without_creating_ledger(tmp_path, capsys) -> None:
    request_path = tmp_path / "request.json"
    evidence_path = tmp_path / "evidence.json"
    approval_path = tmp_path / "approval.json"
    ledger_path = tmp_path / "paper-ledger.sqlite3"
    _write_json(request_path, {"mark_price": "not-a-decimal"})
    _write_json(evidence_path, {})
    _write_json(approval_path, {})

    from autonomous_futures.paper.runtime_cli import main

    exit_code = main(
        [
            "--ledger-path",
            str(ledger_path),
            "--request-path",
            str(request_path),
            "--evidence-path",
            str(evidence_path),
            "--approval-path",
            str(approval_path),
            "--action",
            "open",
            "--trade-id",
            "paper-001",
            "--occurred-at",
            "2026-08-13T00:00:00Z",
        ]
    )

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out) == {
        "error_code": "invalid_input",
        "status": "error",
    }
    assert not ledger_path.exists()


def test_paper_runtime_cli_records_one_explicit_local_close(tmp_path, capsys) -> None:
    request_path = tmp_path / "request.json"
    evidence_path = tmp_path / "evidence.json"
    open_approval_path = tmp_path / "open-approval.json"
    close_approval_path = tmp_path / "close-approval.json"
    ledger_path = tmp_path / "paper-ledger.sqlite3"
    _write_json(request_path, _request_payload())
    _write_json(
        evidence_path,
        {
            "candidate_id": "cand-scope-rsi-adx-001",
            "candidate_artifact_hash": "a" * 64,
            "qualification_hash": "b" * 64,
            "qualification_decision": "qualified",
            "zero_oos_liquidations": True,
        },
    )
    _write_json(
        open_approval_path,
        {
            "approval_id": "approval-open-001",
            "candidate_id": "cand-scope-rsi-adx-001",
            "candidate_artifact_hash": "a" * 64,
            "trade_id": "paper-001",
            "action": "open",
            "approved_at": "2026-08-13T00:00:00Z",
            "expires_at": "2026-08-13T00:01:00Z",
        },
    )
    _write_json(
        close_approval_path,
        {
            "approval_id": "approval-close-001",
            "candidate_id": "cand-scope-rsi-adx-001",
            "candidate_artifact_hash": "a" * 64,
            "trade_id": "paper-001",
            "action": "close",
            "approved_at": "2026-08-13T00:02:00Z",
            "expires_at": "2026-08-13T00:03:00Z",
        },
    )

    from autonomous_futures.paper.runtime_cli import main

    assert (
        main(
            [
                "--ledger-path",
                str(ledger_path),
                "--request-path",
                str(request_path),
                "--evidence-path",
                str(evidence_path),
                "--approval-path",
                str(open_approval_path),
                "--action",
                "open",
                "--trade-id",
                "paper-001",
                "--occurred-at",
                "2026-08-13T00:00:00Z",
            ]
        )
        == 0
    )
    capsys.readouterr()
    exit_code = main(
        [
            "--ledger-path",
            str(ledger_path),
            "--request-path",
            str(request_path),
            "--evidence-path",
            str(evidence_path),
            "--approval-path",
            str(close_approval_path),
            "--action",
            "close",
            "--trade-id",
            "paper-001",
            "--exit-mark-price",
            "110",
            "--occurred-at",
            "2026-08-13T00:02:00Z",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "closed"
    assert SqlitePaperLedger(ledger_path).load().open_positions() == ()
