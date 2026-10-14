"""Persist and reconcile protective commands; this adapter cannot submit opening orders."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from autonomous_futures.execution.account_evidence import atomic_json, finite_decimal
from autonomous_futures.execution.binance_gateway import BinanceAPIError, BinanceFuturesGateway
from autonomous_futures.execution.protective_lifecycle import ACTIVE, TERMINAL, ProtectiveAction
from autonomous_futures.execution.trade_plan import TradePlan
from autonomous_futures.execution.writer_lease import ExecutionLease


class ProtectiveExecutor:
    def __init__(
        self, gateway: BinanceFuturesGateway, directory: Path, *, lease: ExecutionLease
    ) -> None:
        lease.assert_held()
        self.lease = lease
        self.gateway = gateway
        self.path = directory / "protective-orders.json"
        directory.mkdir(parents=True, exist_ok=True)
        self.records: dict[str, dict[str, Any]] = (
            json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        )
        self.lock = lease.io_lock

    def save(self) -> None:
        self.lease.assert_held()
        atomic_json(self.path, self.records, durable=True)

    async def execute(self, plan: TradePlan, action: ProtectiveAction) -> dict[str, Any]:
        async with self.lock:
            self.lease.assert_held()
            if self.gateway.offline_mode:
                raise ValueError("Protective execution requires an exchange gateway")
            if action.operation == "PLACE" and (not action.reduce_only or action.role == "ENTRY"):
                raise ValueError("Protective adapter cannot open or increase positions")
            if action.side == plan.side and action.operation == "PLACE":
                raise ValueError("Protective side does not oppose the trade")
            key = f"{action.operation}:{action.client_id}"
            request = {
                "client_id": action.client_id,
                "plan_key": plan.signal_key,
                "symbol": plan.symbol,
                "role": action.role,
                "operation": action.operation,
                "order_type": action.order_type,
                "quantity": str(action.quantity),
                "price": None if action.price is None else str(action.price),
                "side": action.side,
                "reduce_only": action.reduce_only,
            }
            if key in self.records:
                previous = self.records[key]["request"]
                compared = (
                    {
                        name: value
                        for name, value in previous.items()
                        if name not in {"quantity", "price"}
                    }
                    if action.operation == "CANCEL"
                    else previous
                )
                current = (
                    {
                        name: value
                        for name, value in request.items()
                        if name not in {"quantity", "price"}
                    }
                    if action.operation == "CANCEL"
                    else request
                )
                # Cancellation identifies an existing order, not a requested fill
                # amount. Late fills may change outstanding quantity while the
                # original cancellation is UNKNOWN; reconcile it without reposting.
                if compared != current:
                    raise ValueError("Durable protective command identity collision")
                return self.records[key]
            record: dict[str, Any] = {
                "request": request,
                "state": "SUBMITTING",
                "created_ms": int(time.time() * 1000),
            }
            self.records[key] = record
            self.save()
            try:
                if action.operation == "CANCEL":
                    response = await self.gateway.cancel_order(
                        plan.symbol, client_order_id=action.client_id
                    )
                    if "symbol" not in response or (
                        "status" not in response and "algoStatus" not in response
                    ):
                        response = (
                            await self.gateway.get_conditional_order(plan.symbol, action.client_id)
                            if action.role == "STOP"
                            else await self.gateway.get_order(
                                plan.symbol, client_order_id=action.client_id
                            )
                        )
                else:
                    response = await self.gateway.create_order(
                        symbol=plan.symbol,
                        side=action.side,
                        order_type=action.order_type,
                        quantity=action.quantity,
                        client_order_id=action.client_id,
                        price=action.price if action.order_type == "LIMIT" else None,
                        stop_price=action.price if action.order_type == "STOP_MARKET" else None,
                        reduce_only=True,
                        time_in_force="GTC",
                    )
                self.adopt_response(record, response)
            except Exception as exc:
                record["state"] = "UNKNOWN"
                record["error_type"] = type(exc).__name__
                self.save()
                raise
            self.save()
            return record

    @staticmethod
    def apply_response(record: dict[str, Any], response: dict[str, Any]) -> None:
        request = record["request"]
        if response.get("symbol") != request["symbol"]:
            raise ValueError("Protective exchange symbol mismatch")
        identity = response.get("clientOrderId", response.get("clientAlgoId"))
        if identity != request["client_id"]:
            raise ValueError("Protective exchange client identity mismatch")
        if request["operation"] == "PLACE" and response.get("side") != request["side"]:
            raise ValueError("Protective exchange side mismatch")
        if request["operation"] == "PLACE" and response.get("reduceOnly") not in (True, "true"):
            raise ValueError("Exchange did not confirm reduce-only protection")
        if request["operation"] == "PLACE":
            conditional = response.get("conditional")
            exchange_order = conditional if isinstance(conditional, dict) else response
            exchange_type = exchange_order.get("orderType", exchange_order.get("type"))
            if exchange_type != request["order_type"]:
                raise ValueError("Protective exchange order type differs from intention")
            if request["order_type"] in {"LIMIT", "STOP_MARKET"}:
                price_field = "triggerPrice" if request["order_type"] == "STOP_MARKET" else "price"
                response_field = "stopPrice" if request["order_type"] == "STOP_MARKET" else "price"
                exchange_price = exchange_order.get(price_field, response.get(response_field))
                if exchange_price is None or finite_decimal(exchange_price) != finite_decimal(
                    request["price"]
                ):
                    raise ValueError("Protective exchange price differs from intention")
        status = response.get("status", response.get("algoStatus"))
        if (response.get("algoStatus") == "NEW" and not response.get("actualOrderId")) or (
            request["order_type"] == "STOP_MARKET"
            and status == "NEW"
            and response.get("type") == "STOP_MARKET"
            and not response.get("actualOrderId")
            and not response.get("conditional", {}).get("actualOrderId")
        ):
            status = "CONDITIONAL_NEW"
        if status is None:
            raise ValueError("Exchange response has no status")
        if status not in ACTIVE | TERMINAL:
            raise ValueError("Protective exchange status is unrecognized")
        quantity = finite_decimal(response.get("origQty", response.get("quantity")))
        if quantity <= 0 or (
            request["operation"] == "PLACE" and quantity != finite_decimal(request["quantity"])
        ):
            raise ValueError("Protective exchange quantity differs from intention")
        filled = finite_decimal(
            response.get("executedQty", "0")
            if status == "CONDITIONAL_NEW"
            else response["executedQty"]
        )
        prior = finite_decimal(record.get("exchange", {}).get("executedQty", "0"))
        if not prior <= filled <= quantity or (status == "CONDITIONAL_NEW" and filled != 0):
            raise ValueError("Protective exchange cumulative fills are invalid")
        record["exchange"] = response
        record["state"] = str(status)
        record["observed_ms"] = int(time.time() * 1000)

    def adopt_response(self, record: dict[str, Any], response: dict[str, Any]) -> None:
        self.apply_response(record, response)
        request = record["request"]
        if request["operation"] == "CANCEL" and record["state"] in TERMINAL:
            original = self.records.get("PLACE:" + request["client_id"])
            if original is not None:
                # The authenticated terminal response belongs to the same exchange
                # order. Preserve its actual cumulative fills on the PLACE record
                # so a subsequent not-found query cannot erase confirmed cleanup.
                self.apply_response(original, response)

    async def reconcile(self) -> tuple[str, ...]:
        """Resolve uncertain submissions by their original IDs without resubmitting."""
        unresolved = []
        async with self.lock:
            self.lease.assert_held()
            for key, record in self.records.items():
                if record["state"] in TERMINAL:
                    continue
                request = record["request"]
                identity = key.split(":", 1)[1]
                try:
                    if request["role"] == "STOP" and record.get("exchange", {}).get("algoId"):
                        response = await self.gateway.get_conditional_order(
                            request["symbol"], identity
                        )
                    else:
                        try:
                            response = await self.gateway.get_order(
                                request["symbol"], client_order_id=identity
                            )
                        except BinanceAPIError as exc:
                            if request["role"] != "STOP" or exc.code not in {-2013, -2011, -4120}:
                                raise
                            response = await self.gateway.get_conditional_order(
                                request["symbol"], identity
                            )
                    self.adopt_response(record, response)
                except Exception as exc:
                    record["state"] = "UNKNOWN"
                    record["error_type"] = type(exc).__name__
                    unresolved.append(key)
                self.save()
        return tuple(key for key in unresolved if self.records[key]["state"] not in TERMINAL)
