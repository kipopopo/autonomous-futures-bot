"""Data models for quantitative analytics, risk metrics, and daily performance reports.

Provides strongly typed domain models with exact Decimal representations
and JSON schema serialization for institutional performance attribution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


def _parse_decimal(val: Any, default: str = "0.00") -> Decimal:
    """Safely parse value into Decimal."""
    if val is None:
        return Decimal(default)
    if isinstance(val, Decimal):
        return val
    return Decimal(str(val))


def _parse_opt_decimal(val: Any) -> Decimal | None:
    """Safely parse optional Decimal."""
    if val is None:
        return None
    if isinstance(val, Decimal):
        return val
    return Decimal(str(val))


def _parse_opt_datetime(val: Any) -> datetime | None:
    """Safely parse optional ISO datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    return datetime.fromisoformat(str(val))


@dataclass(frozen=True, slots=True)
class TradeRecord:
    """Represents a completed round-trip trade matched from open and close ledger events."""

    close_sequence: int
    trade_id: str
    candidate_id: str
    candidate_artifact_hash: str
    symbol: str
    side: str  # "LONG" or "SHORT"
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    opened_at: datetime
    closed_at: datetime
    holding_duration_seconds: float
    entry_fee: Decimal
    exit_fee: Decimal
    total_fees: Decimal
    slippage_cost: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    open_approval_id: str | None = None
    close_approval_id: str | None = None
    exit_reason: str = "normal_close"

    def to_dict(self) -> dict[str, Any]:
        """Convert TradeRecord to dictionary representation."""
        return {
            "close_sequence": self.close_sequence,
            "trade_id": self.trade_id,
            "candidate_id": self.candidate_id,
            "candidate_artifact_hash": self.candidate_artifact_hash,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": float(self.quantity),
            "entry_price": float(self.entry_price),
            "exit_price": float(self.exit_price),
            "opened_at": self.opened_at.isoformat(),
            "closed_at": self.closed_at.isoformat(),
            "holding_duration_seconds": self.holding_duration_seconds,
            "entry_fee": float(self.entry_fee),
            "exit_fee": float(self.exit_fee),
            "total_fees": float(self.total_fees),
            "slippage_cost": float(self.slippage_cost),
            "gross_pnl": float(self.gross_pnl),
            "net_pnl": float(self.net_pnl),
            "open_approval_id": self.open_approval_id,
            "close_approval_id": self.close_approval_id,
            "exit_reason": self.exit_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradeRecord:
        """Construct TradeRecord from dictionary."""
        return cls(
            close_sequence=int(data["close_sequence"]),
            trade_id=str(data["trade_id"]),
            candidate_id=str(data["candidate_id"]),
            candidate_artifact_hash=str(data["candidate_artifact_hash"]),
            symbol=str(data["symbol"]),
            side=str(data["side"]),
            quantity=_parse_decimal(data["quantity"]),
            entry_price=_parse_decimal(data["entry_price"]),
            exit_price=_parse_decimal(data["exit_price"]),
            opened_at=_parse_opt_datetime(data["opened_at"]) or datetime.now(),
            closed_at=_parse_opt_datetime(data["closed_at"]) or datetime.now(),
            holding_duration_seconds=float(data.get("holding_duration_seconds", 0.0)),
            entry_fee=_parse_decimal(data.get("entry_fee", "0.00")),
            exit_fee=_parse_decimal(data.get("exit_fee", "0.00")),
            total_fees=_parse_decimal(data.get("total_fees", "0.00")),
            slippage_cost=_parse_decimal(data.get("slippage_cost", "0.00")),
            gross_pnl=_parse_decimal(data.get("gross_pnl", "0.00")),
            net_pnl=_parse_decimal(data.get("net_pnl", "0.00")),
            open_approval_id=data.get("open_approval_id"),
            close_approval_id=data.get("close_approval_id"),
            exit_reason=str(data.get("exit_reason", "normal_close")),
        )


@dataclass(frozen=True, slots=True)
class HoldingDurationStats:
    """Holding duration statistics across closed trades in seconds."""

    avg: float = 0.0
    median: float = 0.0
    min: float = 0.0
    max: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "avg": self.avg,
            "median": self.median,
            "min": self.min,
            "max": self.max,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HoldingDurationStats:
        """Construct HoldingDurationStats from dictionary."""
        return cls(
            avg=float(data.get("avg", 0.0)),
            median=float(data.get("median", 0.0)),
            min=float(data.get("min", 0.0)),
            max=float(data.get("max", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class ExecutionSlippageStats:
    """Execution slippage statistics across closed trades."""

    total_slippage_cost_usdt: float = 0.0
    average_slippage_bps: float = 0.0
    max_slippage_bps: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "total_slippage_cost_usdt": self.total_slippage_cost_usdt,
            "average_slippage_bps": self.average_slippage_bps,
            "max_slippage_bps": self.max_slippage_bps,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionSlippageStats:
        """Construct ExecutionSlippageStats from dictionary."""
        return cls(
            total_slippage_cost_usdt=float(data.get("total_slippage_cost_usdt", 0.0)),
            average_slippage_bps=float(data.get("average_slippage_bps", 0.0)),
            max_slippage_bps=float(data.get("max_slippage_bps", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    """Comprehensive institutional performance and risk metrics."""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0
    win_rate_pct: float = 0.0
    gross_profit: Decimal = Decimal("0.00")
    gross_loss: Decimal = Decimal("0.00")
    net_pnl: Decimal = Decimal("0.00")
    profit_factor: float | None = None
    sharpe_ratio_trade: float | None = None
    sharpe_ratio_annualized: float | None = None
    sortino_ratio: float | None = None
    max_drawdown_amount: Decimal = Decimal("0.00")
    max_drawdown_pct: float = 0.0
    max_drawdown_peak_time: datetime | None = None
    max_drawdown_trough_time: datetime | None = None
    max_drawdown_duration_seconds: float | None = None
    recovery_duration_seconds: float | None = None
    is_drawdown_recovered: bool = True
    calmar_ratio: float | None = None
    recovery_factor: float | None = None
    average_win: Decimal | None = None
    average_loss: Decimal | None = None
    payoff_ratio: float | None = None
    expectancy: Decimal | None = Decimal("0.00")
    expectancy_ratio: float | None = None
    total_fees_paid: Decimal = Decimal("0.00")
    fee_drag_ratio: float | None = None
    holding_duration_mean_seconds: float | None = None
    holding_duration_median_seconds: float | None = None
    holding_duration_min_seconds: float | None = None
    holding_duration_max_seconds: float | None = None
    total_slippage_cost: Decimal = Decimal("0.00")
    average_slippage_bps: float | None = None
    max_slippage_bps: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary conforming to report schema."""
        return {
            "trade_count": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "breakeven_trades": self.breakeven_trades,
            "win_rate_pct": round(self.win_rate_pct, 2),
            "gross_profit_usdt": float(self.gross_profit),
            "gross_loss_usdt": float(self.gross_loss),
            "net_realized_pnl_usdt": float(self.net_pnl),
            "profit_factor": round(self.profit_factor, 4)
            if self.profit_factor is not None
            else None,
            "sharpe_ratio_trade": round(self.sharpe_ratio_trade, 4)
            if self.sharpe_ratio_trade is not None
            else None,
            "sharpe_ratio_annualized": round(self.sharpe_ratio_annualized, 4)
            if self.sharpe_ratio_annualized is not None
            else None,
            "sortino_ratio": round(self.sortino_ratio, 4)
            if self.sortino_ratio is not None
            else None,
            "max_drawdown_usdt": float(self.max_drawdown_amount),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "peak_timestamp_utc": self.max_drawdown_peak_time.isoformat()
            if self.max_drawdown_peak_time
            else None,
            "trough_timestamp_utc": self.max_drawdown_trough_time.isoformat()
            if self.max_drawdown_trough_time
            else None,
            "drawdown_duration_seconds": self.max_drawdown_duration_seconds,
            "recovery_duration_seconds": self.recovery_duration_seconds,
            "is_drawdown_recovered": self.is_drawdown_recovered,
            "calmar_ratio": round(self.calmar_ratio, 4) if self.calmar_ratio is not None else None,
            "recovery_factor": round(self.recovery_factor, 4)
            if self.recovery_factor is not None
            else None,
            "average_win_usdt": float(self.average_win) if self.average_win is not None else 0.0,
            "average_loss_usdt": float(self.average_loss) if self.average_loss is not None else 0.0,
            "win_loss_payoff_ratio": round(self.payoff_ratio, 4)
            if self.payoff_ratio is not None
            else None,
            "expectancy_usdt": float(self.expectancy) if self.expectancy is not None else 0.0,
            "total_taker_fees_usdt": float(self.total_fees_paid),
            "fee_drag_ratio": round(self.fee_drag_ratio, 4)
            if self.fee_drag_ratio is not None
            else None,
            "holding_duration_seconds": {
                "avg": round(self.holding_duration_mean_seconds or 0.0, 1),
                "median": round(self.holding_duration_median_seconds or 0.0, 1),
                "min": round(self.holding_duration_min_seconds or 0.0, 1),
                "max": round(self.holding_duration_max_seconds or 0.0, 1),
            },
            "execution_slippage": {
                "total_slippage_cost_usdt": float(self.total_slippage_cost),
                "average_slippage_bps": round(self.average_slippage_bps or 0.0, 2),
                "max_slippage_bps": round(self.max_slippage_bps or 0.0, 2),
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PerformanceMetrics:
        """Construct PerformanceMetrics from dictionary."""
        holding = data.get("holding_duration_seconds")
        if isinstance(holding, dict):
            h_mean = float(holding["avg"]) if holding.get("avg") is not None else None
            h_median = float(holding["median"]) if holding.get("median") is not None else None
            h_min = float(holding["min"]) if holding.get("min") is not None else None
            h_max = float(holding["max"]) if holding.get("max") is not None else None
        else:
            h_mean = (
                float(data["holding_duration_mean_seconds"])
                if data.get("holding_duration_mean_seconds") is not None
                else None
            )
            h_median = (
                float(data["holding_duration_median_seconds"])
                if data.get("holding_duration_median_seconds") is not None
                else None
            )
            h_min = (
                float(data["holding_duration_min_seconds"])
                if data.get("holding_duration_min_seconds") is not None
                else None
            )
            h_max = (
                float(data["holding_duration_max_seconds"])
                if data.get("holding_duration_max_seconds") is not None
                else None
            )

        slip = data.get("execution_slippage")
        if isinstance(slip, dict):
            tot_slip = _parse_decimal(slip.get("total_slippage_cost_usdt", "0.00"))
            avg_slip = (
                float(slip["average_slippage_bps"])
                if slip.get("average_slippage_bps") is not None
                else None
            )
            max_slip = (
                float(slip["max_slippage_bps"])
                if slip.get("max_slippage_bps") is not None
                else None
            )
        else:
            tot_slip = _parse_decimal(data.get("total_slippage_cost", "0.00"))
            avg_slip = (
                float(data["average_slippage_bps"])
                if data.get("average_slippage_bps") is not None
                else None
            )
            max_slip = (
                float(data["max_slippage_bps"])
                if data.get("max_slippage_bps") is not None
                else None
            )

        total_trades = int(data.get("trade_count", data.get("total_trades", 0)))
        gross_profit = _parse_decimal(
            data.get("gross_profit_usdt", data.get("gross_profit", "0.00"))
        )
        gross_loss = _parse_decimal(data.get("gross_loss_usdt", data.get("gross_loss", "0.00")))
        net_pnl = _parse_decimal(data.get("net_realized_pnl_usdt", data.get("net_pnl", "0.00")))
        max_dd = _parse_decimal(
            data.get("max_drawdown_usdt", data.get("max_drawdown_amount", "0.00"))
        )
        peak_time = _parse_opt_datetime(
            data.get("peak_timestamp_utc", data.get("max_drawdown_peak_time"))
        )
        trough_time = _parse_opt_datetime(
            data.get("trough_timestamp_utc", data.get("max_drawdown_trough_time"))
        )
        avg_win = _parse_opt_decimal(data.get("average_win_usdt", data.get("average_win")))
        avg_loss = _parse_opt_decimal(data.get("average_loss_usdt", data.get("average_loss")))
        raw_payoff = data.get("win_loss_payoff_ratio", data.get("payoff_ratio"))
        payoff = float(raw_payoff) if raw_payoff is not None else None
        expectancy = _parse_opt_decimal(data.get("expectancy_usdt", data.get("expectancy")))
        fees = _parse_decimal(
            data.get("total_taker_fees_usdt", data.get("total_fees_paid", "0.00"))
        )

        raw_dd_dur = data.get(
            "drawdown_duration_seconds", data.get("max_drawdown_duration_seconds")
        )
        dd_dur = float(raw_dd_dur) if raw_dd_dur is not None else None
        raw_rec_dur = data.get("recovery_duration_seconds")
        rec_dur = float(raw_rec_dur) if raw_rec_dur is not None else None

        return cls(
            total_trades=total_trades,
            winning_trades=int(data.get("winning_trades", 0)),
            losing_trades=int(data.get("losing_trades", 0)),
            breakeven_trades=int(data.get("breakeven_trades", 0)),
            win_rate_pct=float(data.get("win_rate_pct", 0.0)),
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            net_pnl=net_pnl,
            profit_factor=float(data["profit_factor"])
            if data.get("profit_factor") is not None
            else None,
            sharpe_ratio_trade=float(data["sharpe_ratio_trade"])
            if data.get("sharpe_ratio_trade") is not None
            else None,
            sharpe_ratio_annualized=float(data["sharpe_ratio_annualized"])
            if data.get("sharpe_ratio_annualized") is not None
            else None,
            sortino_ratio=float(data["sortino_ratio"])
            if data.get("sortino_ratio") is not None
            else None,
            max_drawdown_amount=max_dd,
            max_drawdown_pct=float(data.get("max_drawdown_pct", 0.0)),
            max_drawdown_peak_time=peak_time,
            max_drawdown_trough_time=trough_time,
            max_drawdown_duration_seconds=dd_dur,
            recovery_duration_seconds=rec_dur,
            is_drawdown_recovered=bool(data.get("is_drawdown_recovered", True)),
            calmar_ratio=float(data["calmar_ratio"])
            if data.get("calmar_ratio") is not None
            else None,
            recovery_factor=float(data["recovery_factor"])
            if data.get("recovery_factor") is not None
            else None,
            average_win=avg_win,
            average_loss=avg_loss,
            payoff_ratio=payoff,
            expectancy=expectancy,
            expectancy_ratio=float(data["expectancy_ratio"])
            if data.get("expectancy_ratio") is not None
            else None,
            total_fees_paid=fees,
            fee_drag_ratio=float(data["fee_drag_ratio"])
            if data.get("fee_drag_ratio") is not None
            else None,
            holding_duration_mean_seconds=h_mean,
            holding_duration_median_seconds=h_median,
            holding_duration_min_seconds=h_min,
            holding_duration_max_seconds=h_max,
            total_slippage_cost=tot_slip,
            average_slippage_bps=avg_slip,
            max_slippage_bps=max_slip,
        )


@dataclass(frozen=True, slots=True)
class AssetAttribution:
    """Performance attribution breakdown for a single symbol."""

    symbol: str
    trade_count: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0
    win_rate_pct: float = 0.0
    gross_profit_usdt: Decimal = Decimal("0.00")
    gross_loss_usdt: Decimal = Decimal("0.00")
    net_realized_pnl_usdt: Decimal = Decimal("0.00")
    total_fees_usdt: Decimal = Decimal("0.00")
    profit_factor: float | None = None
    max_drawdown_pct: float = 0.0
    holding_duration_avg_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert asset attribution to dictionary conforming to schema."""
        return {
            "symbol": self.symbol,
            "trade_count": self.trade_count,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "breakeven_trades": self.breakeven_trades,
            "win_rate_pct": round(self.win_rate_pct, 2),
            "gross_profit_usdt": float(self.gross_profit_usdt),
            "gross_loss_usdt": float(self.gross_loss_usdt),
            "net_realized_pnl_usdt": float(self.net_realized_pnl_usdt),
            "total_fees_usdt": float(self.total_fees_usdt),
            "profit_factor": round(self.profit_factor, 4)
            if self.profit_factor is not None
            else None,
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "holding_duration_avg_seconds": round(self.holding_duration_avg_seconds, 1),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssetAttribution:
        """Construct AssetAttribution from dictionary."""
        return cls(
            symbol=str(data.get("symbol", "")),
            trade_count=int(data.get("trade_count", 0)),
            winning_trades=int(data.get("winning_trades", 0)),
            losing_trades=int(data.get("losing_trades", 0)),
            breakeven_trades=int(data.get("breakeven_trades", 0)),
            win_rate_pct=float(data.get("win_rate_pct", 0.0)),
            gross_profit_usdt=_parse_decimal(data.get("gross_profit_usdt", "0.00")),
            gross_loss_usdt=_parse_decimal(data.get("gross_loss_usdt", "0.00")),
            net_realized_pnl_usdt=_parse_decimal(data.get("net_realized_pnl_usdt", "0.00")),
            total_fees_usdt=_parse_decimal(data.get("total_fees_usdt", "0.00")),
            profit_factor=float(data["profit_factor"])
            if data.get("profit_factor") is not None
            else None,
            max_drawdown_pct=float(data.get("max_drawdown_pct", 0.0)),
            holding_duration_avg_seconds=float(data.get("holding_duration_avg_seconds", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class CapitalState:
    """Reconciled capital, equity, and margin utilization state."""

    starting_cash_usdt: Decimal = Decimal("100.00")
    ending_cash_usdt: Decimal = Decimal("100.00")
    current_equity_usdt: Decimal = Decimal("100.00")
    peak_equity_usdt: Decimal = Decimal("100.00")
    net_realized_pnl_usdt: Decimal = Decimal("0.00")
    realized_pnl_pct: float = 0.0
    unrealized_pnl_usdt: Decimal = Decimal("0.00")
    margin_allocated_usdt: Decimal = Decimal("0.00")
    margin_utilization_pct: float = 0.0
    reserve_buffer_pct: float = 100.0

    def to_dict(self) -> dict[str, Any]:
        """Convert capital state to dictionary conforming to schema."""
        return {
            "starting_cash_usdt": float(self.starting_cash_usdt),
            "ending_cash_usdt": float(self.ending_cash_usdt),
            "current_equity_usdt": float(self.current_equity_usdt),
            "peak_equity_usdt": float(self.peak_equity_usdt),
            "net_realized_pnl_usdt": float(self.net_realized_pnl_usdt),
            "realized_pnl_pct": round(self.realized_pnl_pct, 2),
            "unrealized_pnl_usdt": float(self.unrealized_pnl_usdt),
            "margin_utilization_pct": round(self.margin_utilization_pct, 2),
            "reserve_buffer_pct": round(self.reserve_buffer_pct, 2),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapitalState:
        """Construct CapitalState from dictionary."""
        return cls(
            starting_cash_usdt=_parse_decimal(data.get("starting_cash_usdt", "100.00")),
            ending_cash_usdt=_parse_decimal(data.get("ending_cash_usdt", "100.00")),
            current_equity_usdt=_parse_decimal(data.get("current_equity_usdt", "100.00")),
            peak_equity_usdt=_parse_decimal(
                data.get("peak_equity_usdt", data.get("current_equity_usdt", "100.00"))
            ),
            net_realized_pnl_usdt=_parse_decimal(data.get("net_realized_pnl_usdt", "0.00")),
            realized_pnl_pct=float(data.get("realized_pnl_pct", 0.0)),
            unrealized_pnl_usdt=_parse_decimal(data.get("unrealized_pnl_usdt", "0.00")),
            margin_allocated_usdt=_parse_decimal(data.get("margin_allocated_usdt", "0.00")),
            margin_utilization_pct=float(data.get("margin_utilization_pct", 0.0)),
            reserve_buffer_pct=float(data.get("reserve_buffer_pct", 100.0)),
        )


@dataclass
class DailyPerformanceReport:
    """Complete institutional daily performance report model."""

    report_metadata: dict[str, Any]
    daemon_health: dict[str, Any]
    safety_invariants: dict[str, Any]
    capital_summary: dict[str, Any]
    portfolio_performance: dict[str, Any]
    asset_breakdown: dict[str, dict[str, Any]]
    asset_ranking: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Return canonical Draft-07 JSON serializable dictionary."""
        return {
            "report_metadata": self.report_metadata,
            "daemon_health": self.daemon_health,
            "safety_invariants": self.safety_invariants,
            "capital_summary": self.capital_summary,
            "portfolio_performance": self.portfolio_performance,
            "asset_breakdown": self.asset_breakdown,
            "asset_ranking": self.asset_ranking,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize report to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DailyPerformanceReport:
        """Construct DailyPerformanceReport from dictionary."""
        return cls(
            report_metadata=dict(data.get("report_metadata", {})),
            daemon_health=dict(data.get("daemon_health", {})),
            safety_invariants=dict(data.get("safety_invariants", {})),
            capital_summary=dict(data.get("capital_summary", {})),
            portfolio_performance=dict(data.get("portfolio_performance", {})),
            asset_breakdown=dict(data.get("asset_breakdown", {})),
            asset_ranking=list(data.get("asset_ranking", [])),
        )

    @classmethod
    def from_json(cls, json_str: str) -> DailyPerformanceReport:
        """Construct DailyPerformanceReport from serialized JSON string."""
        return cls.from_dict(json.loads(json_str))

    def get_capital_state(self) -> CapitalState:
        """Return typed CapitalState instance from capital_summary."""
        return CapitalState.from_dict(self.capital_summary)

    def get_performance_metrics(self) -> PerformanceMetrics:
        """Return typed PerformanceMetrics instance from portfolio_performance."""
        return PerformanceMetrics.from_dict(self.portfolio_performance)

    def get_asset_attributions(self) -> dict[str, AssetAttribution]:
        """Return typed dict of AssetAttribution instances from asset_breakdown."""
        return {sym: AssetAttribution.from_dict(d) for sym, d in self.asset_breakdown.items()}
