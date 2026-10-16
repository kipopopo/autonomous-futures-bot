"""Durable, minimal evidence for authenticated exchange user-stream events."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from autonomous_futures.execution.writer_lease import ExecutionLease

SCHEMA = "exchange-user-event-evidence-v1"


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _safe_value(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def _first_present(source: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in source:
            return source[name]
    return None


def _normalized_order(event: dict[str, Any]) -> dict[str, Any] | None:
    order = event.get("o")
    if not isinstance(order, dict):
        return None
    fields = {
        "symbol": ("s", "symbol"),
        "order_id": ("i", "orderId", "algoId"),
        "client_order_id": ("c", "clientOrderId", "clientAlgoId"),
        "side": ("S", "side"),
        "order_type": ("o", "type", "orderType"),
        "execution_type": ("x", "executionType"),
        "status": ("X", "status", "algoStatus", "actualOrderStatus"),
        "original_quantity": ("q", "origQty", "quantity"),
        "cumulative_filled_quantity": ("z", "executedQty"),
        "last_filled_quantity": ("l",),
        "last_filled_price": ("L",),
        "average_filled_price": ("ap",),
        "reduce_only": ("R", "reduceOnly"),
        "trigger_price": ("sp", "triggerPrice"),
        "actual_order_id": ("actualOrderId",),
    }
    result = {
        target: value
        for target, names in fields.items()
        if (value := _safe_value(_first_present(order, *names))) is not None
    }
    return result or None


def verify_execution_event_evidence(path: Path) -> dict[str, Any]:
    """Verify an event ledger read-only and return its evidence coverage summary."""
    record_count = 0
    previous_hash = None
    record_types: Counter[str] = Counter()
    event_types: Counter[str] = Counter()
    with path.open("rb") as records:
        for line in records:
            if not line.endswith(b"\n"):
                raise ValueError("Execution event evidence journal has a truncated record")
            try:
                record = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Execution event evidence journal is malformed") from exc
            if not isinstance(record, dict) or record.get("schema") != SCHEMA:
                raise ValueError("Execution event evidence journal has an unsupported record")
            declared_hash = record.pop("record_sha256", None)
            context = record.get("execution_context")
            if (
                record.get("sequence") != record_count + 1
                or record.get("previous_record_sha256") != previous_hash
                or not isinstance(context, dict)
                or record.get("execution_context_sha256")
                != hashlib.sha256(_canonical_json(context)).hexdigest()
            ):
                raise ValueError(
                    "Execution event evidence journal sequence, context, or chain is invalid"
                )
            actual_hash = hashlib.sha256(_canonical_json(record)).hexdigest()
            if declared_hash != actual_hash:
                raise ValueError("Execution event evidence journal hash mismatch")
            record_type = record.get("record_type")
            if record_type not in {"user_event", "stream_disconnect", "rest_reconciliation"}:
                raise ValueError("Execution event evidence journal has an unknown record type")
            record_types[record_type] += 1
            if record_type == "user_event":
                event_type = record.get("event_type")
                payload_hash = record.get("event_payload_sha256")
                if not isinstance(event_type, str) or not isinstance(payload_hash, str):
                    raise ValueError("Execution event evidence record is missing its event digest")
                if len(payload_hash) != 64 or any(
                    char not in "0123456789abcdef" for char in payload_hash
                ):
                    raise ValueError("Execution event evidence record has an invalid event digest")
                event_types[event_type] += 1
            record_count += 1
            previous_hash = actual_hash
    return {
        "schema": SCHEMA,
        "valid": True,
        "record_count": record_count,
        "head_sha256": previous_hash,
        "record_types": dict(sorted(record_types.items())),
        "event_types": dict(sorted(event_types.items())),
    }


class ExecutionEventEvidenceLedger:
    """Append minimal event records and REST reconciliation checkpoints.

    The local SHA-256 chain detects accidental or unsophisticated edits. It is not
    an exchange signature or an externally anchored tamper-proof audit service.
    """

    def __init__(
        self,
        directory: Path,
        *,
        lease: ExecutionLease,
        execution_context: dict[str, Any] | None = None,
    ) -> None:
        lease.assert_held()
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "exchange-user-events.jsonl"
        self.account_path = directory / "exchange-account.json"
        self.journal_paths = {
            "entry_orders": directory / "exchange-orders.json",
            "protective_orders": directory / "protective-orders.json",
            "owned_trades": directory / "owned-trades.json",
        }
        self.lease = lease
        self.execution_context = json.loads(_canonical_json(execution_context or {}))
        self.context_sha256 = hashlib.sha256(_canonical_json(self.execution_context)).hexdigest()
        self.runtime_session_id = uuid.uuid4().hex
        self._lock = threading.Lock()
        self.record_count, self.head_sha256 = self._verify_existing_chain()

    def _verify_existing_chain(self) -> tuple[int, str | None]:
        if not self.path.exists():
            return 0, None
        summary = verify_execution_event_evidence(self.path)
        return int(summary["record_count"]), summary["head_sha256"]

    def _append(self, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.lease.assert_held()
            record = {
                "schema": SCHEMA,
                "sequence": self.record_count + 1,
                "previous_record_sha256": self.head_sha256,
                "runtime_session_id": self.runtime_session_id,
                "execution_context_sha256": self.context_sha256,
                "execution_context": self.execution_context,
                **body,
            }
            record_hash = hashlib.sha256(_canonical_json(record)).hexdigest()
            record["record_sha256"] = record_hash
            line = _canonical_json(record) + b"\n"
            with self.path.open("ab") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
            self.record_count += 1
            self.head_sha256 = record_hash
            return record

    def _account_snapshot(self, now_ms: int) -> dict[str, Any]:
        try:
            raw = self.account_path.read_bytes()
        except OSError:
            return {"available": False, "path": self.account_path.name}
        snapshot_hash = hashlib.sha256(raw).hexdigest()
        try:
            snapshot = json.loads(raw)
        except UnicodeDecodeError, json.JSONDecodeError:
            return {
                "available": True,
                "path": self.account_path.name,
                "sha256": snapshot_hash,
                "parseable": False,
            }
        if not isinstance(snapshot, dict):
            return {
                "available": True,
                "path": self.account_path.name,
                "sha256": snapshot_hash,
                "parseable": False,
            }
        reconciliation = snapshot.get("reconciliation")
        reconciliation = reconciliation if isinstance(reconciliation, dict) else {}
        daily_risk = snapshot.get("daily_risk")
        daily_risk = daily_risk if isinstance(daily_risk, dict) else {}
        timestamp = snapshot.get("timestamp_ms")
        age_ms = now_ms - timestamp if type(timestamp) is int else None
        positions = snapshot.get("positions")
        orders = snapshot.get("open_orders")
        safe_positions = []
        if isinstance(positions, list):
            for row in positions:
                if not isinstance(row, dict):
                    continue
                safe_positions.append(
                    {
                        key: _safe_value(row.get(source))
                        for key, source in (
                            ("symbol", "symbol"),
                            ("position_side", "positionSide"),
                            ("position_amount", "positionAmt"),
                        )
                    }
                )
        safe_orders = []
        if isinstance(orders, list):
            for row in orders:
                if not isinstance(row, dict):
                    continue
                safe_orders.append(
                    {
                        target: _safe_value(_first_present(row, *names))
                        for target, names in (
                            ("symbol", ("symbol",)),
                            ("order_id", ("orderId", "algoId")),
                            ("client_order_id", ("clientOrderId", "clientAlgoId")),
                            ("status", ("status", "algoStatus")),
                            ("order_type", ("type", "orderType")),
                            ("original_quantity", ("origQty", "quantity")),
                            ("executed_quantity", ("executedQty",)),
                            ("reduce_only", ("reduceOnly",)),
                        )
                    }
                )
        return {
            "available": True,
            "parseable": True,
            "path": self.account_path.name,
            "sha256": snapshot_hash,
            "timestamp_ms": timestamp if type(timestamp) is int else None,
            "age_ms": age_ms,
            "source": _safe_value(snapshot.get("source")),
            "reconciliation_verified": reconciliation.get("verified") is True,
            "wallet_drift": _safe_value(reconciliation.get("wallet_drift")),
            "equity_drift": _safe_value(reconciliation.get("equity_drift")),
            "daily_risk_verified": daily_risk.get("verified") is True,
            "positions": safe_positions,
            "open_orders": safe_orders,
        }

    def _journal_hashes(self) -> dict[str, str | None]:
        result: dict[str, str | None] = {}
        for name, path in self.journal_paths.items():
            try:
                result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                result[name] = None
        return result

    def record_user_event(
        self,
        event: dict[str, Any],
        *,
        stream_connected: bool,
        stream_event_count: int,
        reconciliation_required: bool,
        received_at_ms: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(event, dict):
            raise ValueError("Authenticated user event must be a JSON object")
        event_type = event.get("e")
        if not isinstance(event_type, str) or not event_type:
            raise ValueError("Authenticated user event is missing its event type")
        received_at_ms = time.time_ns() // 1_000_000 if received_at_ms is None else received_at_ms
        return self._append(
            {
                "record_type": "user_event",
                "received_at_ms": received_at_ms,
                "source": (
                    "binance_authenticated_user_stream"
                    if stream_connected
                    else "runtime_callback_without_connected_stream"
                ),
                "stream_connected": stream_connected,
                "stream_event_count": stream_event_count,
                "stream_reconciliation_required": reconciliation_required,
                "event_type": event_type,
                "exchange_event_time_ms": _safe_value(_first_present(event, "E", "eventTime")),
                "exchange_transaction_time_ms": _safe_value(
                    _first_present(event, "T", "transactionTime")
                ),
                "event_payload_sha256": hashlib.sha256(_canonical_json(event)).hexdigest(),
                "order": _normalized_order(event),
                "account_snapshot": self._account_snapshot(received_at_ms),
            }
        )

    def record_stream_disconnect(
        self, *, stream_event_count: int, error_type: str | None, occurred_at_ms: int | None = None
    ) -> dict[str, Any]:
        occurred_at_ms = time.time_ns() // 1_000_000 if occurred_at_ms is None else occurred_at_ms
        return self._append(
            {
                "record_type": "stream_disconnect",
                "occurred_at_ms": occurred_at_ms,
                "source": "authenticated_user_stream_lifecycle",
                "stream_event_count": stream_event_count,
                "error_type": error_type,
                "account_snapshot": self._account_snapshot(occurred_at_ms),
            }
        )

    def record_rest_reconciliation(
        self,
        *,
        trigger: str,
        stream_connected: bool,
        stream_event_count: int,
        coordinator_errors: tuple[str, ...],
        completed_at_ms: int | None = None,
    ) -> dict[str, Any]:
        completed_at_ms = (
            time.time_ns() // 1_000_000 if completed_at_ms is None else completed_at_ms
        )
        return self._append(
            {
                "record_type": "rest_reconciliation",
                "trigger": trigger,
                "completed_at_ms": completed_at_ms,
                "stream_connected": stream_connected,
                "stream_event_count": stream_event_count,
                "rest_recovery_complete": not coordinator_errors,
                "unresolved_lifecycle_count": len(coordinator_errors),
                "unresolved_lifecycle_ids_sha256": (
                    hashlib.sha256(_canonical_json(sorted(coordinator_errors))).hexdigest()
                    if coordinator_errors
                    else None
                ),
                "account_snapshot": self._account_snapshot(completed_at_ms),
                "journal_sha256s": self._journal_hashes(),
            }
        )

    def health_summary(self) -> dict[str, Any]:
        return {
            "path": self.path.name,
            "record_count": self.record_count,
            "head_sha256": self.head_sha256,
            "execution_context_sha256": self.context_sha256,
            "runtime_session_id": self.runtime_session_id,
        }
