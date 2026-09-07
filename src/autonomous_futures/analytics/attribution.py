"""Per-asset performance attribution and portfolio ranking engine.

Partitions trade records by asset (BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT),
computes asset-specific metrics, and generates a performance ranking
sorted descending by net realized PnL.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from autonomous_futures.analytics.metrics import (
    calculate_drawdown_metrics,
    calculate_holding_duration_stats,
)
from autonomous_futures.analytics.models import AssetAttribution, TradeRecord

DEFAULT_PORTFOLIO_SYMBOLS: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
)


def calculate_asset_attribution(
    trades: Sequence[TradeRecord],
    symbols: Sequence[str] = DEFAULT_PORTFOLIO_SYMBOLS,
) -> dict[str, AssetAttribution]:
    """Compute performance attribution for each symbol in portfolio.

    Guarantees all requested symbols are present in the output dictionary,
    even if zero trades occurred for that symbol.
    """
    # Group trades by symbol
    trades_by_symbol: dict[str, list[TradeRecord]] = {sym: [] for sym in symbols}
    for t in trades:
        if t.symbol in trades_by_symbol:
            trades_by_symbol[t.symbol].append(t)
        else:
            trades_by_symbol.setdefault(t.symbol, []).append(t)

    attributions: dict[str, AssetAttribution] = {}

    for sym in symbols:
        sym_trades = trades_by_symbol.get(sym, [])
        count = len(sym_trades)

        if count == 0:
            attributions[sym] = AssetAttribution(
                symbol=sym,
                trade_count=0,
                winning_trades=0,
                losing_trades=0,
                breakeven_trades=0,
                win_rate_pct=0.0,
                gross_profit_usdt=Decimal("0.00"),
                gross_loss_usdt=Decimal("0.00"),
                net_realized_pnl_usdt=Decimal("0.00"),
                total_fees_usdt=Decimal("0.00"),
                profit_factor=None,
                max_drawdown_pct=0.0,
                holding_duration_avg_seconds=0.0,
            )
            continue

        wins = sum(1 for t in sym_trades if t.net_pnl > Decimal("0.00"))
        losses = sum(1 for t in sym_trades if t.net_pnl < Decimal("0.00"))
        breakevens = sum(1 for t in sym_trades if t.net_pnl == Decimal("0.00"))
        win_rate = (wins / count) * 100.0

        gross_profit = sum(
            (t.net_pnl for t in sym_trades if t.net_pnl > Decimal("0.00")),
            Decimal("0.00"),
        )
        gross_loss = sum(
            (-t.net_pnl for t in sym_trades if t.net_pnl < Decimal("0.00")),
            Decimal("0.00"),
        )
        net_pnl = sum((t.net_pnl for t in sym_trades), Decimal("0.00"))
        total_fees = sum((t.total_fees for t in sym_trades), Decimal("0.00"))

        if gross_loss > Decimal("0.00"):
            profit_factor = float(gross_profit / gross_loss)
        elif gross_loss == Decimal("0.00") and gross_profit > Decimal("0.00"):
            profit_factor = None
        elif gross_profit == Decimal("0.00") and gross_loss > Decimal("0.00"):
            profit_factor = 0.0
        else:
            profit_factor = None

        dur_stats = calculate_holding_duration_stats(sym_trades)
        _, max_dd_pct, _, _, _, _, _ = calculate_drawdown_metrics(sym_trades)

        attributions[sym] = AssetAttribution(
            symbol=sym,
            trade_count=count,
            winning_trades=wins,
            losing_trades=losses,
            breakeven_trades=breakevens,
            win_rate_pct=win_rate,
            gross_profit_usdt=gross_profit,
            gross_loss_usdt=gross_loss,
            net_realized_pnl_usdt=net_pnl,
            total_fees_usdt=total_fees,
            profit_factor=profit_factor,
            max_drawdown_pct=max_dd_pct,
            holding_duration_avg_seconds=dur_stats.avg,
        )

    return attributions


def calculate_performance_ranking(
    attributions: dict[str, AssetAttribution],
) -> list[str]:
    """Sort symbols descending by net realized PnL (best to worst)."""
    return sorted(
        attributions.keys(),
        key=lambda s: attributions[s].net_realized_pnl_usdt,
        reverse=True,
    )
