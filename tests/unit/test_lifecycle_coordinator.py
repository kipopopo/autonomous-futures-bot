import asyncio
import hashlib
import time
from unittest.mock import AsyncMock

import pytest
from test_production_remediation import account_data
from test_protective_lifecycle import FILTERS, PLAN

from autonomous_futures.execution.account_evidence import atomic_json
from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway
from autonomous_futures.execution.exit_invalidation import ExitObservation
from autonomous_futures.execution.lifecycle_coordinator import LifecycleCoordinator
from autonomous_futures.execution.protective_lifecycle import prearm_actions
from autonomous_futures.execution.writer_lease import ExecutionLease


@pytest.fixture(name="held_execution_lease")
def execution_lease_fixture(tmp_path):
    lease = ExecutionLease(tmp_path / "execution.lock")
    lease.acquire()
    yield lease
    lease.close()


@pytest.mark.parametrize("exit_mode", ["none", "invalidated", "unavailable"])
def test_restart_recovers_first_fill_and_keeps_stop_while_creating_two_targets(
    tmp_path, held_execution_lease, exit_mode
):
    now = int(time.time() * 1000)
    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.symbol_specs = {
        PLAN.symbol: {
            "tick_size": FILTERS.tick_size,
            "step_size": FILTERS.step_size,
            "min_qty": FILTERS.min_qty,
            "max_qty": FILTERS.max_qty,
            "min_notional": FILTERS.min_notional,
        }
    }

    async def create(**request):
        return {
            "symbol": request["symbol"],
            "side": request["side"],
            "clientOrderId": request["client_order_id"],
            "orderId": 2,
            "type": request["order_type"],
            "status": "NEW",
            "reduceOnly": request["reduce_only"],
            "origQty": str(request["quantity"]),
            "executedQty": "0",
            "price": str(request.get("price") or 0),
            "stopPrice": str(request.get("stop_price") or 0),
        }

    gateway.create_order = AsyncMock(side_effect=create)
    entry_id = "afbot-" + hashlib.sha256(PLAN.signal_key.encode()).hexdigest()[:30]
    entry_response = {
        "symbol": PLAN.symbol,
        "side": "BUY",
        "clientOrderId": entry_id,
        "orderId": 1,
        "status": "FILLED",
        "origQty": "2",
        "executedQty": "2",
        "price": "100",
        "reduceOnly": False,
    }
    atomic_json(
        tmp_path / "exchange-orders.json",
        {
            entry_id: {
                "symbol": PLAN.symbol,
                "side": "BUY",
                "price": "100",
                "quantity": "2",
                "reduce_only": False,
                "signal_id": PLAN.signal_key,
                "timestamp_ms": now - 3000,
                "state": "FILLED",
                "exchange": entry_response,
            }
        },
    )
    coordinator = LifecycleCoordinator(gateway, tmp_path, lease=held_execution_lease)
    coordinator.register_entry(PLAN, entry_id)
    stop_action = prearm_actions(PLAN, FILTERS)[0]
    asyncio.run(coordinator.protective.execute(PLAN, stop_action))
    stop_response = dict(
        coordinator.protective.records["PLACE:" + stop_action.client_id]["exchange"]
    )
    gateway.get_order = AsyncMock(return_value=stop_response)
    first_offset, second_offset = (2500, 1500) if exit_mode == "none" else (70000, 69000)
    rows = [
        {
            "id": i,
            "orderId": 1,
            "symbol": PLAN.symbol,
            "side": "BUY",
            "positionSide": "BOTH",
            "commissionAsset": "USDT",
            "qty": "1",
            "price": "100",
            "quoteQty": "100",
            "commission": ".02",
            "realizedPnl": "0",
            "time": now - offset,
        }
        for i, offset in ((1, first_offset), (2, second_offset))
    ]
    gateway.get_order_fills = AsyncMock(return_value=rows)
    data = account_data()
    data["account"].update(
        totalWalletBalance="1000",
        totalMarginBalance="1000",
        availableBalance="800",
        totalInitialMargin="200",
    )
    data["reconciliation"].update(starting_equity="1000", net_realized_pnl="0")
    data["daily_risk"].update(day_start_equity="1000", limit_usdt="50", remaining_usdt="50")
    data["positions"] = [
        {
            "symbol": PLAN.symbol,
            "positionAmt": "2",
            "markPrice": "100",
            "entryPrice": "100",
            "unRealizedProfit": "0",
        }
    ]
    atomic_json(tmp_path / "exchange-account.json", data)
    if exit_mode != "none":
        from decimal import Decimal

        coordinator.exit_reader = AsyncMock()
        if exit_mode == "invalidated":
            coordinator.exit_reader.read.return_value = ExitObservation(
                PLAN.symbol, now // 60000 * 60000, Decimal("99")
            )
        else:
            coordinator.exit_reader.read.side_effect = TimeoutError("sensitive transport URL")
    assert asyncio.run(coordinator.advance(data["timestamp_ms"])) == ()
    trade = coordinator.trades[PLAN.signal_key]
    assert trade["first_fill_ms"] == now - first_offset
    assert trade["fill_summaries"][entry_id]["commission_usdt"] == "0.04"
    expected_types = (
        ["STOP_MARKET", "LIMIT", "LIMIT"] if exit_mode == "none" else ["STOP_MARKET", "MARKET"]
    )
    assert [
        call.kwargs["order_type"] for call in gateway.create_order.call_args_list
    ] == expected_types
    if exit_mode != "none":
        assert trade["exit_observation"]["invalidated"]
        assert "sensitive" not in str(trade["exit_observation"])
        assert gateway.create_order.call_args.kwargs["reduce_only"]
        assert gateway.create_order.call_args.kwargs["quantity"] == 2
    restarted = LifecycleCoordinator(gateway, tmp_path, lease=held_execution_lease)
    assert restarted.trades[PLAN.signal_key]["first_fill_ms"] == now - first_offset
    assert not restarted.trades[PLAN.signal_key]["closed"]


