from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal

import pandas as pd
from pydantic import Field, field_validator, model_validator

from ..data.parquet import DataQualityError, canonicalize_bars
from ..domain.contracts import DomainModel, StrictNonNegativeDecimal, StrictPositiveDecimal

FractionDecimal = Decimal


class TradeSimulationConfig(DomainModel):
    """Deterministic unlevered research costs and sizing for one cached window."""

    starting_equity: StrictPositiveDecimal
    position_fraction: FractionDecimal = Field(strict=True, gt=Decimal("0"), le=Decimal("1"))
    taker_fee_rate: StrictNonNegativeDecimal = Field(le=Decimal("1"))
    slippage_rate: StrictNonNegativeDecimal = Field(le=Decimal("1"))


class EquityPoint(DomainModel):
    timestamp: datetime
    equity: StrictNonNegativeDecimal

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("equity timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)


class SimulatedTrade(DomainModel):
    trade_id: str = Field(min_length=1)
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    side: Literal["LONG", "SHORT"]
    entry_timestamp: datetime
    exit_timestamp: datetime
    quantity: StrictPositiveDecimal
    entry_price: StrictPositiveDecimal
    exit_price: StrictPositiveDecimal
    entry_notional: StrictPositiveDecimal
    exit_notional: StrictPositiveDecimal
    entry_fee: StrictNonNegativeDecimal
    exit_fee: StrictNonNegativeDecimal
    fees: StrictNonNegativeDecimal
    slippage_cost: StrictNonNegativeDecimal
    gross_pnl: Decimal
    net_pnl: Decimal
    exit_reason: Literal["signal_exit", "forced_end_of_window"]

    @field_validator("entry_timestamp", "exit_timestamp")
    @classmethod
    def trade_timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("trade timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @field_validator("gross_pnl", "net_pnl")
    @classmethod
    def pnl_is_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("trade P&L must be finite")
        return value

    @model_validator(mode="after")
    def validate_trade_accounting(self) -> SimulatedTrade:
        if self.exit_timestamp < self.entry_timestamp:
            raise ValueError("trade exit must not precede entry")
        if self.fees != self.entry_fee + self.exit_fee:
            raise ValueError("trade fees must equal entry plus exit fees")
        if self.net_pnl != self.gross_pnl - self.fees:
            raise ValueError("trade net P&L must include fees")
        return self


class TradeSimulationResult(DomainModel):
    simulation_version: Literal[1] = 1
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    starting_equity: StrictPositiveDecimal
    final_equity: StrictNonNegativeDecimal
    total_fees: StrictNonNegativeDecimal
    total_slippage_cost: StrictNonNegativeDecimal
    trades: tuple[SimulatedTrade, ...] = ()
    equity_curve: tuple[EquityPoint, ...] = Field(min_length=1)
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False

    @model_validator(mode="after")
    def validate_result_accounting(self) -> TradeSimulationResult:
        if self.equity_curve[-1].equity != self.final_equity:
            raise ValueError("final equity must equal the last equity-curve point")
        expected_final_equity = self.starting_equity + sum(
            (trade.net_pnl for trade in self.trades), Decimal("0")
        )
        if self.final_equity != expected_final_equity:
            raise ValueError("final equity must equal starting equity plus net trade P&L")
        if self.total_fees != sum((trade.fees for trade in self.trades), Decimal("0")):
            raise ValueError("total fees must equal the trade ledger")
        if self.total_slippage_cost != sum(
            (trade.slippage_cost for trade in self.trades), Decimal("0")
        ):
            raise ValueError("total slippage must equal the trade ledger")
        return self


@dataclass(frozen=True, slots=True)
class _OpenPosition:
    trade_id: str
    entry_timestamp: datetime
    side: Literal["LONG", "SHORT"]
    quantity: Decimal
    entry_price: Decimal
    entry_notional: Decimal
    entry_fee: Decimal
    entry_slippage_cost: Decimal


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        converted = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise DataQualityError(f"simulation value is invalid: {field}") from exc
    if not converted.is_finite():
        raise DataQualityError(f"simulation value is not finite: {field}")
    return converted


def _fill_price(raw_price: Decimal, side: str, *, entry: bool, slippage_rate: Decimal) -> Decimal:
    adverse = slippage_rate if (side == "LONG") == entry else -slippage_rate
    return raw_price * (Decimal("1") + adverse)


def _mark_equity(cash: Decimal, position: _OpenPosition | None, close: Decimal) -> Decimal:
    if position is None:
        return cash
    if position.side == "LONG":
        return cash + (close - position.entry_price) * position.quantity
    return cash + (position.entry_price - close) * position.quantity


def _close_position(
    position: _OpenPosition,
    *,
    symbol: str,
    raw_exit_price: Decimal,
    exit_timestamp: datetime,
    reason: Literal["signal_exit", "forced_end_of_window"],
    taker_fee_rate: Decimal,
    slippage_rate: Decimal,
) -> tuple[SimulatedTrade, Decimal]:
    exit_price = _fill_price(
        raw_exit_price,
        position.side,
        entry=False,
        slippage_rate=slippage_rate,
    )
    exit_notional = position.quantity * exit_price
    exit_fee = exit_notional * taker_fee_rate
    exit_slippage_cost = position.quantity * raw_exit_price * slippage_rate
    if position.side == "LONG":
        gross_pnl = (exit_price - position.entry_price) * position.quantity
    else:
        gross_pnl = (position.entry_price - exit_price) * position.quantity
    fees = position.entry_fee + exit_fee
    trade = SimulatedTrade(
        trade_id=position.trade_id,
        symbol=symbol,
        side=position.side,
        entry_timestamp=position.entry_timestamp,
        exit_timestamp=exit_timestamp,
        quantity=position.quantity,
        entry_price=position.entry_price,
        exit_price=exit_price,
        entry_notional=position.entry_notional,
        exit_notional=exit_notional,
        entry_fee=position.entry_fee,
        exit_fee=exit_fee,
        fees=fees,
        slippage_cost=position.entry_slippage_cost + exit_slippage_cost,
        gross_pnl=gross_pnl,
        net_pnl=gross_pnl - fees,
        exit_reason=reason,
    )
    return trade, gross_pnl - exit_fee


def simulate_cached_signals(
    frame: pd.DataFrame,
    *,
    symbol: str,
    config: TradeSimulationConfig,
) -> TradeSimulationResult:
    """Simulate cached signals with open fills and a deterministic final close."""
    if not re.fullmatch(r"[A-Z0-9]+", symbol):
        raise DataQualityError("simulation symbol must be uppercase alphanumeric")
    required_columns = {"timestamp", "open", "high", "low", "close", "signal"}
    missing = sorted(required_columns.difference(frame.columns))
    if missing:
        raise DataQualityError("simulation frame is missing columns: " + ", ".join(missing))
    canonical = canonicalize_bars(frame, interval=timedelta(minutes=5))
    rows = canonical.to_dict(orient="records")
    parsed_rows: list[tuple[datetime, Decimal, Decimal, Decimal]] = []
    for row in rows:
        timestamp = pd.Timestamp(row["timestamp"]).to_pydatetime()
        raw_open = _decimal(row["open"], field="open")
        raw_close = _decimal(row["close"], field="close")
        for field in ("high", "low"):
            if _decimal(row[field], field=field) <= 0:
                raise DataQualityError(f"simulation OHLC value must be positive: {field}")
        if raw_open <= 0 or raw_close <= 0:
            raise DataQualityError("simulation OHLC value must be positive")
        signal_decimal = _decimal(row["signal"], field="signal")
        if signal_decimal not in (Decimal("-1"), Decimal("0"), Decimal("1")):
            raise DataQualityError("simulation signal must be -1, 0, or 1")
        parsed_rows.append((timestamp, raw_open, raw_close, signal_decimal))

    cash = config.starting_equity
    position: _OpenPosition | None = None
    trades: list[SimulatedTrade] = []
    equity_points: list[EquityPoint] = []
    for index, (timestamp, raw_open, raw_close, signal_decimal) in enumerate(parsed_rows):
        signal = int(signal_decimal)
        closed_this_bar = False
        if position is not None:
            opposite = (position.side == "LONG" and signal == -1) or (
                position.side == "SHORT" and signal == 1
            )
            if opposite:
                trade, cash_delta = _close_position(
                    position,
                    symbol=symbol,
                    raw_exit_price=raw_open,
                    exit_timestamp=timestamp,
                    reason="signal_exit",
                    taker_fee_rate=config.taker_fee_rate,
                    slippage_rate=config.slippage_rate,
                )
                trades.append(trade)
                cash += cash_delta
                position = None
                closed_this_bar = True
        if position is None and not closed_this_bar and signal != 0:
            side: Literal["LONG", "SHORT"] = "LONG" if signal == 1 else "SHORT"
            entry_price = _fill_price(
                raw_open,
                side,
                entry=True,
                slippage_rate=config.slippage_rate,
            )
            quantity = cash * config.position_fraction / raw_open
            entry_notional = quantity * entry_price
            entry_fee = entry_notional * config.taker_fee_rate
            if cash - entry_fee < 0:
                raise DataQualityError("entry fee exceeds available simulation equity")
            cash -= entry_fee
            position = _OpenPosition(
                trade_id=f"{symbol.lower()}-{index:06d}",
                entry_timestamp=timestamp,
                side=side,
                quantity=quantity,
                entry_price=entry_price,
                entry_notional=entry_notional,
                entry_fee=entry_fee,
                entry_slippage_cost=quantity * raw_open * config.slippage_rate,
            )
        equity_points.append(
            EquityPoint(timestamp=timestamp, equity=_mark_equity(cash, position, raw_close))
        )

    final_timestamp, _, final_close, _ = parsed_rows[-1]
    if position is not None:
        final_close_timestamp = final_timestamp + timedelta(minutes=5) - timedelta(milliseconds=1)
        trade, cash_delta = _close_position(
            position,
            symbol=symbol,
            raw_exit_price=final_close,
            exit_timestamp=final_close_timestamp,
            reason="forced_end_of_window",
            taker_fee_rate=config.taker_fee_rate,
            slippage_rate=config.slippage_rate,
        )
        trades.append(trade)
        cash += cash_delta
        equity_points.append(EquityPoint(timestamp=final_close_timestamp, equity=cash))
    elif equity_points[-1].timestamp != (
        final_timestamp + timedelta(minutes=5) - timedelta(milliseconds=1)
    ):
        equity_points.append(
            EquityPoint(
                timestamp=final_timestamp + timedelta(minutes=5) - timedelta(milliseconds=1),
                equity=cash,
            )
        )

    return TradeSimulationResult(
        symbol=symbol,
        starting_equity=config.starting_equity,
        final_equity=cash,
        total_fees=sum((trade.fees for trade in trades), Decimal("0")),
        total_slippage_cost=sum((trade.slippage_cost for trade in trades), Decimal("0")),
        trades=tuple(trades),
        equity_curve=tuple(equity_points),
    )


__all__ = [
    "EquityPoint",
    "SimulatedTrade",
    "TradeSimulationConfig",
    "TradeSimulationResult",
    "simulate_cached_signals",
]
