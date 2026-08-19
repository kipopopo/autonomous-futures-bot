from decimal import Decimal


def _open_order():
    return {
        "orderId": 28546535340,
        "clientOrderId": "afbot-open-1787102129611",
        "symbol": "BTCUSDT",
        "status": "FILLED",
        "side": "BUY",
        "type": "MARKET",
        "origQty": "0.0008",
        "executedQty": "0.0008",
        "reduceOnly": False,
        "updateTime": 1787102129612,
    }


def _close_order():
    return {
        "orderId": 28546535920,
        "clientOrderId": "afbot-recovery-close-1787102171616",
        "symbol": "BTCUSDT",
        "status": "FILLED",
        "side": "SELL",
        "type": "MARKET",
        "origQty": "0.0008",
        "executedQty": "0.0008",
        "reduceOnly": True,
        "updateTime": 1787102171617,
    }


def test_order_history_parser_and_lifecycle_reconciliation_pass() -> None:
    from autonomous_futures.testnet_lifecycle import (
        parse_testnet_order_record,
        reconcile_testnet_lifecycle,
    )

    open_order = parse_testnet_order_record(_open_order())
    close_order = parse_testnet_order_record(_close_order())
    audit = reconcile_testnet_lifecycle(open_order, close_order, (), ())

    assert open_order.executed_qty == Decimal("0.0008")
    assert close_order.reduce_only is True
    assert audit.status == "reconciled"
    assert audit.reason_codes == ("testnet_lifecycle_reconciled",)
    assert audit.live_enabled is False


def test_lifecycle_reconciliation_blocks_unfilled_or_position_drift() -> None:
    from autonomous_futures.testnet_lifecycle import (
        TestnetLifecyclePosition,
        parse_testnet_order_record,
        reconcile_testnet_lifecycle,
    )

    open_order = parse_testnet_order_record({**_open_order(), "status": "NEW"})
    close_order = parse_testnet_order_record(_close_order())
    audit = reconcile_testnet_lifecycle(
        open_order,
        close_order,
        (
            TestnetLifecyclePosition(
                symbol="BTCUSDT", position_side="BOTH", position_amt=Decimal("0.0008")
            ),
        ),
        (
            TestnetLifecyclePosition(
                symbol="BTCUSDT", position_side="BOTH", position_amt=Decimal("0.0008")
            ),
        ),
    )

    assert audit.status == "drift"
    assert "open_order_not_filled" in audit.reason_codes
    assert "post_close_position_not_flat" in audit.reason_codes
