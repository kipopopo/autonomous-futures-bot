import asyncio
from dataclasses import replace
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from test_protective_lifecycle import FILTERS, PLAN

from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway
from autonomous_futures.execution.protective_executor import ProtectiveExecutor
from autonomous_futures.execution.protective_lifecycle import ProtectiveAction, prearm_actions
from autonomous_futures.execution.writer_lease import ExecutionLease


@pytest.fixture
def held_lease(tmp_path):
    lease = ExecutionLease(tmp_path / "execution.lock")
    lease.acquire()
    yield lease
    lease.close()


def response(action):
    return {
        "symbol": PLAN.symbol,
        "clientOrderId": action.client_id,
        "orderId": 1,
        "side": action.side,
        "type": "STOP_MARKET",
        "stopPrice": str(action.price),
        "status": "NEW",
        "reduceOnly": True,
        "origQty": str(action.quantity),
        "executedQty": "0",
    }


def test_stop_acknowledgement_is_durable_protection_not_a_fill(tmp_path, held_lease):
    gateway = BinanceFuturesGateway(offline_mode=False)
    action = prearm_actions(PLAN, FILTERS)[0]
    gateway.create_order = AsyncMock(return_value=response(action))
    executor = ProtectiveExecutor(gateway, tmp_path, lease=held_lease)
    record = asyncio.run(executor.execute(PLAN, action))
    assert record["state"] == "CONDITIONAL_NEW"
    assert record["exchange"]["executedQty"] == "0"
    restarted = ProtectiveExecutor(gateway, tmp_path, lease=held_lease)
    asyncio.run(restarted.execute(PLAN, action))
    assert gateway.create_order.await_count == 1
    assert gateway.create_order.call_args.kwargs["reduce_only"] is True


def test_unknown_submission_reconciles_without_resubmission(tmp_path, held_lease):
    gateway = BinanceFuturesGateway(offline_mode=False)
    action = prearm_actions(PLAN, FILTERS)[0]
    gateway.create_order = AsyncMock(side_effect=TimeoutError())
    executor = ProtectiveExecutor(gateway, tmp_path, lease=held_lease)
    with pytest.raises(TimeoutError):
        asyncio.run(executor.execute(PLAN, action))
    assert asyncio.run(executor.execute(PLAN, action))["state"] == "UNKNOWN"
    gateway.get_order = AsyncMock(return_value=response(action))
    assert asyncio.run(executor.reconcile()) == ()
    assert executor.records["PLACE:" + action.client_id]["state"] == "CONDITIONAL_NEW"
    assert gateway.create_order.await_count == 1


def test_unknown_cancellation_keeps_identity_when_late_fill_changes_remainder(tmp_path, held_lease):
    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.cancel_order = AsyncMock(side_effect=TimeoutError())
    executor = ProtectiveExecutor(gateway, tmp_path, lease=held_lease)
    action = ProtectiveAction(
        "owned-entry-fixture",
        "ENTRY",
        "CANCEL",
        "LIMIT",
        PLAN.side,
        Decimal("2"),
        PLAN.entry,
        False,
    )
    with pytest.raises(TimeoutError):
        asyncio.run(executor.execute(PLAN, action))
    late = replace(action, quantity=Decimal("1"))
    assert asyncio.run(executor.execute(PLAN, late))["state"] == "UNKNOWN"
    assert gateway.cancel_order.await_count == 1
    with pytest.raises(ValueError, match="identity collision"):
        asyncio.run(executor.execute(PLAN, replace(late, side="SELL")))


@pytest.mark.parametrize("mismatch", [None, "orderId", "side", "positionSide", "reduceOnly"])
def test_triggered_algo_follows_actual_child_and_does_not_invent_fill(mismatch):
    paths = []

    def transport(request):
        paths.append(request.url.path)
        if request.url.path.endswith("algoOrder"):
            return httpx.Response(
                200,
                json={
                    "symbol": "SOLUSDT",
                    "clientAlgoId": "owned-stop",
                    "algoStatus": "FINISHED",
                    "actualOrderId": "9",
                    "side": "SELL",
                    "reduceOnly": True,
                },
            )
        child = {
            "symbol": "SOLUSDT",
            "clientOrderId": "exchange-child",
            "status": "NEW",
            "executedQty": "0",
            "orderId": 9,
            "side": "SELL",
            "reduceOnly": True,
        }
        if mismatch is not None:
            child[mismatch] = {
                "orderId": 10,
                "side": "BUY",
                "positionSide": "SHORT",
                "reduceOnly": False,
            }[mismatch]
        return httpx.Response(200, json=child)

    gateway = BinanceFuturesGateway(mock_transport=httpx.MockTransport(transport))
    if mismatch is not None:
        with pytest.raises(ValueError, match="child identity mismatch"):
            asyncio.run(gateway.get_conditional_order("SOLUSDT", "owned-stop"))
        return
    result = asyncio.run(gateway.get_conditional_order("SOLUSDT", "owned-stop"))
    assert result["status"] == "NEW" and result["executedQty"] == "0"
    assert paths == ["/fapi/v1/algoOrder", "/fapi/v1/order"]


