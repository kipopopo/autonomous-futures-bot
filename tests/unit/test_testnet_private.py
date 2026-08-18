from decimal import Decimal

import pytest


def _account_body() -> dict[str, object]:
    return {
        "totalWalletBalance": "100.00",
        "availableBalance": "90.00",
        "assets": [{"asset": "USDT", "walletBalance": "100.00", "availableBalance": "90.00"}],
        "positions": [
            {
                "symbol": "BTCUSDT",
                "positionAmt": "0.1",
                "entryPrice": "100",
                "markPrice": "110",
                "positionSide": "BOTH",
            }
        ],
    }


def test_private_account_request_is_signed_without_returning_secret() -> None:
    from autonomous_futures.testnet_private import build_testnet_account_request

    request = build_testnet_account_request(
        api_key="fake-api-key",
        secret="fake-secret",
        timestamp_ms=1591702613943,
    )

    assert request.method == "GET"
    assert request.url == "https://demo-fapi.binance.com/fapi/v3/account"
    assert request.headers == {
        "Accept": "application/json",
        "X-MBX-APIKEY": "fake-api-key",
    }
    assert "timestamp=1591702613943" in request.signed_query
    assert "recvWindow=5000" in request.signed_query
    assert "fake-secret" not in request.model_dump_json()
    assert request.signed_query.endswith(tuple("0123456789abcdef"))


def test_private_account_request_rejects_empty_credentials_and_non_testnet_base() -> None:
    from autonomous_futures.testnet_private import build_testnet_account_request

    with pytest.raises(ValueError, match="API key"):
        build_testnet_account_request(
            api_key="",
            secret="fake-secret",
            timestamp_ms=1591702613943,
        )
    with pytest.raises(ValueError, match="testnet base URL"):
        build_testnet_account_request(
            api_key="fake-api-key",
            secret="fake-secret",
            timestamp_ms=1591702613943,
            base_url="https://fapi.binance.com",
        )


def test_account_parser_and_exact_position_reconciliation() -> None:
    from autonomous_futures.testnet_private import (
        TestnetPositionExpectation,
        parse_testnet_account_snapshot,
        reconcile_testnet_account,
    )

    snapshot = parse_testnet_account_snapshot(_account_body())
    result = reconcile_testnet_account(
        snapshot,
        (
            TestnetPositionExpectation(
                symbol="BTCUSDT", position_side="BOTH", position_amt=Decimal("0.1")
            ),
        ),
    )

    assert snapshot.total_wallet_balance == Decimal("100.00")
    assert snapshot.positions[0].mark_price == Decimal("110")
    assert result.status == "reconciled"
    assert result.reason_codes == ("testnet_account_reconciled",)


def test_account_reconciliation_blocks_drift_and_unexpected_positions() -> None:
    from autonomous_futures.testnet_private import (
        TestnetPositionExpectation,
        parse_testnet_account_snapshot,
        reconcile_testnet_account,
    )

    snapshot = parse_testnet_account_snapshot(_account_body())
    result = reconcile_testnet_account(
        snapshot,
        (
            TestnetPositionExpectation(
                symbol="ETHUSDT", position_side="BOTH", position_amt=Decimal("0.1")
            ),
        ),
    )

    assert result.status == "drift"
    assert result.missing_symbols == ("ETHUSDT",)
    assert result.unexpected_symbols == ("BTCUSDT",)
    assert result.reason_codes == ("testnet_account_position_drift",)
