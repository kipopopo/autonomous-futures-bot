from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel, StrictNonNegativeDecimal, StrictPositiveDecimal
from .trade_simulation import EquityPoint, TradeSimulationResult


class TradePerformanceMetrics(DomainModel):
    """Deterministic net performance metrics for one cached simulation result."""

    metrics_version: Literal[1] = 1
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    starting_equity: StrictPositiveDecimal
    final_equity: StrictNonNegativeDecimal
    trade_count: int = Field(ge=0, strict=True)
    winning_trades: int = Field(ge=0, strict=True)
    losing_trades: int = Field(ge=0, strict=True)
    breakeven_trades: int = Field(ge=0, strict=True)
    win_rate: StrictNonNegativeDecimal = Field(le=Decimal("1"))
    gross_profit: StrictNonNegativeDecimal
    gross_loss: StrictNonNegativeDecimal
    net_pnl: Decimal
    average_trade_pnl: Decimal
    return_pct: Decimal
    profit_factor: StrictNonNegativeDecimal | None = None
    max_drawdown: StrictNonNegativeDecimal
    max_drawdown_pct: StrictNonNegativeDecimal
    peak_equity: StrictPositiveDecimal
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False

    @field_validator("net_pnl", "average_trade_pnl", "return_pct")
    @classmethod
    def decimal_metric_is_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("performance metric must be finite")
        return value

    @model_validator(mode="after")
    def validate_metric_consistency(self) -> TradePerformanceMetrics:
        if self.trade_count != self.winning_trades + self.losing_trades + self.breakeven_trades:
            raise ValueError("trade buckets must equal trade count")
        expected_win_rate = (
            Decimal(self.winning_trades) / Decimal(self.trade_count)
            if self.trade_count
            else Decimal("0")
        )
        if self.win_rate != expected_win_rate:
            raise ValueError("win rate must equal winning trades divided by trade count")
        expected_net_pnl = self.gross_profit - self.gross_loss
        if self.net_pnl != expected_net_pnl:
            raise ValueError("net P&L must equal gross profit minus gross loss")
        expected_average = (
            self.net_pnl / Decimal(self.trade_count) if self.trade_count else Decimal("0")
        )
        if self.average_trade_pnl != expected_average:
            raise ValueError("average trade P&L is inconsistent")
        expected_return_pct = self.net_pnl / self.starting_equity * Decimal("100")
        if self.return_pct != expected_return_pct:
            raise ValueError("return percentage is inconsistent with net P&L")
        expected_profit_factor = self.gross_profit / self.gross_loss if self.gross_loss else None
        if self.profit_factor != expected_profit_factor:
            raise ValueError("profit factor is inconsistent with net trade buckets")
        expected_drawdown_pct = self.max_drawdown / self.peak_equity * Decimal("100")
        if self.max_drawdown_pct != expected_drawdown_pct:
            raise ValueError("drawdown percentage is inconsistent with peak equity")
        expected_final = self.starting_equity + self.net_pnl
        if self.final_equity != expected_final:
            raise ValueError("final equity must equal starting equity plus net P&L")
        return self


def _sum_decimal(values: tuple[Decimal, ...]) -> Decimal:
    with localcontext() as context:
        context.prec = max(context.prec, 80)
        total = sum(values, Decimal("0"))
    return +total


def calculate_performance_metrics(result: TradeSimulationResult) -> TradePerformanceMetrics:
    """Calculate finite net performance metrics from a cached trade ledger."""
    net_pnls = tuple(trade.net_pnl for trade in result.trades)
    winning_trades = sum(pnl > 0 for pnl in net_pnls)
    losing_trades = sum(pnl < 0 for pnl in net_pnls)
    breakeven_trades = sum(pnl == 0 for pnl in net_pnls)
    gross_profit = _sum_decimal(tuple(pnl for pnl in net_pnls if pnl > 0))
    gross_loss = _sum_decimal(tuple(-pnl for pnl in net_pnls if pnl < 0))
    net_pnl = _sum_decimal(net_pnls)
    peak_equity = max((result.starting_equity, *(point.equity for point in result.equity_curve)))
    max_drawdown = _max_drawdown(result.starting_equity, result.equity_curve)
    return TradePerformanceMetrics(
        symbol=result.symbol,
        starting_equity=result.starting_equity,
        final_equity=result.final_equity,
        trade_count=len(net_pnls),
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        breakeven_trades=breakeven_trades,
        win_rate=(Decimal(winning_trades) / Decimal(len(net_pnls)) if net_pnls else Decimal("0")),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_pnl=net_pnl,
        average_trade_pnl=(net_pnl / Decimal(len(net_pnls)) if net_pnls else Decimal("0")),
        return_pct=net_pnl / result.starting_equity * Decimal("100"),
        profit_factor=(gross_profit / gross_loss if gross_loss else None),
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown / peak_equity * Decimal("100"),
        peak_equity=peak_equity,
    )


def _max_drawdown(
    starting_equity: Decimal,
    equity_curve: tuple[EquityPoint, ...],
) -> Decimal:
    peak = starting_equity
    max_drawdown = Decimal("0")
    for point in equity_curve:
        peak = max(peak, point.equity)
        max_drawdown = max(max_drawdown, peak - point.equity)
    return max_drawdown


__all__ = ["TradePerformanceMetrics", "calculate_performance_metrics"]
