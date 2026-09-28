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
    serialized = request.model_dump_json()
    rendered = repr(request)
    assert "fake-live-key" not in serialized
    assert request.signed_query not in serialized
    assert "fake-live-key" not in rendered
    assert request.signed_query not in rendered

    with pytest.raises(ValueError, match="production endpoint"):
        build_live_account_request(
            api_key="fake-live-key",
            secret="fake-live-secret",
            timestamp_ms=1,
            base_url="https://demo-fapi.binance.com",
        )


def test_live_account_transport_rejects_redirect_without_following(monkeypatch) -> None:
    import io
    import urllib.error
    import urllib.request

    from autonomous_futures.live_readonly import build_live_account_request, fetch_live_account

    request = build_live_account_request(
        api_key="fake-live-key", secret="fake-live-secret", timestamp_ms=1
    )
    requests: list[object] = []

    def fake_build_opener(*handlers):
        assert any(
            isinstance(handler, urllib.request.HTTPRedirectHandler)
            and handler.redirect_request(None, None, 302, "Found", {}, "https://evil.invalid")
            is None
            for handler in handlers
        )

        class Opener:
            def open(self, http_request, timeout):
                requests.append(http_request)
                raise urllib.error.HTTPError(
                    http_request.full_url,
                    302,
                    "redirect blocked",
                    {"Location": "https://evil.invalid/fapi/v3/account"},
                    io.BytesIO(b'{"msg":"redirect blocked"}'),
                )

        return Opener()

    monkeypatch.setattr(
        "autonomous_futures.live_readonly.urllib.request.build_opener", fake_build_opener
    )

    with pytest.raises(RuntimeError, match="HTTP 302"):
        fetch_live_account(request)
    assert len(requests) == 1


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


def test_live_account_snapshot_rejects_duplicate_position_keys() -> None:
    from autonomous_futures.live_readonly import (
        LivePositionExpectation,
        parse_live_account_snapshot,
        reconcile_live_account,
    )

    body = _body("0.001")
    body["positions"] = [
        {"symbol": "BTCUSDT", "positionAmt": "0.001", "positionSide": "BOTH"},
        {"symbol": "BTCUSDT", "positionAmt": "0.001", "positionSide": "BOTH"},
    ]
    decision = reconcile_live_account(
        parse_live_account_snapshot(body),
        (LivePositionExpectation(symbol="BTCUSDT", position_amt=Decimal("0.001")),),
    )

    assert decision.status == "drift"
    assert decision.reason_codes == ("duplicate_exchange_position_keys",)


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
