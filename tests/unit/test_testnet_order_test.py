from decimal import Decimal

import pytest


def _filters():
    from autonomous_futures.testnet import TestnetSymbolFilters

    return TestnetSymbolFilters(
        symbol="BTCUSDT",
        min_quantity=Decimal("0.001"),
        max_quantity=Decimal("10"),
        step_size=Decimal("0.001"),
        min_notional=Decimal("5"),
        max_leverage=Decimal("20"),
    )


def _proposal(max_quote_notional: str = "20"):
    from autonomous_futures.testnet import TestnetOrderProposal

    return TestnetOrderProposal(
        symbol="BTCUSDT",
        side="BUY",
        quantity=Decimal("0.1"),
        mark_price=Decimal("100"),
        leverage=Decimal("5"),
        reduce_only=False,
        existing_symbol_position=False,
        open_position_count=0,
        max_open_positions=1,
        max_quote_notional=Decimal(max_quote_notional),
    )


def test_order_test_request_is_signed_only_after_risk_gate() -> None:
    from autonomous_futures.testnet_order_test import build_testnet_order_test_request

    request = build_testnet_order_test_request(
        _proposal(),
        _filters(),
        api_key="fake-api-key",
        secret="fake-secret",
        timestamp_ms=1591702613943,
        client_order_id="afbot-test-001",
    )

    assert request.method == "POST"
    assert request.url == "https://demo-fapi.binance.com/fapi/v1/order/test"
    assert request.headers == {
        "Accept": "application/json",
        "X-MBX-APIKEY": "fake-api-key",
    }
    assert "symbol=BTCUSDT" in request.signed_query
    assert "side=BUY" in request.signed_query
    assert "type=MARKET" in request.signed_query
    assert "quantity=0.1" in request.signed_query
    assert "newClientOrderId=afbot-test-001" in request.signed_query
    assert "fake-secret" not in request.model_dump_json()
    assert request.live_enabled is False


def test_order_test_request_rejects_risk_block_before_descriptor_creation() -> None:
    from autonomous_futures.testnet_order_test import build_testnet_order_test_request

    with pytest.raises(ValueError, match="risk"):
        build_testnet_order_test_request(
            _proposal("5"),
            _filters(),
            api_key="fake-api-key",
            secret="fake-secret",
            timestamp_ms=1591702613943,
            client_order_id="afbot-test-001",
        )