def test_entry_query_outage_does_not_skip_other_lifecycle_cleanup(tmp_path, held_execution_lease):
    from dataclasses import replace

    now = int(time.time() * 1000)
    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.get_order = AsyncMock(side_effect=TimeoutError("sensitive signed URL"))
    coordinator = LifecycleCoordinator(gateway, tmp_path, lease=held_execution_lease)
    first_id = coordinator.prepare(PLAN, now)
    coordinator.entries.orders[first_id] = {
        "symbol": PLAN.symbol,
        "state": "UNKNOWN",
    }
    second = replace(PLAN, symbol="ETHUSDT", signal_key="independent-prepared-fixture")
    coordinator.prepare(second, now)
    data = account_data()
    atomic_json(tmp_path / "exchange-account.json", data)
    assert asyncio.run(coordinator.advance(data["timestamp_ms"])) == (PLAN.signal_key,)
    assert coordinator.entries.orders[first_id]["state"] == "UNKNOWN"
    assert coordinator.entries.orders[first_id]["error_type"] == "TimeoutError"
    assert "sensitive" not in coordinator.trades[PLAN.signal_key]["recovery_error"]
    assert not coordinator.trades[PLAN.signal_key]["closed"]
    assert coordinator.trades[second.signal_key]["closed"]


def test_order_query_outage_does_not_skip_later_order_reconciliation(
    tmp_path, held_execution_lease
):
    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.get_order = AsyncMock(
        side_effect=[
            TimeoutError(),
            {
                "status": "CANCELED",
                "symbol": "ETHUSDT",
                "side": "BUY",
                "clientOrderId": "second",
                "origQty": "1",
                "price": "100",
                "reduceOnly": False,
                "orderId": 2,
                "executedQty": "0",
            },
        ]
    )
    coordinator = LifecycleCoordinator(gateway, tmp_path, lease=held_execution_lease)
    coordinator.entries.orders = {
        "first": {"symbol": "SOLUSDT", "state": "UNKNOWN"},
        "second": {
            "symbol": "ETHUSDT",
            "state": "UNKNOWN",
            "side": "BUY",
            "quantity": "1",
            "price": "100",
            "reduce_only": False,
        },
    }
    assert asyncio.run(coordinator.entries.reconcile()) == ("first",)
    assert coordinator.entries.orders["second"]["state"] == "CANCELED"
    assert gateway.get_order.await_count == 2


def test_unresolved_orphan_protective_command_blocks_new_entries(tmp_path, held_execution_lease):
    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.get_order = AsyncMock(side_effect=TimeoutError())
    coordinator = LifecycleCoordinator(gateway, tmp_path, lease=held_execution_lease)
    coordinator.protective.records["PLACE:orphaned-protection"] = {
        "request": {
            "client_id": "orphaned-protection",
            "plan_key": "missing-trade-journal",
            "symbol": PLAN.symbol,
            "role": "TP1",
            "operation": "PLACE",
            "order_type": "LIMIT",
            "quantity": "1",
            "price": "100",
            "side": "SELL",
            "reduce_only": True,
        },
        "state": "UNKNOWN",
    }
    data = account_data()
    atomic_json(tmp_path / "exchange-account.json", data)

    assert asyncio.run(coordinator.advance(data["timestamp_ms"])) == (
        "protective:PLACE:orphaned-protection",
    )
    assert coordinator.protective.records["PLACE:orphaned-protection"]["state"] == "UNKNOWN"
