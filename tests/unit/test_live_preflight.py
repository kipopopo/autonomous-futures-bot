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


def test_live_preflight_is_ready_for_manual_activation_but_never_network_enabled(
    tmp_path,
) -> None:
    from autonomous_futures.live_preflight import evaluate_live_preflight

    (tmp_path / "BINANCE_LIVE_API_KEY").write_text("opaque", encoding="utf-8")
    (tmp_path / "BINANCE_LIVE_SECRET_KEY").write_text("opaque", encoding="utf-8")

    decision = evaluate_live_preflight(
        _token(),
        credential_dir=tmp_path,
        base_url="https://fapi.binance.com",
        account_reconciled=True,
        positions_flat=True,
        kill_switch_ready=True,
        now=datetime(2026, 8, 20, 1, 30, tzinfo=UTC),
    )

    assert decision.status == "ready_for_manual_activation"
    assert decision.reason_codes == ("token_not_enabled",)
    assert decision.credential_names_present == (
        "BINANCE_LIVE_API_KEY",
        "BINANCE_LIVE_SECRET_KEY",
    )
    assert decision.live_enabled is False
    assert decision.network_allowed is False


def test_live_preflight_blocks_missing_static_gates(tmp_path) -> None:
    from autonomous_futures.live_preflight import evaluate_live_preflight

    decision = evaluate_live_preflight(
        _token(),
        credential_dir=tmp_path,
        base_url="https://demo-fapi.binance.com",
        account_reconciled=False,
        positions_flat=False,
        kill_switch_ready=False,
        now=datetime(2026, 8, 20, 1, 30, tzinfo=UTC),
    )

    assert decision.status == "blocked"
    assert "credential_missing_BINANCE_LIVE_API_KEY" in decision.reason_codes
    assert "invalid_production_endpoint" in decision.reason_codes
    assert "account_not_reconciled" in decision.reason_codes
    assert "positions_not_flat" in decision.reason_codes
    assert "kill_switch_not_verified" in decision.reason_codes
    assert decision.network_allowed is False
