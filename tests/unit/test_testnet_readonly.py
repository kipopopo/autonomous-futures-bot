from typing import Any

import pytest


def _exchange_info() -> dict[str, Any]:
    return {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "status": "TRADING",
                "baseAsset": "BTC",
                "quoteAsset": "USDT",
                "contractType": "PERPETUAL",
            },
            {
                "symbol": "ETHUSDT",
                "status": "TRADING",
                "baseAsset": "ETH",
                "quoteAsset": "USDT",
                "contractType": "PERPETUAL",
            },
            {
                "symbol": "测试测试USDT",
                "status": "TRADING",
                "baseAsset": "TEST",
                "quoteAsset": "USDT",
                "contractType": "PERPETUAL",
            },
        ]
    }


def test_read_only_testnet_client_uses_injected_get_transport_and_typed_exchange_info() -> None:
    from autonomous_futures.testnet_readonly import TestnetReadOnlyClient, TestnetResponse

    calls: list[tuple[str, str, dict[str, str]]] = []

    def transport(method: str, url: str, query: dict[str, str]) -> TestnetResponse:
        calls.append((method, url, query))
        return TestnetResponse(status_code=200, body=_exchange_info())

    client = TestnetReadOnlyClient(
        transport,
        base_url="https://demo-fapi.binance.com",
    )
    info = client.get_exchange_info()

    assert tuple(symbol.symbol for symbol in info.symbols) == (
        "BTCUSDT",
        "ETHUSDT",
        "测试测试USDT",
    )
    assert info.symbols[0].quote_asset == "USDT"
    assert calls == [
        (
            "GET",
            "https://demo-fapi.binance.com/fapi/v1/exchangeInfo",
            {},
        )
    ]


def test_read_only_testnet_client_selects_symbol_and_rejects_missing_symbol() -> None:
    from autonomous_futures.testnet_readonly import TestnetReadOnlyClient, TestnetResponse

    client = TestnetReadOnlyClient(
        lambda method, url, query: TestnetResponse(status_code=200, body=_exchange_info()),
        base_url="https://demo-fapi.binance.com",
    )

    assert client.get_symbol("BTCUSDT").base_asset == "BTC"
    with pytest.raises(ValueError, match="symbol unavailable"):
        client.get_symbol("SOLUSDT")


def test_read_only_testnet_client_classifies_error_without_retrying() -> None:
    from autonomous_futures.testnet_readonly import (
        TestnetReadOnlyClient,
        TestnetReadOnlyError,
        TestnetResponse,
    )

    client = TestnetReadOnlyClient(
        lambda method, url, query: TestnetResponse(
            status_code=503,
            body={"msg": "Unknown error, please check your request"},
        ),
        base_url="https://demo-fapi.binance.com",
    )

    with pytest.raises(TestnetReadOnlyError, match="reconcile") as error:
        client.get_exchange_info()
    assert error.value.disposition == "reconcile"


def test_read_only_testnet_client_rejects_production_base_url_and_malformed_body() -> None:
    from autonomous_futures.testnet_readonly import (
        TestnetReadOnlyClient,
        TestnetReadOnlyError,
        TestnetResponse,
    )

    with pytest.raises(ValueError, match="testnet base URL"):
        TestnetReadOnlyClient(
            lambda method, url, query: TestnetResponse(status_code=200, body=_exchange_info()),
            base_url="https://fapi.binance.com",
        )

    client = TestnetReadOnlyClient(
        lambda method, url, query: TestnetResponse(status_code=200, body={"symbols": "bad"}),
        base_url="https://demo-fapi.binance.com",
    )
    with pytest.raises(TestnetReadOnlyError, match="malformed"):
        client.get_exchange_info()


def test_public_testnet_transport_uses_stdlib_get_without_credentials(monkeypatch) -> None:
    import json

    from autonomous_futures.testnet_readonly import public_testnet_transport

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(_exchange_info()).encode("utf-8")

    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("autonomous_futures.testnet_readonly.urllib.request.urlopen", fake_urlopen)

    response = public_testnet_transport(
        "GET",
        "https://demo-fapi.binance.com/fapi/v1/exchangeInfo",
        {},
    )

    request = captured["request"]
    assert response.status_code == 200
    assert response.body == _exchange_info()
    assert request.get_method() == "GET"
    assert request.full_url == "https://demo-fapi.binance.com/fapi/v1/exchangeInfo"
    assert request.get_header("X-mbx-apikey") is None
    assert captured["timeout"] == 10
