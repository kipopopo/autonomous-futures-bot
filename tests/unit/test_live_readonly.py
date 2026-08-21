from decimal import Decimal

import pytest


def _body(position_amt: str = "0") -> dict[str, object]:
    return {
        "totalWalletBalance": "100.00",
        "availableBalance": "100.00",
        "assets": [
            {
                "asset": "USDT",
                "walletBalance": "100.00",
                "availableBalance": "100.00",
            }
        ],
        "positions": [
            {
                "symbol": "BTCUSDT",
                "positionAmt": position_amt,
                "positionSide": "BOTH",
            }
        ],
    }


def test_live_account_request_is_production_read_only() -> None:
    from autonomous_futures.live_readonly import build_live_account_request

    request = build_live_account_request(
        api_key="fake-live-key",
        secret="fake-live-secret",
        timestamp_ms=1,
    )

    assert request.method == "GET"
    assert request.url == "https://fapi.binance.com/fapi/v3/account"
    assert request.headers == {"Accept": "application/json", "X-MBX-APIKEY": "fake-live-key"}
    assert "signature=" in request.signed_query
    assert request.order_capability is False

    with pytest.raises(ValueError, match="production endpoint"):
        build_live_account_request(
            api_key="fake-live-key",
            secret="fake-live-secret",
            timestamp_ms=1,
            base_url="https://demo-fapi.binance.com",
        )


def test_live_account_snapshot_reconciles_flat_account() -> None:
    from autonomous_futures.live_readonly import (
        LivePositionExpectation,
        parse_live_account_snapshot,
        reconcile_live_account,
    )

    snapshot = parse_live_account_snapshot(_body())
    decision = reconcile_live_account(snapshot, (LivePositionExpectation(symbol="BTCUSDT"),))

    assert snapshot.total_wallet_balance == Decimal("100.00")
    assert len(snapshot.assets) == 1
    assert decision.status == "reconciled"
    assert decision.reason_codes == ("live_account_reconciled",)


def test_live_account_snapshot_detects_nonzero_position() -> None:
    from autonomous_futures.live_readonly import (
        LivePositionExpectation,
        parse_live_account_snapshot,
        reconcile_live_account,
    )

    snapshot = parse_live_account_snapshot(_body("0.001"))
    decision = reconcile_live_account(snapshot, (LivePositionExpectation(symbol="BTCUSDT"),))

    assert decision.status == "drift"
    assert decision.unexpected_symbols == ("BTCUSDT",)
