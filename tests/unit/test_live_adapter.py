from datetime import UTC, datetime
from decimal import Decimal

import pytest


def _review():
    from autonomous_futures.live_review import create_live_activation_review

    return create_live_activation_review(
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


def test_live_order_descriptor_is_production_only() -> None:
    from autonomous_futures.live_adapter import build_live_order_request

    request = build_live_order_request(
        symbol="BTCUSDT",
        side="BUY",
        quantity=Decimal("0.0008"),
        api_key="fake-live-key",
        secret="fake-live-secret",
        timestamp_ms=1,
    )

    assert request.method == "POST"
    assert request.url == "https://fapi.binance.com/fapi/v1/order"
    assert request.headers == {"Accept": "application/json", "X-MBX-APIKEY": "fake-live-key"}
    assert "signature=" in request.signed_query

    with pytest.raises(ValueError, match="production endpoint"):
        build_live_order_request(
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0.0008"),
            api_key="fake-live-key",
            secret="fake-live-secret",
            timestamp_ms=1,
            base_url="https://demo-fapi.binance.com",
        )
    with pytest.raises(ValueError, match="finite positive Decimal"):
        build_live_order_request(
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0"),
            api_key="fake-live-key",
            secret="fake-live-secret",
            timestamp_ms=1,
        )


def test_reviewed_not_activated_blocks_transport_before_send() -> None:
    from autonomous_futures.live_adapter import (
        build_live_order_request,
        send_live_order_request,
    )

    request = build_live_order_request(
        symbol="BTCUSDT",
        side="BUY",
        quantity=Decimal("0.0008"),
        api_key="fake-live-key",
        secret="fake-live-secret",
        timestamp_ms=1,
    )
    calls: list[object] = []

    def transport(value: object) -> object:
        calls.append(value)
        return {"status": 200}

    with pytest.raises(ValueError, match="not activated"):
        send_live_order_request(_review(), request, transport)

    assert calls == []
