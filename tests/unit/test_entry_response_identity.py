import pytest

from autonomous_futures.execution.live_orders import LiveOrderBook


@pytest.mark.parametrize(
    "field,value",
    [
        ("clientOrderId", "foreign"),
        ("symbol", "ETHUSDT"),
        ("side", "SELL"),
        ("origQty", "2"),
        ("price", "99"),
        ("reduceOnly", True),
        ("executedQty", "0.1"),
        ("status", "UNRECOGNIZED"),
    ],
)
def test_invalid_response_cannot_replace_owned_exchange_evidence(field, value):
    order = {
        "symbol": "SOLUSDT",
        "side": "BUY",
        "quantity": "1",
        "price": "100",
        "reduce_only": False,
        "state": "PARTIALLY_FILLED",
        "exchange": {"executedQty": "0.2"},
    }
    response = {
        "symbol": "SOLUSDT",
        "side": "BUY",
        "clientOrderId": "owned",
        "origQty": "1",
        "price": "100",
        "reduceOnly": False,
        "orderId": 9,
        "executedQty": "0.2",
        "status": "PARTIALLY_FILLED",
    }
    with pytest.raises(ValueError):
        LiveOrderBook.apply_response(order, "owned", {**response, field: value})
    assert order["exchange"] == {"executedQty": "0.2"}
    assert order["state"] == "PARTIALLY_FILLED"
