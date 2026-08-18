from decimal import Decimal

import pytest


def test_testnet_endpoint_allow_list_rejects_production_and_non_https() -> None:
    from autonomous_futures.testnet import validate_testnet_rest_url

    assert (
        validate_testnet_rest_url("https://demo-fapi.binance.com/fapi/v1/order")
        == "https://demo-fapi.binance.com/fapi/v1/order"
    )
    with pytest.raises(ValueError, match="testnet endpoint"):
        validate_testnet_rest_url("https://fapi.binance.com/fapi/v1/order")
    with pytest.raises(ValueError, match="testnet endpoint"):
        validate_testnet_rest_url("http://demo-fapi.binance.com/fapi/v1/order")
    with pytest.raises(ValueError, match="testnet endpoint"):
        validate_testnet_rest_url("https://demo-fapi.binance.com/api/v3/order")


def test_testnet_signing_is_deterministic_with_known_fake_secret_vector() -> None:
    import base64
    import binascii

    from autonomous_futures.testnet import sign_testnet_query

    signed = sign_testnet_query(
        {"timestamp": "1591702613943", "symbol": "BTCUSDT"},
        secret="test-secret",
    )
    query, signature = signed.rsplit("&signature=", 1)

    assert query == "symbol=BTCUSDT&timestamp=1591702613943"
    assert base64.b64encode(binascii.unhexlify(signature)).decode() == (
        "PD0xn/lJugtuPh+eZt2RqRlX6mI01aEZ9mIeX5vmtEQ="
    )


def test_testnet_risk_uses_quote_notional_and_applies_leverage_once() -> None:
    from autonomous_futures.testnet import (
        TestnetOrderProposal,
        TestnetSymbolFilters,
        validate_testnet_order,
    )

    decision = validate_testnet_order(
        TestnetOrderProposal(
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("0.1"),
            mark_price=Decimal("100"),
            leverage=Decimal("5"),
            reduce_only=False,
            existing_symbol_position=False,
            open_position_count=0,
            max_open_positions=1,
            max_quote_notional=Decimal("20"),
        ),
        TestnetSymbolFilters(
            symbol="BTCUSDT",
            min_quantity=Decimal("0.001"),
            max_quantity=Decimal("10"),
            step_size=Decimal("0.001"),
            min_notional=Decimal("5"),
            max_leverage=Decimal("20"),
        ),
    )

    assert decision.allowed is True
    assert decision.quote_notional == Decimal("10")
    assert decision.margin_notional == Decimal("2")
    assert decision.reason_codes == ("testnet_order_risk_approved",)


def test_testnet_risk_rejects_quote_limit_and_invalid_reduce_only_state() -> None:
    from autonomous_futures.testnet import (
        TestnetOrderProposal,
        TestnetSymbolFilters,
        validate_testnet_order,
    )

    proposal = TestnetOrderProposal(
        symbol="BTCUSDT",
        side="BUY",
        quantity=Decimal("0.1"),
        mark_price=Decimal("100"),
        leverage=Decimal("5"),
        reduce_only=True,
        existing_symbol_position=False,
        open_position_count=0,
        max_open_positions=1,
        max_quote_notional=Decimal("5"),
    )
    filters = TestnetSymbolFilters(
        symbol="BTCUSDT",
        min_quantity=Decimal("0.001"),
        max_quantity=Decimal("10"),
        step_size=Decimal("0.001"),
        min_notional=Decimal("5"),
        max_leverage=Decimal("20"),
    )

    decision = validate_testnet_order(proposal, filters)

    assert decision.allowed is False
    assert decision.reason_codes == (
        "quote_notional_limit_exceeded",
        "reduce_only_position_missing",
    )


def test_testnet_error_classification_never_retries_unknown_execution_status() -> None:
    from autonomous_futures.testnet import classify_testnet_error

    assert classify_testnet_error(503, "Unknown error, please check your request") == "reconcile"
    assert classify_testnet_error(503, "Service Unavailable.") == "retry"
    assert classify_testnet_error(429, "too many requests") == "retry"
    assert classify_testnet_error(418, "IP banned") == "halt"
    assert classify_testnet_error(400, "bad request") == "reject"


def test_testnet_reconciliation_halts_ambiguity_and_allows_only_proven_retry() -> None:
    from autonomous_futures.testnet import reconcile_testnet_order

    assert reconcile_testnet_order("not_submitted", None) == "safe_to_submit"
    assert reconcile_testnet_order("unknown", "FILLED") == "reconciled_no_retry"
    assert reconcile_testnet_order("unknown", "REJECTED") == "retry_allowed"
    assert reconcile_testnet_order("unknown", None) == "halt_ambiguous_state"
