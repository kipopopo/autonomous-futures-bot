import hashlib
import json
import time

import pytest

from autonomous_futures.execution.execution_event_evidence import (
    ExecutionEventEvidenceLedger,
    verify_execution_event_evidence,
)
from autonomous_futures.execution.writer_lease import ExecutionLease


def test_event_ledger_binds_normalized_order_to_source_and_account_snapshot(tmp_path):
    now_ms = time.time_ns() // 1_000_000
    lease = ExecutionLease(tmp_path / "writer.lock")
    lease.acquire()
    try:
        account_path = tmp_path / "exchange-account.json"
        snapshot = {
            "source": "binance_authenticated_rest",
            "timestamp_ms": now_ms,
            "account": {"totalWalletBalance": "secret-balance-fixture"},
            "reconciliation": {
                "verified": True,
                "wallet_drift": "0",
                "equity_drift": "0",
            },
            "daily_risk": {"verified": True},
            "positions": [{"symbol": "SOLUSDT", "positionSide": "BOTH", "positionAmt": "0.5"}],
            "open_orders": [
                {
                    "symbol": "SOLUSDT",
                    "orderId": 81,
                    "clientOrderId": "afbot-entry-fixture",
                    "status": "PARTIALLY_FILLED",
                    "type": "LIMIT",
                    "origQty": "1",
                    "executedQty": "0.5",
                    "reduceOnly": False,
                },
                {
                    "symbol": "SOLUSDT",
                    "algoId": 82,
                    "clientAlgoId": "afbot-stop-fixture",
                    "algoStatus": "NEW",
                    "orderType": "STOP_MARKET",
                    "quantity": "0.5",
                    "executedQty": "0",
                    "reduceOnly": True,
                },
            ],
        }
        account_path.write_text(json.dumps(snapshot), encoding="utf-8")
        context = {
            "environment": "testnet",
            "admission_manifest_sha256": "a" * 64,
            "candidates": [
                {
                    "portfolio_id": "portfolio-fixture",
                    "report_hash": "b" * 64,
                    "selection_hash": "c" * 64,
                    "implementation_hashes": {"src/strategy.py": "d" * 64},
                }
            ],
        }
        ledger = ExecutionEventEvidenceLedger(tmp_path, lease=lease, execution_context=context)
        event = {
            "e": "ORDER_TRADE_UPDATE",
            "E": now_ms,
            "T": now_ms,
            "o": {
                "s": "SOLUSDT",
                "c": "afbot-entry-fixture",
                "i": 81,
                "S": "BUY",
                "o": "LIMIT",
                "x": "TRADE",
                "X": "PARTIALLY_FILLED",
                "q": "1",
                "z": "0.5",
                "l": "0.5",
                "L": "100",
                "R": False,
            },
            "test_only_private_field": "never-write-this-value",
        }
        event_record = ledger.record_user_event(
            event,
            stream_connected=True,
            stream_event_count=1,
            reconciliation_required=True,
            received_at_ms=now_ms,
        )
        stop_event = ledger.record_user_event(
            {
                "e": "ALGO_UPDATE",
                "E": now_ms + 1,
                "o": {
                    "s": "SOLUSDT",
                    "algoId": 82,
                    "clientAlgoId": "afbot-stop-fixture",
                    "S": "SELL",
                    "o": "STOP_MARKET",
                    "algoStatus": "NEW",
                    "quantity": "0.5",
                    "triggerPrice": "90",
                    "reduceOnly": True,
                    "actualOrderId": 9001,
                },
            },
            stream_connected=True,
            stream_event_count=2,
            reconciliation_required=True,
            received_at_ms=now_ms + 1,
        )
        reconciliation = ledger.record_rest_reconciliation(
            trigger="user_stream_event_batch",
            stream_connected=True,
            stream_event_count=2,
            coordinator_errors=(),
            completed_at_ms=now_ms,
        )

        assert event_record["source"] == "binance_authenticated_user_stream"
        assert event_record["order"] == {
            "symbol": "SOLUSDT",
            "order_id": 81,
            "client_order_id": "afbot-entry-fixture",
            "side": "BUY",
            "order_type": "LIMIT",
            "execution_type": "TRADE",
            "status": "PARTIALLY_FILLED",
            "original_quantity": "1",
            "cumulative_filled_quantity": "0.5",
            "last_filled_quantity": "0.5",
            "last_filled_price": "100",
            "reduce_only": False,
        }
        assert (
            event_record["event_payload_sha256"]
            == hashlib.sha256(
                json.dumps(
                    event, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest()
        )
        assert stop_event["event_type"] == "ALGO_UPDATE"
        assert stop_event["order"]["status"] == "NEW"
        assert stop_event["order"]["reduce_only"] is True
        assert stop_event["order"]["actual_order_id"] == 9001
        assert reconciliation["rest_recovery_complete"] is True
        assert reconciliation["account_snapshot"]["reconciliation_verified"] is True
        assert reconciliation["account_snapshot"]["positions"] == [
            {"symbol": "SOLUSDT", "position_side": "BOTH", "position_amount": "0.5"}
        ]
        assert reconciliation["account_snapshot"]["open_orders"][0]["executed_quantity"] == "0.5"
        assert reconciliation["account_snapshot"]["open_orders"][1]["reduce_only"] is True

        journal_bytes = ledger.path.read_bytes()
        assert b"never-write-this-value" not in journal_bytes
        assert b"secret-balance-fixture" not in journal_bytes
        assert ledger.health_summary()["record_count"] == 3
        reopened = ExecutionEventEvidenceLedger(tmp_path, lease=lease, execution_context=context)
        assert reopened.record_count == 3
        assert reopened.head_sha256 == ledger.head_sha256
        verification = verify_execution_event_evidence(ledger.path)
        assert verification["valid"] is True
        assert verification["record_count"] == 3
        assert verification["event_types"] == {
            "ALGO_UPDATE": 1,
            "ORDER_TRADE_UPDATE": 1,
        }

        ledger.path.write_bytes(journal_bytes.replace(b"PARTIALLY_FILLED", b"FILLED"))
        with pytest.raises(ValueError, match="hash mismatch"):
            ExecutionEventEvidenceLedger(tmp_path, lease=lease, execution_context=context)
        with pytest.raises(ValueError, match="hash mismatch"):
            verify_execution_event_evidence(ledger.path)
    finally:
        lease.close()