def test_finished_algo_without_child_fails_closed():
    gateway = BinanceFuturesGateway(
        mock_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "symbol": "SOLUSDT",
                    "clientAlgoId": "owned-stop",
                    "algoStatus": "FINISHED",
                    "actualOrderId": "",
                },
            )
        )
    )
    with pytest.raises(ValueError, match="no verifiable child"):
        asyncio.run(gateway.get_conditional_order("SOLUSDT", "owned-stop"))


def test_failed_intention_persistence_prevents_network_submission(tmp_path, held_lease):
    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.create_order = AsyncMock()
    executor = ProtectiveExecutor(gateway, tmp_path, lease=held_lease)

    def disk_failure():
        raise OSError("disk unavailable")

    executor.save = disk_failure
    with pytest.raises(OSError):
        asyncio.run(executor.execute(PLAN, prearm_actions(PLAN, FILTERS)[0]))
    assert gateway.create_order.await_count == 0


def test_conditional_cancel_success_code_is_followed_by_authenticated_status(tmp_path, held_lease):
    gateway = BinanceFuturesGateway(offline_mode=False)
    action = prearm_actions(PLAN, FILTERS)[0]
    gateway.cancel_order = AsyncMock(return_value={"code": 200, "msg": "success"})
    gateway.get_conditional_order = AsyncMock(
        return_value={**response(action), "status": "CANCELED"}
    )
    cancel = ProtectiveAction(
        action.client_id,
        "STOP",
        "CANCEL",
        "STOP_MARKET",
        action.side,
        action.quantity,
        action.price,
    )
    executor = ProtectiveExecutor(gateway, tmp_path, lease=held_lease)
    gateway.create_order = AsyncMock(return_value=response(action))
    asyncio.run(executor.execute(PLAN, action))
    result = asyncio.run(executor.execute(PLAN, cancel))
    assert result["state"] == "CANCELED"
    assert gateway.get_conditional_order.await_count == 1
    assert executor.records["PLACE:" + action.client_id]["state"] == "CANCELED"
    restarted = ProtectiveExecutor(gateway, tmp_path, lease=held_lease)
    gateway.get_order = AsyncMock(
        side_effect=AssertionError("Terminal cleanup must not be requeried")
    )
    assert asyncio.run(restarted.reconcile()) == ()
    gateway.get_order.assert_not_awaited()


@pytest.mark.parametrize(
    "field,value",
    [
        ("origQty", "99"),
        ("type", "LIMIT"),
        ("stopPrice", "999"),
        ("executedQty", "-1"),
        ("executedQty", "99"),
        ("status", "FINISHED"),
    ],
)
def test_invalid_protective_response_preserves_previous_evidence(
    tmp_path, held_lease, field, value
):
    gateway = BinanceFuturesGateway(offline_mode=False)
    action = prearm_actions(PLAN, FILTERS)[0]
    gateway.create_order = AsyncMock(return_value=response(action))
    executor = ProtectiveExecutor(gateway, tmp_path, lease=held_lease)
    record = asyncio.run(executor.execute(PLAN, action))
    original = dict(record["exchange"])
    with pytest.raises(ValueError):
        executor.apply_response(record, {**original, field: value})
    assert record["exchange"] == original
    assert record["state"] == "CONDITIONAL_NEW"


def test_triggered_child_stop_type_does_not_restore_untriggered_coverage(tmp_path, held_lease):
    gateway = BinanceFuturesGateway(offline_mode=False)
    action = prearm_actions(PLAN, FILTERS)[0]
    gateway.create_order = AsyncMock(return_value=response(action))
    executor = ProtectiveExecutor(gateway, tmp_path, lease=held_lease)
    record = asyncio.run(executor.execute(PLAN, action))
    child = {
        **response(action),
        "conditional": {
            "actualOrderId": "1",
            "orderType": "STOP_MARKET",
            "triggerPrice": str(action.price),
        },
    }
    executor.apply_response(record, child)
    assert record["state"] == "NEW"
