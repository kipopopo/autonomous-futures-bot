from datetime import UTC, datetime
from decimal import Decimal

import pytest


def _review(decision: str = "approve_live_design"):
    from autonomous_futures.live_review import create_live_activation_review

    return create_live_activation_review(
        review_id="review-live-001",
        reviewed_by="human-reviewer-1",
        reviewed_at=datetime(2026, 8, 20, tzinfo=UTC),
        expires_at=datetime(2026, 8, 21, tzinfo=UTC),
        decision=decision,
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


def test_activation_token_is_one_shot_and_not_network_enabled() -> None:
    from autonomous_futures.live_activation import issue_live_activation_token

    token = issue_live_activation_token(
        _review(),
        token_id="token-live-001",
        issued_at=datetime(2026, 8, 20, 1, tzinfo=UTC),
        expires_at=datetime(2026, 8, 20, 2, tzinfo=UTC),
    )

    assert token.review_id == "review-live-001"
    assert token.max_quote_notional_pct == Decimal("50")
    assert token.max_capital_at_risk_pct == Decimal("1")
    assert token.max_daily_loss_pct == Decimal("2")
    assert token.remaining_uses == 1
    assert token.state == "issued_not_enabled"
    assert token.live_enabled is False
    assert token.network_allowed is False
    assert len(token.token_hash) == 64


def test_activation_token_rejects_unapproved_review_or_extended_expiry() -> None:
    from autonomous_futures.live_activation import issue_live_activation_token

    with pytest.raises(ValueError, match="review is not approved"):
        issue_live_activation_token(
            _review("needs_attention"),
            token_id="token-live-002",
            issued_at=datetime(2026, 8, 20, 1, tzinfo=UTC),
            expires_at=datetime(2026, 8, 20, 2, tzinfo=UTC),
        )

    with pytest.raises(ValueError, match="review expiry"):
        issue_live_activation_token(
            _review(),
            token_id="token-live-003",
            issued_at=datetime(2026, 8, 20, 1, tzinfo=UTC),
            expires_at=datetime(2026, 8, 21, 1, tzinfo=UTC),
        )


def test_sqlite_activation_token_journal_is_write_once(tmp_path) -> None:
    from autonomous_futures.live_activation import (
        SqliteLiveActivationTokens,
        issue_live_activation_token,
    )

    token = issue_live_activation_token(
        _review(),
        token_id="token-live-004",
        issued_at=datetime(2026, 8, 20, 1, tzinfo=UTC),
        expires_at=datetime(2026, 8, 20, 2, tzinfo=UTC),
    )
    path = tmp_path / "live-tokens.sqlite3"
    store = SqliteLiveActivationTokens(path)
    store.append(token)
    store.append(token)

    assert store.get(token.token_id) == token
    assert store.read() == (token,)
    with pytest.raises(ValueError, match="conflicting live token ID"):
        store.append(token.model_copy(update={"remaining_uses": 0}))

    absent = tmp_path / "absent.sqlite3"
    assert SqliteLiveActivationTokens(absent).read() == ()
    assert not absent.exists()
