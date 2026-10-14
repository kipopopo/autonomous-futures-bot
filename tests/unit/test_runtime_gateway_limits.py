import asyncio
from decimal import Decimal as D
from unittest.mock import AsyncMock

import httpx
import pytest

from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway


def gateway():
    g = BinanceFuturesGateway(offline_mode=True)
    g.symbol_specs["SOLUSDT"] = {
        "step_size": D(".01"),
        "tick_size": D(".01"),
        "min_qty": D(".01"),
        "max_qty": D("1"),
        "min_notional": D("5"),
    }
    return g


def test_entry_over_old_notional_cap_allowed():
    order = asyncio.run(gateway().create_order("SOLUSDT", "BUY", "LIMIT", D(".5"), price=D("100")))
    assert D(order["origQty"]) == D(".5")


def test_below_exchange_minimum_rejected_but_reduce_only_exit_allowed():
    g = gateway()
    with pytest.raises(ValueError, match="below the exchange minimum"):
        asyncio.run(g.create_order("SOLUSDT", "BUY", "LIMIT", D(".01"), price=D("100")))
    order = asyncio.run(
        g.create_order(
            "SOLUSDT", "SELL", "STOP_MARKET", D(".01"), stop_price=D("100"), reduce_only=True
        )
    )
    assert order["reduceOnly"] is True


def test_exchange_maximum_still_enforced():
    with pytest.raises(ValueError, match="exchange lot limits"):
        asyncio.run(gateway().create_order("SOLUSDT", "BUY", "LIMIT", D("1.01"), price=D("100")))


def test_exit_slicing_uses_exchange_maximum():
    assert gateway().split_exit_quantity("SOLUSDT", D("2.5"), D("100")) == (D("1"), D("1"), D(".5"))


def test_reduce_only_market_close_does_not_depend_on_ticker_availability():
    g = gateway()
    g.get_ticker_price = AsyncMock(side_effect=RuntimeError("market-data outage"))
    order = asyncio.run(g.create_order("SOLUSDT", "SELL", "MARKET", D(".5"), reduce_only=True))
    assert order["reduceOnly"] is True
    assert g.get_ticker_price.await_count == 0


def test_conditional_inventory_uses_separate_authenticated_endpoint():
    g = BinanceFuturesGateway(offline_mode=False)
    row = {"symbol": "SOLUSDT", "clientAlgoId": "actual-exchange-id-fixture"}
    g.signed_get = AsyncMock(return_value=[row])
    assert asyncio.run(g.get_open_algo_orders("solusdt")) == [row]
    g.signed_get.assert_awaited_once_with("/fapi/v1/openAlgoOrders", {"symbol": "SOLUSDT"})
    g.signed_get.return_value = [{**row, "symbol": "ETHUSDT"}]
    with pytest.raises(ValueError, match="inventory"):
        asyncio.run(g.get_open_algo_orders("SOLUSDT"))


def test_conditional_inventory_cannot_use_offline_state():
    with pytest.raises(ValueError, match="authenticated"):
        asyncio.run(gateway().get_open_algo_orders())


@pytest.mark.parametrize(
    "response,expected",
    [({"dualSidePosition": False}, False), ({"dualSidePosition": True}, True)],
)
def test_position_mode_uses_authenticated_exchange_evidence(response, expected):
    g = BinanceFuturesGateway(offline_mode=False)
    g.signed_get = AsyncMock(return_value=response)
    assert asyncio.run(g.get_position_mode()) is expected
    g.signed_get.assert_awaited_once_with("/fapi/v1/positionSide/dual", {})


@pytest.mark.parametrize(
    "response",
    [None, [], {}, {"dualSidePosition": "false"}, {"dualSidePosition": 0}],
)
def test_position_mode_rejects_missing_or_coerced_exchange_evidence(response):
    g = BinanceFuturesGateway(offline_mode=False)
    g.signed_get = AsyncMock(return_value=response)
    with pytest.raises(ValueError, match="position-mode evidence"):
        asyncio.run(g.get_position_mode())


@pytest.mark.parametrize(
    "testnet,foreign_key,foreign_secret",
    [
        (True, "BINANCE_API_KEY", "BINANCE_API_SECRET"),
        (False, "BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_SECRET_KEY"),
    ],
)
def test_credentials_never_cross_between_live_and_testnet(
    testnet, foreign_key, foreign_secret, monkeypatch
):
    from autonomous_futures.execution import binance_gateway

    monkeypatch.setattr(binance_gateway, "_load_dotenv_fallback", lambda: None)
    for name in (
        "BINANCE_TESTNET_API_KEY",
        "BINANCE_TESTNET_SECRET_KEY",
        "BINANCE_TESTNET_API_SECRET",
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "BINANCE_SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(foreign_key, "foreign-environment-key")
    monkeypatch.setenv(foreign_secret, "foreign-environment-secret")

    g = BinanceFuturesGateway(testnet=testnet, offline_mode=False)

    assert g.api_key == ""
    assert g.api_secret == ""
    with pytest.raises(ValueError, match="no authenticated key pair"):
        g.sign_payload({"symbol": "SOLUSDT"})


@pytest.mark.parametrize("missing", [None, "algoStatus", "clientAlgoId", "triggerPrice"])
def test_migrated_stop_ack_cannot_invent_missing_exchange_fields(missing):
    requests = []

    def transport(request):
        requests.append(request)
        if request.url.path == "/fapi/v1/order":
            return httpx.Response(400, json={"code": -4120, "msg": "Use Algo Order API"})
        params = request.url.params
        payload = {
            "symbol": params["symbol"],
            "side": params["side"],
            "algoId": 9,
            "clientAlgoId": params["clientAlgoId"],
            "algoStatus": "NEW",
            "quantity": params["quantity"],
            "triggerPrice": params["triggerPrice"],
            "reduceOnly": True,
        }
        if missing:
            payload.pop(missing)
        return httpx.Response(200, json=payload)

    g = BinanceFuturesGateway(offline_mode=False, mock_transport=httpx.MockTransport(transport))
    g.symbol_specs = gateway().symbol_specs
    call = g.create_order(
        "SOLUSDT", "SELL", "STOP_MARKET", D(".5"), stop_price=D("95"), reduce_only=True
    )
    if missing:
        with pytest.raises(ValueError, match="incomplete or mismatched"):
            asyncio.run(call)
    else:
        result = asyncio.run(call)
        assert result["clientOrderId"] == requests[1].url.params["clientAlgoId"]
        assert D(result["origQty"]) == D("0.5")
        assert result["status"] == "NEW"
    assert len(requests) == 2
    assert requests[1].url.params["reduceOnly"] == "true"
