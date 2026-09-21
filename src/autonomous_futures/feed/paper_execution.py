"""Phase 294: Micro Child Order Slicing & Passive Matching Engine.

Implements simulated micro child order slicing (strictly <= 5.00 USDT, ROUND_DOWN precision),
Binance exchange filter enforcement (LOT_SIZE, PRICE_FILTER, MIN_NOTIONAL), and passive
limit order matching simulation against live top-5 orderbook depth and aggregate trades.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from autonomous_futures.data.exchange_filters import (
    ExchangeSymbolFilters,
)
from autonomous_futures.domain.contracts import DomainModel
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.feed.models import (
    AggregateTrade,
    OrderBookDepthSnapshot,
)

# =====================================================================
# Constants & Micro Constraints (Phase 294)
# =====================================================================

HARD_MICRO_NOTIONAL_CAP_USDT: Decimal = Decimal("5.00")
NOMINAL_CHUNK_CAP_USDT: Decimal = Decimal("2.50")
THROTTLED_CHUNK_CAP_USDT: Decimal = Decimal("1.25")
MIN_MICRO_NOTIONAL_FLOOR_USDT: Decimal = Decimal("1.00")

DEFAULT_MAKER_FEE_RATE: Decimal = Decimal("0.0002")  # 0.02% maker fee
DEFAULT_TAKER_FEE_RATE: Decimal = Decimal("0.0004")  # 0.04% taker fee
DEFAULT_TAKER_SLIPPAGE_BPS: Decimal = Decimal("2.0")  # 2.0 bps slippage
DEFAULT_TAKER_SLIPPAGE_RATE: Decimal = Decimal("0.0002")

CANARY_STAGED_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


# =====================================================================
# Error Hierarchy
# =====================================================================


class PaperExecutionError(DomainViolation):
    """Base exception for paper execution and matching simulation operations."""


class IndividualMicroCapExceededError(PaperExecutionError):
    """Raised when a child order exceeds the strictly enforced 5.00 USDT micro notional cap."""


class MicroNotionalFloorViolationError(PaperExecutionError):
    """Raised when a child order notional falls below the minimal viable micro floor."""


class OrderSlicingError(PaperExecutionError):
    """Raised when parent order parameters fail mathematical slicing."""


class RestingOrderNotFoundError(PaperExecutionError):
    """Raised when referencing an unknown or already filled resting order."""


class PostOnlyViolationError(PaperExecutionError):
    """Raised when a post-only passive limit order would cross the prevailing book."""


# =====================================================================
# Domain Enums & Models
# =====================================================================


class OrderSide(StrEnum):
    """Execution side."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    """Execution type."""

    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(StrEnum):
    """Order lifecycle status."""

    NEW = "NEW"
    OPEN = "OPEN"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class TimeInForce(StrEnum):
    """Time in force policies."""

    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    POST_ONLY = "POST_ONLY"


class ParentOrderIntention(DomainModel):
    """High-level parent order to be sliced into micro child orders."""

    parent_order_id: str = Field(default="")
    parent_id: str = Field(default="")
    candidate_id: str | None = None
    symbol: str = Field(min_length=1, pattern=r"^[A-Z0-9]+$")
    side: OrderSide
    order_type: OrderType = OrderType.LIMIT
    target_notional_usdt: Decimal = Field(default=Decimal("0"))
    target_notional: Decimal = Field(default=Decimal("0"))
    limit_price: Decimal | None = None
    created_time_ms: int = Field(default=0)

    @model_validator(mode="before")
    @classmethod
    def _normalize_parent_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            p_id = data.get("parent_id") or data.get("parent_order_id") or ""
            data["parent_id"] = p_id
            data["parent_order_id"] = p_id
            notional = (
                data.get("target_notional")
                if data.get("target_notional") is not None
                else data.get("target_notional_usdt")
            )
            if notional is not None:
                data["target_notional"] = notional
                data["target_notional_usdt"] = notional
        return data


class ChildOrderIntention(DomainModel):
    """Micro child order produced by the slicing engine."""

    client_order_id: str = Field(default="")
    child_id: str = Field(default="")
    parent_order_id: str = Field(default="")
    parent_id: str = Field(default="")
    child_index: int = Field(default=0, ge=0)
    symbol: str = Field(min_length=1, pattern=r"^[A-Z0-9]+$")
    side: OrderSide
    order_type: OrderType = OrderType.LIMIT
    price: Decimal
    quantity: Decimal
    notional_usdt: Decimal = Field(default=Decimal("0"))
    notional: Decimal = Field(default=Decimal("0"))
    time_in_force: TimeInForce = TimeInForce.GTC
    status: OrderStatus = OrderStatus.NEW
    created_time_ms: int = Field(default=0)

    @model_validator(mode="before")
    @classmethod
    def _normalize_child_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            c_id = data.get("child_id") or data.get("client_order_id") or ""
            data["child_id"] = c_id
            data["client_order_id"] = c_id
            p_id = data.get("parent_id") or data.get("parent_order_id") or ""
            data["parent_id"] = p_id
            data["parent_order_id"] = p_id
            n = (
                data.get("notional")
                if data.get("notional") is not None
                else data.get("notional_usdt")
            )
            if n is not None:
                data["notional"] = n
                data["notional_usdt"] = n
        return data

    @model_validator(mode="after")
    def validate_micro_cap(self) -> ChildOrderIntention:
        if self.notional_usdt > HARD_MICRO_NOTIONAL_CAP_USDT:
            raise IndividualMicroCapExceededError(
                f"Child notional {self.notional_usdt} exceeds {HARD_MICRO_NOTIONAL_CAP_USDT} USDT"
            )
        return self


class OrderExecutionFill(DomainModel):
    """Execution fill record emitted by the matching simulator."""

    fill_id: str = Field(min_length=1)
    client_order_id: str = Field(default="")
    order_id: str = Field(default="")
    parent_order_id: str = Field(default="")
    child_index: int = Field(default=0, ge=0)
    symbol: str = Field(min_length=1, pattern=r"^[A-Z0-9]+$")
    side: OrderSide
    fill_price: Decimal
    fill_quantity: Decimal
    fill_notional_usdt: Decimal = Field(default=Decimal("0"))
    fill_notional: Decimal = Field(default=Decimal("0"))
    fee_usdt: Decimal = Field(default=Decimal("0"))
    fee: Decimal = Field(default=Decimal("0"))
    fee_rate: Decimal = DEFAULT_MAKER_FEE_RATE
    is_maker: bool = True
    slippage_bps: Decimal = Decimal("0")
    fill_time_ms: int = Field(default=0, ge=0)
    timestamp_ms: int = Field(default=0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def _normalize_fill_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            o_id = data.get("order_id") or data.get("client_order_id") or ""
            data["order_id"] = o_id
            data["client_order_id"] = o_id
            n = (
                data.get("fill_notional")
                if data.get("fill_notional") is not None
                else data.get("fill_notional_usdt")
            )
            if n is not None:
                data["fill_notional"] = n
                data["fill_notional_usdt"] = n
            f = data.get("fee") if data.get("fee") is not None else data.get("fee_usdt")
            if f is not None:
                data["fee"] = f
                data["fee_usdt"] = f
            t = (
                data.get("timestamp_ms")
                if data.get("timestamp_ms") is not None
                else data.get("fill_time_ms")
            )
            if t is not None:
                data["timestamp_ms"] = t
                data["fill_time_ms"] = t
        return data


class SimulatedRestingOrder:
    """Internal state of a resting limit order in the matching simulator queue."""

    def __init__(
        self,
        *,
        client_order_id: str,
        parent_order_id: str,
        child_index: int,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        limit_price: Decimal,
        quantity: Decimal,
        notional_usdt: Decimal,
        queue_ahead_qty: Decimal,
        created_time_ms: int,
        time_in_force: TimeInForce = TimeInForce.POST_ONLY,
    ) -> None:
        self.client_order_id = client_order_id
        self.parent_order_id = parent_order_id
        self.child_index = child_index
        self.symbol = symbol
        self.side = side
        self.order_type = order_type
        self.limit_price = limit_price
        self.quantity = quantity
        self.remaining_quantity = quantity
        self.notional_usdt = notional_usdt
        self.queue_ahead_qty = max(Decimal("0"), queue_ahead_qty)
        self.created_time_ms = created_time_ms
        self.time_in_force = time_in_force
        self.status = OrderStatus.NEW
        self.executed_quantity = Decimal("0")
        self.executed_notional = Decimal("0")
        self.total_fee_usdt = Decimal("0")

    @property
    def q_ahead(self) -> Decimal:
        return self.queue_ahead_qty

    @q_ahead.setter
    def q_ahead(self, val: Decimal) -> None:
        self.queue_ahead_qty = val

    @property
    def notional(self) -> Decimal:
        return self.notional_usdt

    @property
    def child_id(self) -> str:
        return self.client_order_id

    @property
    def parent_id(self) -> str:
        return self.parent_order_id

    @property
    def order_id(self) -> str:
        return self.client_order_id

    @property
    def is_active(self) -> bool:
        return self.status in (OrderStatus.NEW, OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)


# =====================================================================
# Default Canonical Exchange Filters
# =====================================================================


def get_default_exchange_filters() -> dict[str, ExchangeSymbolFilters]:
    """Provide canonical Binance USDⓈ-M perpetual exchange filters for staged symbols."""
    return {
        "BTCUSDT": ExchangeSymbolFilters(
            symbol="BTCUSDT",
            status="TRADING",
            contract_type="PERPETUAL",
            base_asset="BTC",
            quote_asset="USDT",
            settle_asset="USDT",
            price_min=Decimal("0.10"),
            price_max=Decimal("1000000.00"),
            price_tick_size=Decimal("0.10"),
            quantity_min=Decimal("0.00001"),
            quantity_max=Decimal("1000.00"),
            quantity_step_size=Decimal("0.00001"),
            market_quantity_min=Decimal("0.00001"),
            market_quantity_max=Decimal("1000.00"),
            market_quantity_step_size=Decimal("0.00001"),
            min_notional=Decimal("1.00"),
        ),
        "ETHUSDT": ExchangeSymbolFilters(
            symbol="ETHUSDT",
            status="TRADING",
            contract_type="PERPETUAL",
            base_asset="ETH",
            quote_asset="USDT",
            settle_asset="USDT",
            price_min=Decimal("0.01"),
            price_max=Decimal("1000000.00"),
            price_tick_size=Decimal("0.01"),
            quantity_min=Decimal("0.001"),
            quantity_max=Decimal("10000.00"),
            quantity_step_size=Decimal("0.001"),
            market_quantity_min=Decimal("0.001"),
            market_quantity_max=Decimal("10000.00"),
            market_quantity_step_size=Decimal("0.001"),
            min_notional=Decimal("5.00"),
        ),
        "SOLUSDT": ExchangeSymbolFilters(
            symbol="SOLUSDT",
            status="TRADING",
            contract_type="PERPETUAL",
            base_asset="SOL",
            quote_asset="USDT",
            settle_asset="USDT",
            price_min=Decimal("0.01"),
            price_max=Decimal("100000.00"),
            price_tick_size=Decimal("0.01"),
            quantity_min=Decimal("0.01"),
            quantity_max=Decimal("10000.00"),
            quantity_step_size=Decimal("0.01"),
            market_quantity_min=Decimal("0.01"),
            market_quantity_max=Decimal("10000.00"),
            market_quantity_step_size=Decimal("0.01"),
            min_notional=Decimal("5.00"),
        ),
    }


# =====================================================================
# Slicing Engine
# =====================================================================


def quantize_price(
    raw_price: Decimal,
    tick_size: Decimal,
    side: OrderSide,
) -> Decimal:
    """Align limit price to tickSize with conservative direction-aware rounding."""
    if tick_size <= 0:
        return raw_price
    rounding = ROUND_DOWN if side == OrderSide.BUY else ROUND_UP
    # Use integer multiples of tickSize
    steps = (raw_price / tick_size).to_integral_value(rounding=rounding)
    return steps * tick_size


def quantize_quantity(
    raw_quantity: Decimal,
    step_size: Decimal,
) -> Decimal:
    """Quantize quantity to exchange stepSize using strictly ROUND_DOWN."""
    if step_size <= 0:
        return raw_quantity
    steps = (raw_quantity / step_size).to_integral_value(rounding=ROUND_DOWN)
    return steps * step_size


def slice_parent_order(
    parent: ParentOrderIntention,
    filters: ExchangeSymbolFilters,
    reference_price: Decimal | None = None,
    chunk_cap_usdt: Decimal = NOMINAL_CHUNK_CAP_USDT,
    regime_chunk_cap: Decimal | None = None,
    min_notional_override: Decimal | None = None,
) -> list[ChildOrderIntention]:
    """Partition a parent order into micro child orders strictly <= 5.00 USDT."""
    if regime_chunk_cap is not None:
        chunk_cap_usdt = regime_chunk_cap

    effective_ref_price = (
        reference_price
        if reference_price is not None and reference_price > 0
        else (
            parent.limit_price
            if parent.limit_price is not None and parent.limit_price > 0
            else Decimal("1.0")
        )
    )

    target_notional = (
        parent.target_notional if parent.target_notional > 0 else parent.target_notional_usdt
    )
    if target_notional <= 0:
        raise ValueError("target_notional must be positive and finite")

    if target_notional < MIN_MICRO_NOTIONAL_FLOOR_USDT:
        raise MicroNotionalFloorViolationError(
            f"Parent target notional {target_notional} is below micro floor "
            f"{MIN_MICRO_NOTIONAL_FLOOR_USDT}"
        )

    effective_chunk_cap = min(HARD_MICRO_NOTIONAL_CAP_USDT, chunk_cap_usdt)
    if effective_chunk_cap <= Decimal("0"):
        raise OrderSlicingError(f"Invalid chunk cap: {effective_chunk_cap}")

    aligned_price = quantize_price(effective_ref_price, filters.price_tick_size, parent.side)
    if aligned_price <= Decimal("0"):
        raise OrderSlicingError(
            f"Aligned price {aligned_price} <= 0 for {parent.symbol} "
            f"(below tick size {filters.price_tick_size})"
        )

    # Number of chunks
    if target_notional <= effective_chunk_cap:
        chunk_notionals = [target_notional]
    else:
        num_chunks = max(1, math.ceil(float(target_notional / effective_chunk_cap)))
        chunk_notionals = []
        remaining = target_notional
        for _ in range(num_chunks - 1):
            chunk_notionals.append(effective_chunk_cap)
            remaining -= effective_chunk_cap
        chunk_notionals.append(remaining)

    child_orders: list[ChildOrderIntention] = []
    ts = parent.created_time_ms

    effective_step = filters.quantity_step_size
    effective_min_qty = filters.quantity_min

    for i, notional in enumerate(chunk_notionals):
        raw_qty = notional / aligned_price
        qty = quantize_quantity(raw_qty, effective_step)

        if qty < effective_min_qty:
            steps = (effective_min_qty / effective_step).to_integral_value(rounding=ROUND_UP)
            candidate_qty = steps * effective_step
            if candidate_qty * aligned_price <= HARD_MICRO_NOTIONAL_CAP_USDT:
                qty = candidate_qty
            else:
                continue

        if qty <= Decimal("0"):
            continue

        actual_notional = (qty * aligned_price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

        child_notional = min(notional, effective_chunk_cap)
        if actual_notional <= effective_chunk_cap and actual_notional > 0:
            child_notional = min(child_notional, actual_notional)

        if min_notional_override is not None and child_notional < min_notional_override:
            raise MicroNotionalFloorViolationError(
                f"Child notional {child_notional} below override floor {min_notional_override}"
            )

        if child_notional > HARD_MICRO_NOTIONAL_CAP_USDT:
            raise IndividualMicroCapExceededError(
                f"Child notional {child_notional} exceeds cap {HARD_MICRO_NOTIONAL_CAP_USDT}"
            )

        cid = f"{parent.parent_order_id}-slice-{i}" if parent.parent_order_id else f"c-slice-{i}"
        child = ChildOrderIntention(
            client_order_id=cid,
            child_id=cid,
            parent_order_id=parent.parent_order_id,
            parent_id=parent.parent_order_id,
            child_index=i,
            symbol=parent.symbol,
            side=parent.side,
            order_type=parent.order_type or OrderType.LIMIT,
            price=aligned_price,
            quantity=qty,
            notional_usdt=child_notional,
            notional=child_notional,
            time_in_force=TimeInForce.POST_ONLY,
            status=OrderStatus.NEW,
            created_time_ms=ts,
        )
        child_orders.append(child)

    return child_orders


# =====================================================================
# Passive Matching Simulator
# =====================================================================


class SimulatedPassiveMatchingEngine:
    """Matching engine that models book depth queues, trade arrival, and maker/taker fees."""

    def __init__(
        self,
        *,
        maker_fee_rate: Decimal = DEFAULT_MAKER_FEE_RATE,
        taker_fee_rate: Decimal = DEFAULT_TAKER_FEE_RATE,
        slippage_rate: Decimal = DEFAULT_TAKER_SLIPPAGE_RATE,
    ) -> None:
        self.maker_fee_rate = maker_fee_rate
        self.taker_fee_rate = taker_fee_rate
        self.slippage_rate = slippage_rate

        self._resting_orders: dict[str, SimulatedRestingOrder] = {}
        self._latest_depth: dict[str, OrderBookDepthSnapshot] = {}
        self._execution_fills: list[OrderExecutionFill] = []

    @property
    def execution_fills(self) -> Sequence[OrderExecutionFill]:
        return tuple(self._execution_fills)

    def update_depth(self, snapshot: OrderBookDepthSnapshot) -> None:
        """Cache latest depth snapshot for the symbol."""
        self._latest_depth[snapshot.symbol] = snapshot

    def get_latest_depth(self, symbol: str) -> OrderBookDepthSnapshot | None:
        return self._latest_depth.get(symbol)

    def place_limit_order(
        self,
        order: ChildOrderIntention,
        current_depth: OrderBookDepthSnapshot | None = None,
    ) -> SimulatedRestingOrder:
        """Place a post-only limit child order into the matching simulator queue."""
        if current_depth is not None:
            self.update_depth(current_depth)
        depth = current_depth if current_depth is not None else self._latest_depth.get(order.symbol)
        queue_ahead = Decimal("0")

        if depth and depth.bids and depth.asks:
            best_bid = depth.best_bid_price or (depth.bids[0].price if depth.bids else None)
            best_ask = depth.best_ask_price or (depth.asks[0].price if depth.asks else None)

            if order.side == OrderSide.BUY:
                if best_ask is not None and order.price > best_ask:
                    raise PostOnlyViolationError(
                        f"Post-only buy limit order price {order.price} crosses best ask {best_ask}"
                    )
                if best_bid is not None and order.price > best_bid:
                    queue_ahead = Decimal("0")
                else:
                    queue_ahead = sum(
                        (level.quantity for level in depth.bids if level.price >= order.price),
                        Decimal("0"),
                    )
            else:  # SELL
                if best_bid is not None and order.price < best_bid:
                    raise PostOnlyViolationError(
                        f"Post-only sell limit order price {order.price} crosses "
                        f"best bid {best_bid}"
                    )
                if best_ask is not None and order.price < best_ask:
                    queue_ahead = Decimal("0")
                else:
                    queue_ahead = sum(
                        (level.quantity for level in depth.asks if level.price <= order.price),
                        Decimal("0"),
                    )

        resting = SimulatedRestingOrder(
            client_order_id=order.client_order_id,
            parent_order_id=order.parent_order_id,
            child_index=order.child_index,
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            limit_price=order.price,
            quantity=order.quantity,
            notional_usdt=order.notional_usdt,
            queue_ahead_qty=queue_ahead,
            created_time_ms=order.created_time_ms,
            time_in_force=order.time_in_force,
        )
        self._resting_orders[order.client_order_id] = resting
        return resting

    def get_working_order(self, client_order_id: str) -> SimulatedRestingOrder | None:
        """Get an active working order in the queue; returns None if completed or cancelled."""
        order = self._resting_orders.get(client_order_id)
        if order is not None and order.is_active and order.status != OrderStatus.FILLED:
            return order
        return None

    def get_order(self, client_order_id: str) -> SimulatedRestingOrder | None:
        """Get order by ID regardless of working status."""
        return self._resting_orders.get(client_order_id)

    def place_order(
        self,
        child: ChildOrderIntention,
        current_depth: OrderBookDepthSnapshot | None = None,
    ) -> tuple[SimulatedRestingOrder, list[OrderExecutionFill]]:
        """Place a child order into the matching simulator."""
        depth = current_depth if current_depth is not None else self._latest_depth.get(child.symbol)
        fills: list[OrderExecutionFill] = []

        if child.order_type == OrderType.MARKET:
            best_bid = depth.best_bid_price if depth else None
            best_ask = depth.best_ask_price if depth else None
            fill_price = (
                best_ask
                if (child.side == OrderSide.BUY and best_ask)
                else (best_bid or child.price)
            )
            fill = self._create_fill(
                child=child,
                fill_price=fill_price,
                fill_qty=child.quantity,
                is_maker=False,
                slippage_rate=self.slippage_rate,
                fill_time_ms=child.created_time_ms,
            )
            fills.append(fill)
            resting = SimulatedRestingOrder(
                client_order_id=child.client_order_id,
                parent_order_id=child.parent_order_id,
                child_index=child.child_index,
                symbol=child.symbol,
                side=child.side,
                order_type=child.order_type,
                limit_price=child.price,
                quantity=child.quantity,
                notional_usdt=child.notional_usdt,
                queue_ahead_qty=Decimal("0"),
                created_time_ms=child.created_time_ms,
                time_in_force=child.time_in_force,
            )
            resting.status = OrderStatus.FILLED
            resting.executed_quantity = child.quantity
            resting.executed_notional = fill.fill_notional_usdt
            resting.total_fee_usdt = fill.fee_usdt
            self._resting_orders[child.client_order_id] = resting
            return resting, fills

        # For limit orders:
        try:
            resting = self.place_limit_order(child, depth)
            return resting, fills
        except PostOnlyViolationError:
            if child.time_in_force == TimeInForce.POST_ONLY:
                resting = SimulatedRestingOrder(
                    client_order_id=child.client_order_id,
                    parent_order_id=child.parent_order_id,
                    child_index=child.child_index,
                    symbol=child.symbol,
                    side=child.side,
                    order_type=child.order_type,
                    limit_price=child.price,
                    quantity=child.quantity,
                    notional_usdt=child.notional_usdt,
                    queue_ahead_qty=Decimal("0"),
                    created_time_ms=child.created_time_ms,
                    time_in_force=child.time_in_force,
                )
                resting.status = OrderStatus.CANCELLED
                self._resting_orders[child.client_order_id] = resting
                return resting, []

            # If crossed and placed via place_order with non-post-only, execute as aggressive taker
            fill_price = (
                (best_ask or child.price)
                if child.side == OrderSide.BUY
                else (best_bid or child.price)
            )
            fill = self._create_fill(
                child=child,
                fill_price=fill_price,
                fill_qty=child.quantity,
                is_maker=False,
                slippage_rate=self.slippage_rate,
                fill_time_ms=child.created_time_ms,
            )
            fills.append(fill)
            resting = SimulatedRestingOrder(
                client_order_id=child.client_order_id,
                parent_order_id=child.parent_order_id,
                child_index=child.child_index,
                symbol=child.symbol,
                side=child.side,
                order_type=child.order_type,
                limit_price=child.price,
                quantity=child.quantity,
                notional_usdt=child.notional_usdt,
                queue_ahead_qty=Decimal("0"),
                created_time_ms=child.created_time_ms,
                time_in_force=child.time_in_force,
            )
            resting.status = OrderStatus.FILLED
            resting.executed_quantity = fill.fill_quantity
            resting.executed_notional = fill.fill_notional_usdt
            resting.total_fee_usdt = fill.fee_usdt
            self._resting_orders[child.client_order_id] = resting
            return resting, fills

    def on_aggregate_trade(self, trade: AggregateTrade) -> list[OrderExecutionFill]:
        """Process incoming aggregate trade event; check queue depletion or crossed fills."""
        fills: list[OrderExecutionFill] = []
        trade_ms = (
            int(trade.trade_time.timestamp() * 1000)
            if hasattr(trade, "trade_time") and trade.trade_time
            else 0
        )

        for order in list(self._resting_orders.values()):
            if (
                not order.is_active
                or order.status == OrderStatus.FILLED
                or order.symbol != trade.symbol
            ):
                continue

            if order.side == OrderSide.BUY:
                if trade.price < order.limit_price:
                    # Traded below limit price -> immediate passive fill at limit price
                    fill = self._fill_resting_order(
                        order,
                        fill_price=order.limit_price,
                        fill_time_ms=trade_ms,
                        fill_qty=order.remaining_quantity,
                        is_maker=True,
                    )
                    fills.append(fill)
                elif trade.price == order.limit_price:
                    # Traded at limit price: deplete queue ahead and fill order
                    if order.queue_ahead_qty > Decimal("0"):
                        if trade.quantity < order.queue_ahead_qty:
                            order.queue_ahead_qty -= trade.quantity
                            trade_avail = Decimal("0")
                        else:
                            trade_avail = trade.quantity - order.queue_ahead_qty
                            order.queue_ahead_qty = Decimal("0")
                            is_maker_match = getattr(trade, "is_buyer_maker", False) is True
                            if trade_avail <= Decimal("0") and is_maker_match:
                                trade_avail = order.remaining_quantity
                    else:
                        trade_avail = trade.quantity

                    if trade_avail > Decimal("0"):
                        fill_qty = min(order.remaining_quantity, trade_avail)
                        fill = self._fill_resting_order(
                            order,
                            fill_price=order.limit_price,
                            fill_time_ms=trade_ms,
                            fill_qty=fill_qty,
                            is_maker=True,
                        )
                        fills.append(fill)
            else:  # OrderSide.SELL
                if trade.price > order.limit_price:
                    # Traded above limit price -> immediate passive fill at limit price
                    fill = self._fill_resting_order(
                        order,
                        fill_price=order.limit_price,
                        fill_time_ms=trade_ms,
                        fill_qty=order.remaining_quantity,
                        is_maker=True,
                    )
                    fills.append(fill)
                elif trade.price == order.limit_price:
                    # Traded at limit price: deplete queue ahead and fill order
                    if order.queue_ahead_qty > Decimal("0"):
                        if trade.quantity < order.queue_ahead_qty:
                            order.queue_ahead_qty -= trade.quantity
                            trade_avail = Decimal("0")
                        else:
                            trade_avail = trade.quantity - order.queue_ahead_qty
                            order.queue_ahead_qty = Decimal("0")
                            is_maker_match = getattr(trade, "is_buyer_maker", True) is False
                            if trade_avail <= Decimal("0") and is_maker_match:
                                trade_avail = order.remaining_quantity
                    else:
                        trade_avail = trade.quantity

                    if trade_avail > Decimal("0"):
                        fill_qty = min(order.remaining_quantity, trade_avail)
                        fill = self._fill_resting_order(
                            order,
                            fill_price=order.limit_price,
                            fill_time_ms=trade_ms,
                            fill_qty=fill_qty,
                            is_maker=True,
                        )
                        fills.append(fill)

        return fills

    def on_depth_snapshot(self, depth: OrderBookDepthSnapshot) -> list[OrderExecutionFill]:
        """Process incoming book depth update; check if opposite best crosses limit price."""
        self.update_depth(depth)
        fills: list[OrderExecutionFill] = []
        depth_ms = (
            int(depth.event_time.timestamp() * 1000)
            if hasattr(depth, "event_time") and depth.event_time
            else 0
        )

        best_bid = depth.best_bid_price or (depth.bids[0].price if depth.bids else None)
        best_ask = depth.best_ask_price or (depth.asks[0].price if depth.asks else None)

        if not best_bid or not best_ask:
            return fills

        for order in list(self._resting_orders.values()):
            if (
                not order.is_active
                or order.status == OrderStatus.FILLED
                or order.symbol != depth.symbol
            ):
                continue

            if order.side == OrderSide.BUY:
                if best_ask <= order.limit_price:
                    # Best ask crossed buy limit price -> immediate fill at limit price
                    fill = self._fill_resting_order(
                        order,
                        fill_price=order.limit_price,
                        fill_time_ms=depth_ms,
                        fill_qty=order.remaining_quantity,
                        is_maker=True,
                    )
                    fills.append(fill)
            else:  # SELL
                if best_bid >= order.limit_price:
                    # Best bid crossed sell limit price -> immediate fill at limit price
                    fill = self._fill_resting_order(
                        order,
                        fill_price=order.limit_price,
                        fill_time_ms=depth_ms,
                        fill_qty=order.remaining_quantity,
                        is_maker=True,
                    )
                    fills.append(fill)

        return fills

    def cancel_order(self, client_order_id: str) -> SimulatedRestingOrder | None:
        """Cancel an active resting order."""
        order = self._resting_orders.get(client_order_id)
        if order and order.is_active:
            order.status = OrderStatus.CANCELLED
            return order
        return None

    def cancel_all_orders(self, symbol: str | None = None) -> list[SimulatedRestingOrder]:
        """Cancel all resting orders, optionally filtered by symbol."""
        cancelled: list[SimulatedRestingOrder] = []
        for order in self._resting_orders.values():
            if order.is_active and (symbol is None or order.symbol == symbol):
                order.status = OrderStatus.CANCELLED
                cancelled.append(order)
        return cancelled

    def get_resting_order(self, client_order_id: str) -> SimulatedRestingOrder | None:
        return self._resting_orders.get(client_order_id)

    def get_active_orders(self, symbol: str | None = None) -> list[SimulatedRestingOrder]:
        return [
            o
            for o in self._resting_orders.values()
            if o.is_active and (symbol is None or o.symbol == symbol)
        ]

    def _fill_resting_order(
        self,
        order: SimulatedRestingOrder,
        *,
        fill_price: Decimal,
        fill_time_ms: int,
        fill_qty: Decimal | None = None,
        is_maker: bool = True,
    ) -> OrderExecutionFill:
        """Fill an active resting limit order."""
        qty = fill_qty if fill_qty is not None else order.remaining_quantity
        fill = self._create_fill(
            child=order,
            fill_price=fill_price,
            fill_qty=qty,
            is_maker=is_maker,
            slippage_rate=Decimal("0") if is_maker else self.slippage_rate,
            fill_time_ms=fill_time_ms,
        )
        order.executed_quantity += fill.fill_quantity
        order.remaining_quantity = max(Decimal("0"), order.remaining_quantity - fill.fill_quantity)
        order.executed_notional += fill.fill_notional_usdt
        order.total_fee_usdt += fill.fee_usdt
        if order.remaining_quantity <= Decimal("0"):
            order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.PARTIALLY_FILLED
        return fill

    def _create_fill(
        self,
        *,
        child: ChildOrderIntention | SimulatedRestingOrder,
        fill_price: Decimal,
        fill_qty: Decimal,
        is_maker: bool,
        slippage_rate: Decimal,
        fill_time_ms: int,
    ) -> OrderExecutionFill:
        """Generate an execution fill record with exact fee and slippage math."""
        # Calculate effective fill price with slippage (for aggressive taker fills)
        if not is_maker and slippage_rate > 0:
            if child.side == OrderSide.BUY:
                effective_price = fill_price * (Decimal("1") + slippage_rate)
            else:
                effective_price = fill_price * (Decimal("1") - slippage_rate)
        else:
            effective_price = fill_price

        # V2: For limit orders, respect limit price ceiling
        limit_price = getattr(child, "price", None) or getattr(child, "limit_price", None)
        if child.order_type == OrderType.LIMIT and limit_price is not None:
            if child.side == OrderSide.BUY:
                effective_price = min(limit_price, effective_price)
            else:
                effective_price = max(limit_price, effective_price)

        notional = (fill_qty * effective_price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

        # V1: Clamp fill quantity so executed notional is strictly <= 5.00 USDT
        if notional > HARD_MICRO_NOTIONAL_CAP_USDT:
            fill_qty = (HARD_MICRO_NOTIONAL_CAP_USDT / effective_price).quantize(
                Decimal("0.00000001"), rounding=ROUND_DOWN
            )
            notional = (fill_qty * effective_price).quantize(
                Decimal("0.00000001"), rounding=ROUND_DOWN
            )
            while notional > HARD_MICRO_NOTIONAL_CAP_USDT and fill_qty > Decimal("0.00000001"):
                fill_qty -= Decimal("0.00000001")
                notional = (fill_qty * effective_price).quantize(
                    Decimal("0.00000001"), rounding=ROUND_DOWN
                )

        fee_rate = self.maker_fee_rate if is_maker else self.taker_fee_rate
        fee = (notional * fee_rate).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        slippage_bps = (slippage_rate * Decimal("10000")) if not is_maker else Decimal("0")

        fill = OrderExecutionFill(
            fill_id=f"fill-{uuid.uuid4().hex[:12]}",
            client_order_id=child.client_order_id,
            parent_order_id=child.parent_order_id,
            child_index=child.child_index,
            symbol=child.symbol,
            side=child.side,
            fill_price=effective_price.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN),
            fill_quantity=fill_qty,
            fill_notional_usdt=notional,
            fee_usdt=fee,
            fee_rate=fee_rate,
            is_maker=is_maker,
            slippage_bps=slippage_bps,
            fill_time_ms=fill_time_ms,
        )
        self._execution_fills.append(fill)
        return fill


PassiveMatchingSimulator = SimulatedPassiveMatchingEngine


__all__ = [
    "CANARY_STAGED_SYMBOLS",
    "ChildOrderIntention",
    "DEFAULT_MAKER_FEE_RATE",
    "DEFAULT_TAKER_FEE_RATE",
    "DEFAULT_TAKER_SLIPPAGE_BPS",
    "DEFAULT_TAKER_SLIPPAGE_RATE",
    "HARD_MICRO_NOTIONAL_CAP_USDT",
    "IndividualMicroCapExceededError",
    "MIN_MICRO_NOTIONAL_FLOOR_USDT",
    "MicroNotionalFloorViolationError",
    "NOMINAL_CHUNK_CAP_USDT",
    "OrderExecutionFill",
    "OrderSide",
    "OrderSlicingError",
    "OrderStatus",
    "OrderType",
    "PaperExecutionError",
    "ParentOrderIntention",
    "PassiveMatchingSimulator",
    "RestingOrderNotFoundError",
    "SimulatedPassiveMatchingEngine",
    "SimulatedRestingOrder",
    "THROTTLED_CHUNK_CAP_USDT",
    "TimeInForce",
    "get_default_exchange_filters",
    "quantize_price",
    "quantize_quantity",
    "slice_parent_order",
]
