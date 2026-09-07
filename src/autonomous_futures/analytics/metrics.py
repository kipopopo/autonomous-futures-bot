"""Institutional quantitative performance and risk analytics engine.

Computes 10 quantitative risk and performance metric categories with exact
Decimal precision and complete edge-case handling (zero trades, zero losses,
zero variance, zero drawdown).
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from autonomous_futures.analytics.models import (
    ExecutionSlippageStats,
    HoldingDurationStats,
    PerformanceMetrics,
    TradeRecord,
)


def calculate_holding_duration_stats(trades: Sequence[TradeRecord]) -> HoldingDurationStats:
    """Calculate mean, median, min, and max holding durations in seconds."""
    if not trades:
        return HoldingDurationStats()
    durations = [t.holding_duration_seconds for t in trades]
    return HoldingDurationStats(
        avg=float(sum(durations) / len(durations)),
        median=float(statistics.median(durations)),
        min=float(min(durations)),
        max=float(max(durations)),
    )


def calculate_execution_slippage_stats(trades: Sequence[TradeRecord]) -> ExecutionSlippageStats:
    """Calculate execution slippage cost and basis point statistics."""
    if not trades:
        return ExecutionSlippageStats()

    total_cost = sum((t.slippage_cost for t in trades), Decimal("0.00"))
    bps_list: list[float] = []

    for t in trades:
        notional = (t.entry_price * t.quantity) + (t.exit_price * t.quantity)
        if notional > Decimal("0"):
            bps = float((t.slippage_cost / notional) * Decimal("10000"))
            bps_list.append(bps)
        else:
            bps_list.append(0.0)

    avg_bps = float(sum(bps_list) / len(bps_list)) if bps_list else 0.0
    max_bps = float(max(bps_list)) if bps_list else 0.0

    return ExecutionSlippageStats(
        total_slippage_cost_usdt=float(total_cost),
        average_slippage_bps=avg_bps,
        max_slippage_bps=max_bps,
    )


def calculate_drawdown_metrics(
    trades: Sequence[TradeRecord],
    starting_capital: Decimal = Decimal("100.00"),
) -> tuple[Decimal, float, datetime | None, datetime | None, float | None, float | None, bool]:
    """Calculate maximum peak-to-trough drawdown in dollars and percent with timestamps.

    Returns:
        (max_drawdown_amount, max_drawdown_pct, peak_time, trough_time,
         drawdown_duration_seconds, recovery_duration_seconds, is_recovered)
    """
    if not trades:
        return Decimal("0.00"), 0.0, None, None, None, None, True

    # Build chronological equity curve
    # Each point: (timestamp, equity)
    equity_points: list[tuple[datetime, Decimal]] = []
    current_equity = starting_capital
    first_time = trades[0].opened_at
    equity_points.append((first_time, current_equity))

    for t in trades:
        current_equity += t.net_pnl
        equity_points.append((t.closed_at, current_equity))

    high_water_mark = starting_capital
    peak_time_candidate = first_time

    max_dd_amount = Decimal("0.00")
    max_dd_pct = 0.0
    best_peak_time: datetime | None = None
    best_trough_time: datetime | None = None
    trough_idx: int = 0

    for idx, (t_time, eq) in enumerate(equity_points):
        if eq > high_water_mark:
            high_water_mark = eq
            peak_time_candidate = t_time
        else:
            dd_amount = high_water_mark - eq
            if dd_amount > max_dd_amount:
                max_dd_amount = dd_amount
                max_dd_pct = (
                    float(dd_amount / high_water_mark * Decimal("100"))
                    if high_water_mark > Decimal("0")
                    else 0.0
                )
                best_peak_time = peak_time_candidate
                best_trough_time = t_time
                trough_idx = idx

    if max_dd_amount <= Decimal("0.00") or best_peak_time is None or best_trough_time is None:
        return Decimal("0.00"), 0.0, None, None, None, None, True

    # Check recovery after trough
    recovery_time: datetime | None = None
    peak_equity_at_mdd = starting_capital
    for t_time, eq in equity_points:
        if t_time == best_peak_time:
            peak_equity_at_mdd = eq
            break

    for idx in range(trough_idx + 1, len(equity_points)):
        t_time, eq = equity_points[idx]
        if eq >= peak_equity_at_mdd:
            recovery_time = t_time
            break

    dd_duration = max(0.0, (best_trough_time - best_peak_time).total_seconds())
    recovery_duration = (
        max(0.0, (recovery_time - best_trough_time).total_seconds())
        if recovery_time is not None
        else None
    )
    is_recovered = recovery_time is not None

    return (
        max_dd_amount,
        max_dd_pct,
        best_peak_time,
        best_trough_time,
        dd_duration,
        recovery_duration,
        is_recovered,
    )


def calculate_performance_metrics(
    trades: Sequence[TradeRecord],
    starting_capital: Decimal = Decimal("100.00"),
    annualization_days: float = 365.0,
) -> PerformanceMetrics:
    """Calculate full quantitative performance and risk metrics.

    Handles all mathematical edge cases (zero trades, zero losses, zero variance,
    zero drawdown) returning None or 0.0 where appropriate without division by zero.
    """
    total_trades = len(trades)
    if total_trades == 0:
        return PerformanceMetrics()

    winning_trades = sum(1 for t in trades if t.net_pnl > Decimal("0.00"))
    losing_trades = sum(1 for t in trades if t.net_pnl < Decimal("0.00"))
    breakeven_trades = sum(1 for t in trades if t.net_pnl == Decimal("0.00"))
    win_rate_pct = (winning_trades / total_trades) * 100.0

    gross_profit = sum((t.net_pnl for t in trades if t.net_pnl > Decimal("0.00")), Decimal("0.00"))
    gross_loss = sum((-t.net_pnl for t in trades if t.net_pnl < Decimal("0.00")), Decimal("0.00"))
    net_pnl = sum((t.net_pnl for t in trades), Decimal("0.00"))
    total_fees_paid = sum((t.total_fees for t in trades), Decimal("0.00"))

    # Fee drag ratio
    if gross_profit > Decimal("0.00"):
        fee_drag_ratio = float(total_fees_paid / gross_profit)
    else:
        fee_drag_ratio = None

    # Profit factor
    if gross_loss > Decimal("0.00"):
        profit_factor = float(gross_profit / gross_loss)
    elif gross_loss == Decimal("0.00") and gross_profit > Decimal("0.00"):
        profit_factor = None  # Infinite profit factor
    elif gross_profit == Decimal("0.00") and gross_loss > Decimal("0.00"):
        profit_factor = 0.0
    else:
        profit_factor = None

    # Win/Loss payoff and averages
    average_win = (gross_profit / Decimal(winning_trades)) if winning_trades > 0 else None
    average_loss = (gross_loss / Decimal(losing_trades)) if losing_trades > 0 else None

    if average_win is not None and average_loss is not None and average_loss > Decimal("0.00"):
        payoff_ratio = float(average_win / average_loss)
    elif average_win is not None and (average_loss is None or average_loss == Decimal("0.00")):
        payoff_ratio = None
    elif average_loss is not None and average_win is None:
        payoff_ratio = 0.0
    else:
        payoff_ratio = None

    # Expectancy ($/trade)
    expectancy = (net_pnl / Decimal(total_trades)) if total_trades > 0 else Decimal("0.00")
    expectancy_ratio = (
        float(expectancy / average_loss)
        if (average_loss is not None and average_loss > Decimal("0.00") and expectancy is not None)
        else None
    )

    # Holding durations & Slippage
    duration_stats = calculate_holding_duration_stats(trades)
    slippage_stats = calculate_execution_slippage_stats(trades)

    # Drawdown metrics
    (
        max_dd_amount,
        max_dd_pct,
        peak_time,
        trough_time,
        dd_duration_sec,
        recovery_duration_sec,
        is_recovered,
    ) = calculate_drawdown_metrics(trades, starting_capital=starting_capital)

    # Return rates for Sharpe and Sortino
    returns: list[float] = []
    for t in trades:
        notional = t.entry_price * t.quantity
        if notional > Decimal("0.00"):
            ret = float(t.net_pnl / notional)
        else:
            ret = float(t.net_pnl / starting_capital)
        returns.append(ret)

    # Sharpe and Sortino calculations
    sharpe_trade: float | None = None
    sharpe_annualized: float | None = None
    sortino_ratio: float | None = None

    # Time span for annualization
    start_dt = trades[0].opened_at
    end_dt = trades[-1].closed_at
    timespan_days = max((end_dt - start_dt).total_seconds() / 86400.0, 1.0 / 288.0)  # at least 5m
    annual_trade_multiplier = max(1.0, (total_trades / timespan_days) * annualization_days)

    if total_trades >= 2:
        mean_ret = float(statistics.mean(returns))
        try:
            stdev_ret = float(statistics.stdev(returns))
        except statistics.StatisticsError:
            stdev_ret = 0.0

        if stdev_ret > 1e-12:
            sharpe_trade = mean_ret / stdev_ret
            sharpe_annualized = sharpe_trade * math.sqrt(annual_trade_multiplier)

        # Sortino downside semi-deviation (MAR = 0.0)
        downside_squared = [min(0.0, r) ** 2 for r in returns]
        downside_dev = math.sqrt(sum(downside_squared) / total_trades)
        if downside_dev > 1e-12:
            sortino_trade = mean_ret / downside_dev
            sortino_ratio = sortino_trade * math.sqrt(annual_trade_multiplier)

    # Calmar Ratio and Recovery Factor
    if max_dd_pct > 0.0:
        total_return_pct = float(net_pnl / starting_capital * Decimal("100"))
        annualized_return_pct = total_return_pct * (annualization_days / max(timespan_days, 0.01))
        calmar_ratio = annualized_return_pct / max_dd_pct
    else:
        calmar_ratio = None

    if max_dd_amount > Decimal("0.00"):
        recovery_factor = float(net_pnl / max_dd_amount)
    else:
        recovery_factor = None

    return PerformanceMetrics(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        breakeven_trades=breakeven_trades,
        win_rate_pct=win_rate_pct,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_pnl=net_pnl,
        profit_factor=profit_factor,
        sharpe_ratio_trade=sharpe_trade,
        sharpe_ratio_annualized=sharpe_annualized,
        sortino_ratio=sortino_ratio,
        max_drawdown_amount=max_dd_amount,
        max_drawdown_pct=max_dd_pct,
        max_drawdown_peak_time=peak_time,
        max_drawdown_trough_time=trough_time,
        max_drawdown_duration_seconds=dd_duration_sec,
        recovery_duration_seconds=recovery_duration_sec,
        is_drawdown_recovered=is_recovered,
        calmar_ratio=calmar_ratio,
        recovery_factor=recovery_factor,
        average_win=average_win,
        average_loss=average_loss,
        payoff_ratio=payoff_ratio,
        expectancy=expectancy,
        expectancy_ratio=expectancy_ratio,
        total_fees_paid=total_fees_paid,
        fee_drag_ratio=fee_drag_ratio,
        holding_duration_mean_seconds=duration_stats.avg,
        holding_duration_median_seconds=duration_stats.median,
        holding_duration_min_seconds=duration_stats.min,
        holding_duration_max_seconds=duration_stats.max,
        total_slippage_cost=Decimal(str(round(slippage_stats.total_slippage_cost_usdt, 4))),
        average_slippage_bps=slippage_stats.average_slippage_bps,
        max_slippage_bps=slippage_stats.max_slippage_bps,
    )
