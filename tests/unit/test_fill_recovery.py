import asyncio
from decimal import Decimal as D
from unittest.mock import AsyncMock

import pytest

from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway
from autonomous_futures.execution.fill_recovery import summarize_fills


def fill(identity, when, qty, commission):
    return {
        "id": identity,
        "time": when,
        "symbol": "SOLUSDT",
        "orderId": 5,
        "side": "BUY",
        "positionSide": "BOTH",
        "commissionAsset": "USDT",
        "qty": qty,
        "price": "100",
        "quoteQty": str(D(qty) * 100),
        "commission": commission,
        "realizedPnl": "0",
    }


def test_first_fill_does_not_reset_at_last_partial_fill_or_restart():
    rows = [fill(2, 2000, ".2", ".004"), fill(1, 1000, ".1", ".002")]
    summary = summarize_fills(
        rows, symbol="SOLUSDT", order_id=5, side="BUY", executed_quantity=D(".3")
    )
    assert summary.first_fill_ms == 1000
    assert summary.last_fill_ms == 2000
    assert summary.commission_usdt == D(".006")
    assert summary.trade_ids == (1, 2)


def test_duplicate_missing_or_foreign_fills_do_not_become_recovered_balance():
    row = fill(1, 1000, ".1", ".002")
    for rows, quantity in [
        ([row, row], D(".2")),
        ([row], D(".3")),
        ([{**row, "side": "SELL"}], D(".1")),
    ]:
        with pytest.raises(ValueError):
            summarize_fills(
                rows, symbol="SOLUSDT", order_id=5, side="BUY", executed_quantity=quantity
            )


def test_gateway_recovers_more_than_one_thousand_actual_fill_records():
    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.signed_get = AsyncMock(
        side_effect=[
            [fill(i, 1000, ".1", ".002") for i in range(1000)],
            [fill(1000, 2000, ".1", ".002")],
        ]
    )
    rows = asyncio.run(gateway.get_order_fills("SOLUSDT", 5, 1000, 2000))
    assert len(rows) == 1001
    params = gateway.signed_get.call_args_list[1].args[1]
    assert params["fromId"] == 1000
    assert "startTime" not in params and "endTime" not in params


def test_non_advancing_pagination_never_becomes_complete_recovery():
    gateway = BinanceFuturesGateway(offline_mode=False)
    page = [fill(i, 1000, ".1", ".002") for i in range(1000)]
    gateway.signed_get = AsyncMock(side_effect=[page, page])
    with pytest.raises(ValueError, match="pagination"):
        asyncio.run(gateway.get_order_fills("SOLUSDT", 5, 1000, 2000))
