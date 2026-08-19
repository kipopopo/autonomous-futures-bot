"""Offline parser and reconciliation for one bounded testnet lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import Field, field_validator

from .domain.contracts import DomainModel


class TestnetOrderRecord(DomainModel):
    order_id: int = Field(ge=0, strict=True)
    client_order_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    status: str = Field(min_length=1)
    side: Literal["BUY", "SELL"]
    order_type: str = Field(min_length=1)
    original_quantity: Decimal
    executed_qty: Decimal
    reduce_only: bool
    update_time_ms: int = Field(ge=0, strict=True)

    @field_validator("original_quantity", "executed_qty")
    @classmethod
    def quantities_are_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0:
            raise ValueError("testnet order quantities must be finite and non-negative")
        return value


class TestnetLifecyclePosition(DomainModel):
    symbol: str = Field(min_length=1)
    position_side: Literal["BOTH", "LONG", "SHORT"]
    position_amt: Decimal

    @field_validator("position_amt")
    @classmethod
    def position_amount_is_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("testnet lifecycle position amount must be finite")
        return value


class TestnetLifecycleAudit(DomainModel):
    status: Literal["reconciled", "drift"]
    open_order_id: int
    close_order_id: int
    reason_codes: tuple[str, ...] = Field(min_length=1)
    live_enabled: Literal[False] = False


def _decimal(value: object, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid order {field_name}") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"invalid order {field_name}")
    return parsed


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"invalid order {field_name}")
    return value


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"invalid order {field_name}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"invalid order {field_name}") from exc
    raise ValueError(f"invalid order {field_name}")


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"invalid order {field_name}")
    return value


def _side(value: object) -> Literal["BUY", "SELL"]:
    if value == "BUY":
        return "BUY"
    if value == "SELL":
        return "SELL"
    raise ValueError("invalid order side")


def parse_testnet_order_record(body: Mapping[str, object]) -> TestnetOrderRecord:
    try:
        return TestnetOrderRecord(
            order_id=_integer(body["orderId"], "order ID"),
            client_order_id=_text(body["clientOrderId"], "client order ID"),
            symbol=_text(body["symbol"], "symbol"),
            status=_text(body["status"], "status"),
            side=_side(body["side"]),
            order_type=_text(body["type"], "type"),
            original_quantity=_decimal(body["origQty"], "original quantity"),
            executed_qty=_decimal(body["executedQty"], "executed quantity"),
            reduce_only=_boolean(body["reduceOnly"], "reduce-only"),
            update_time_ms=_integer(body["updateTime"], "update time"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("malformed testnet order response") from exc


def reconcile_testnet_lifecycle(
    open_order: TestnetOrderRecord,
    close_order: TestnetOrderRecord,
    pre_open_positions: tuple[TestnetLifecyclePosition, ...],
    post_close_positions: tuple[TestnetLifecyclePosition, ...],
) -> TestnetLifecycleAudit:
    reasons: list[str] = []
    if pre_open_positions:
        reasons.append("pre_open_position_not_flat")
    if open_order.status != "FILLED":
        reasons.append("open_order_not_filled")
    if close_order.status != "FILLED":
        reasons.append("close_order_not_filled")
    if open_order.side != "BUY":
        reasons.append("open_order_side_invalid")
    if close_order.side != "SELL":
        reasons.append("close_order_side_invalid")
    if not close_order.reduce_only:
        reasons.append("close_order_not_reduce_only")
    if open_order.symbol != close_order.symbol:
        reasons.append("lifecycle_symbol_mismatch")
    if open_order.executed_qty != close_order.executed_qty:
        reasons.append("lifecycle_quantity_mismatch")
    if open_order.executed_qty <= 0 or close_order.executed_qty <= 0:
        reasons.append("lifecycle_zero_execution")
    if post_close_positions:
        reasons.append("post_close_position_not_flat")
    return TestnetLifecycleAudit(
        status="drift" if reasons else "reconciled",
        open_order_id=open_order.order_id,
        close_order_id=close_order.order_id,
        reason_codes=tuple(sorted(reasons)) if reasons else ("testnet_lifecycle_reconciled",),
    )
