from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel, StrictNonNegativeDecimal
from .performance_metrics import TradePerformanceMetrics


class WalkForwardWindowMetrics(DomainModel):
    """One explicitly bound train/validation/OOS metric window."""

    window_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    split: Literal["train", "validation", "oos"] = "oos"
    window_start: datetime
    window_end: datetime
    metrics: TradePerformanceMetrics

    @field_validator("window_start", "window_end")
    @classmethod
    def timestamp_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("walk-forward window timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_window_binding(self) -> WalkForwardWindowMetrics:
        if self.window_end <= self.window_start:
            raise ValueError("walk-forward window end must be after start")
        if self.metrics.symbol != self.symbol:
            raise ValueError("window symbol must match metric symbol")
        return self


class WalkForwardSymbolSummary(DomainModel):
    """Deterministic OOS summary for one required symbol."""

    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    window_count: int = Field(ge=1, strict=True)
    total_trade_count: int = Field(ge=0, strict=True)
    gross_profit: StrictNonNegativeDecimal
    gross_loss: StrictNonNegativeDecimal
    net_pnl: Decimal
    pooled_profit_factor: StrictNonNegativeDecimal | None = None
    average_return_pct: Decimal
    worst_max_drawdown: StrictNonNegativeDecimal
    worst_max_drawdown_pct: StrictNonNegativeDecimal


class WalkForwardAggregation(DomainModel):
    """OOS-only deterministic aggregation without qualification decisions."""

    aggregation_version: Literal[1] = 1
    required_symbols: tuple[str, ...] = Field(min_length=1)
    windows: tuple[WalkForwardWindowMetrics, ...] = Field(min_length=1)
    per_symbol: tuple[WalkForwardSymbolSummary, ...] = Field(min_length=1)
    window_count: int = Field(ge=1, strict=True)
    total_trade_count: int = Field(ge=0, strict=True)
    pooled_gross_profit: StrictNonNegativeDecimal
    pooled_gross_loss: StrictNonNegativeDecimal
    pooled_net_pnl: Decimal
    pooled_profit_factor: StrictNonNegativeDecimal | None = None
    average_return_pct: Decimal
    worst_max_drawdown: StrictNonNegativeDecimal
    worst_max_drawdown_pct: StrictNonNegativeDecimal
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False

    @model_validator(mode="after")
    def validate_aggregation_consistency(self) -> WalkForwardAggregation:
        if self.required_symbols != tuple(sorted(set(self.required_symbols))):
            raise ValueError("required symbols must be sorted and unique")
        if self.window_count != len(self.windows):
            raise ValueError("window count must equal bound windows")
        if tuple(summary.symbol for summary in self.per_symbol) != self.required_symbols:
            raise ValueError("per-symbol summaries must match required symbols")
        if self.total_trade_count != sum(window.metrics.trade_count for window in self.windows):
            raise ValueError("total trade count must equal bound windows")
        if self.pooled_gross_profit != sum(
            (window.metrics.gross_profit for window in self.windows), Decimal("0")
        ):
            raise ValueError("pooled gross profit is inconsistent")
        if self.pooled_gross_loss != sum(
            (window.metrics.gross_loss for window in self.windows), Decimal("0")
        ):
            raise ValueError("pooled gross loss is inconsistent")
        if self.pooled_net_pnl != self.pooled_gross_profit - self.pooled_gross_loss:
            raise ValueError("pooled net P&L is inconsistent")
        expected_profit_factor = (
            self.pooled_gross_profit / self.pooled_gross_loss if self.pooled_gross_loss else None
        )
        if self.pooled_profit_factor != expected_profit_factor:
            raise ValueError("pooled profit factor is inconsistent")
        expected_average_return = sum(
            (window.metrics.return_pct for window in self.windows), Decimal("0")
        ) / Decimal(self.window_count)
        if self.average_return_pct != expected_average_return:
            raise ValueError("average return is inconsistent")
        if self.worst_max_drawdown != max(window.metrics.max_drawdown for window in self.windows):
            raise ValueError("worst drawdown is inconsistent")
        if self.worst_max_drawdown_pct != max(
            window.metrics.max_drawdown_pct for window in self.windows
        ):
            raise ValueError("worst drawdown percentage is inconsistent")
        return self


def aggregate_walk_forward_metrics(
    windows: Sequence[WalkForwardWindowMetrics],
    *,
    required_symbols: Sequence[str],
    minimum_windows: int = 1,
) -> WalkForwardAggregation:
    """Aggregate explicit OOS windows without mixing splits or fabricating data."""
    symbols = tuple(required_symbols)
    if not symbols or symbols != tuple(sorted(set(symbols))):
        raise ValueError("required symbols must be non-empty, sorted, and unique")
    if any(not symbol.isupper() or not symbol.isalnum() for symbol in symbols):
        raise ValueError("required symbols must be uppercase alphanumeric")
    if minimum_windows < 1:
        raise ValueError("minimum window count must be positive")
    if not windows:
        raise ValueError("at least one walk-forward window is required")

    ordered = tuple(
        sorted(
            windows,
            key=lambda window: (
                window.symbol,
                window.window_start,
                window.window_end,
                window.window_id,
            ),
        )
    )
    required_set = set(symbols)
    seen: set[tuple[str, str]] = set()
    for window in ordered:
        if window.split != "oos":
            raise ValueError("walk-forward aggregation accepts OOS windows only")
        if window.symbol not in required_set:
            raise ValueError("window contains a symbol outside required symbols")
        if window.metrics.data_source != "cached_only" or window.metrics.exchange_access:
            raise ValueError("walk-forward metrics must be cached-only")
        key = (window.symbol, window.window_id)
        if key in seen:
            raise ValueError("duplicate symbol/window binding")
        seen.add(key)

    by_symbol: dict[str, list[WalkForwardWindowMetrics]] = {symbol: [] for symbol in symbols}
    for window in ordered:
        by_symbol[window.symbol].append(window)
    for symbol, symbol_windows in by_symbol.items():
        if not symbol_windows:
            raise ValueError(f"required symbol {symbol} has no OOS windows")
        if len(symbol_windows) < minimum_windows:
            raise ValueError(f"symbol {symbol} is below minimum OOS window coverage")
        previous_end: datetime | None = None
        for window in symbol_windows:
            if previous_end is not None and window.window_start < previous_end:
                raise ValueError(f"overlapping OOS windows for symbol {symbol}")
            previous_end = window.window_end

    summaries = tuple(_build_symbol_summary(symbol, by_symbol[symbol]) for symbol in symbols)
    pooled_gross_profit = sum((window.metrics.gross_profit for window in ordered), Decimal("0"))
    pooled_gross_loss = sum((window.metrics.gross_loss for window in ordered), Decimal("0"))
    pooled_net_pnl = pooled_gross_profit - pooled_gross_loss
    return WalkForwardAggregation(
        required_symbols=symbols,
        windows=ordered,
        per_symbol=summaries,
        window_count=len(ordered),
        total_trade_count=sum(window.metrics.trade_count for window in ordered),
        pooled_gross_profit=pooled_gross_profit,
        pooled_gross_loss=pooled_gross_loss,
        pooled_net_pnl=pooled_net_pnl,
        pooled_profit_factor=(
            pooled_gross_profit / pooled_gross_loss if pooled_gross_loss else None
        ),
        average_return_pct=sum((window.metrics.return_pct for window in ordered), Decimal("0"))
        / Decimal(len(ordered)),
        worst_max_drawdown=max(window.metrics.max_drawdown for window in ordered),
        worst_max_drawdown_pct=max(window.metrics.max_drawdown_pct for window in ordered),
    )


def _build_symbol_summary(
    symbol: str,
    windows: Sequence[WalkForwardWindowMetrics],
) -> WalkForwardSymbolSummary:
    gross_profit = sum((window.metrics.gross_profit for window in windows), Decimal("0"))
    gross_loss = sum((window.metrics.gross_loss for window in windows), Decimal("0"))
    return WalkForwardSymbolSummary(
        symbol=symbol,
        window_count=len(windows),
        total_trade_count=sum(window.metrics.trade_count for window in windows),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_pnl=gross_profit - gross_loss,
        pooled_profit_factor=(gross_profit / gross_loss if gross_loss else None),
        average_return_pct=sum((window.metrics.return_pct for window in windows), Decimal("0"))
        / Decimal(len(windows)),
        worst_max_drawdown=max(window.metrics.max_drawdown for window in windows),
        worst_max_drawdown_pct=max(window.metrics.max_drawdown_pct for window in windows),
    )


__all__ = [
    "WalkForwardAggregation",
    "WalkForwardSymbolSummary",
    "WalkForwardWindowMetrics",
    "aggregate_walk_forward_metrics",
]
