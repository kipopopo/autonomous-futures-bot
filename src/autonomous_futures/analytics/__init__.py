"""Autonomous Futures Bot: Quantitative Performance Analytics & Daily PnL Engine.

Provides institutional-grade performance attribution, risk-adjusted metrics
(rolling Sharpe, Sortino, Profit Factor, Maximum Drawdown, Win/Loss Payoff),
multi-asset decomposition across BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT,
automated daily performance JSON report persistence, and Telegram formatters.
"""

from __future__ import annotations

from autonomous_futures.analytics.attribution import (
    DEFAULT_PORTFOLIO_SYMBOLS,
    calculate_asset_attribution,
    calculate_performance_ranking,
)
from autonomous_futures.analytics.formatter import (
    format_analytics_command_reply,
    format_daily_performance_report,
    format_duration,
)
from autonomous_futures.analytics.ledger_reader import ReadOnlyLedgerReader
from autonomous_futures.analytics.metrics import (
    calculate_drawdown_metrics,
    calculate_execution_slippage_stats,
    calculate_holding_duration_stats,
    calculate_performance_metrics,
)
from autonomous_futures.analytics.models import (
    AssetAttribution,
    CapitalState,
    DailyPerformanceReport,
    ExecutionSlippageStats,
    HoldingDurationStats,
    PerformanceMetrics,
    TradeRecord,
)
from autonomous_futures.analytics.reporter import (
    generate_and_persist_daily_report,
    generate_daily_performance_report,
)

__all__ = [
    "DEFAULT_PORTFOLIO_SYMBOLS",
    "AssetAttribution",
    "CapitalState",
    "DailyPerformanceReport",
    "ExecutionSlippageStats",
    "HoldingDurationStats",
    "PerformanceMetrics",
    "ReadOnlyLedgerReader",
    "TradeRecord",
    "calculate_asset_attribution",
    "calculate_drawdown_metrics",
    "calculate_execution_slippage_stats",
    "calculate_holding_duration_stats",
    "calculate_performance_metrics",
    "calculate_performance_ranking",
    "format_analytics_command_reply",
    "format_daily_performance_report",
    "format_duration",
    "generate_and_persist_daily_report",
    "generate_daily_performance_report",
]
