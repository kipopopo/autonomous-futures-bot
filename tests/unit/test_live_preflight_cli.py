import json
from datetime import UTC, datetime
from decimal import Decimal


def _token():
    from autonomous_futures.live_activation import issue_live_activation_token
    from autonomous_futures.live_review import create_live_activation_review

    review = create_live_activation_review(
        review_id="review-live-001",
        reviewed_by="human-reviewer-1",
        reviewed_at=datetime(2026, 8, 20, tzinfo=UTC),
        expires_at=datetime(2026, 8, 21, tzinfo=UTC),
        decision="approve_live_design",
        candidate_id="cand-scope-rsi-adx-001",
        candidate_artifact_hash="a" * 64,
        testnet_completion_hash="b" * 64,
        legal_review_confirmed=True,
        venue_account_confirmed=True,
        capital_risk_confirmed=True,
        secret_manager_confirmed=True,
        kill_switch_confirmed=True,
        reconciliation_clean=True,
        symbol_approved=True,
        explicit_live_activation=True,
        symbol="BTCUSDT",
        max_quote_notional_pct=Decimal("50"),
        max_capital_at_risk_pct=Decimal("1"),
        max_daily_loss_pct=Decimal("2"),
    )
    return issue_live_activation_token(
        review,
        token_id="token-live-001",
        issued_at=datetime(2026, 8, 20, 1, tzinfo=UTC),
        expires_at=datetime(2026, 8, 20, 2, tzinfo=UTC),
    )


def test_preflight_cli_defaults_to_blocked_without_operator_assertions(tmp_path, capsys) -> None:
    from autonomous_futures.live_activation import SqliteLiveActivationTokens
    from autonomous_futures.live_preflight_cli import main

    token_db = tmp_path / "tokens.sqlite3"
    SqliteLiveActivationTokens(token_db).append(_token())
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir()
    (credential_dir / "BINANCE_LIVE_API_KEY").write_text("opaque", encoding="utf-8")
    (credential_dir / "BINANCE_LIVE_SECRET_KEY").write_text("opaque", encoding="utf-8")

    exit_code = main(
        [
            "--token-db",
            str(token_db),
            "--credential-dir",
            str(credential_dir),
            "--base-url",
            "https://fapi.binance.com",
            "--now",
            "2026-08-20T01:30:00+00:00",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 3
    assert payload["status"] == "blocked"
    assert payload["network_allowed"] is False
    assert payload["reason_codes"] == [
        "account_not_reconciled",
        "positions_not_flat",
        "kill_switch_not_verified",
        "token_not_enabled",
    ]


def test_preflight_cli_can_report_static_ready_without_network(tmp_path, capsys) -> None:
    from autonomous_futures.live_activation import SqliteLiveActivationTokens
    from autonomous_futures.live_preflight_cli import main

    token_db = tmp_path / "tokens.sqlite3"
    SqliteLiveActivationTokens(token_db).append(_token())
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir()
    for name in ("BINANCE_LIVE_API_KEY", "BINANCE_LIVE_SECRET_KEY"):
        (credential_dir / name).write_text("opaque", encoding="utf-8")

    exit_code = main(
        [
            "--token-db",
            str(token_db),
            "--credential-dir",
            str(credential_dir),
            "--base-url",
            "https://fapi.binance.com",
            "--account-reconciled",
            "--positions-flat",
            "--kill-switch-ready",
            "--now",
            "2026-08-20T01:30:00+00:00",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "ready_for_manual_activation"
    assert payload["network_allowed"] is False
