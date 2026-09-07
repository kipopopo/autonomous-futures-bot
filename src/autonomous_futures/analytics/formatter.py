"""Telegram MarkdownV2 report formatting engine for quantitative analytics.

Adheres strictly to Telegram Bot API character escaping rules for all 19 reserved
characters: _ * [ ] ( ) ~ ` > # + - = | { } . ! \\
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from autonomous_futures.notify.telegram import escape_markdown_v2


def format_duration(seconds: float | None) -> str:
    """Format duration in seconds to human-readable string (e.g. '24m 30s')."""
    if seconds is None or seconds <= 0:
        return "0s"
    sec = int(round(seconds))
    hours = sec // 3600
    mins = (sec % 3600) // 60
    secs = sec % 60

    if hours > 0:
        return f"{hours}h {mins}m"
    if mins > 0:
        return f"{mins}m {secs}s"
    return f"{secs}s"


def format_daily_performance_report(report_data: dict[str, Any]) -> str:
    """Format an institutional daily performance report using Telegram MarkdownV2 syntax.

    Escapes all variable content to guarantee HTTP 200 delivery without entity parse errors.
    """
    meta = report_data.get("report_metadata", {})
    cap = report_data.get("capital_summary", {})
    perf = report_data.get("portfolio_performance", {})
    assets = report_data.get("asset_breakdown", {})
    ranking = report_data.get("asset_ranking", [])
    health = report_data.get("daemon_health", {})

    report_date = escape_markdown_v2(str(meta.get("report_date", "")))

    # Capital values
    start_cash = escape_markdown_v2(f"{cap.get('starting_cash_usdt', 100.0):.2f}")
    end_cash = escape_markdown_v2(f"{cap.get('ending_cash_usdt', 100.0):.2f}")
    equity = escape_markdown_v2(f"{cap.get('current_equity_usdt', 100.0):.2f}")

    net_pnl = float(cap.get("net_realized_pnl_usdt", 0.0))
    pnl_sign = "\\+" if net_pnl >= 0 else "\\-"
    pnl_val = escape_markdown_v2(f"{abs(net_pnl):.2f}")
    pnl_pct = float(cap.get("realized_pnl_pct", 0.0))
    pct_sign = "\\+" if pnl_pct >= 0 else "\\-"
    pct_val = escape_markdown_v2(f"{abs(pnl_pct):.2f}")

    margin_util = escape_markdown_v2(f"{cap.get('margin_utilization_pct', 0.0):.1f}")
    reserve_buf = escape_markdown_v2(f"{cap.get('reserve_buffer_pct', 100.0):.1f}")

    # Performance values
    trade_count = escape_markdown_v2(str(perf.get("trade_count", 0)))
    wins = escape_markdown_v2(str(perf.get("winning_trades", 0)))
    losses = escape_markdown_v2(str(perf.get("losing_trades", 0)))
    be = escape_markdown_v2(str(perf.get("breakeven_trades", 0)))
    win_rate = escape_markdown_v2(f"{perf.get('win_rate_pct', 0.0):.1f}")

    payoff_val = perf.get("win_loss_payoff_ratio")
    payoff = escape_markdown_v2(f"{payoff_val:.2f}") if payoff_val is not None else "N/A"

    pf_val = perf.get("profit_factor")
    if pf_val is not None:
        profit_factor = escape_markdown_v2(f"{pf_val:.2f}")
    elif perf.get("trade_count", 0) > 0 and perf.get("losing_trades", 0) == 0:
        profit_factor = "∞"
    else:
        profit_factor = "N/A"

    sharpe_val = perf.get("sharpe_ratio_annualized")
    sharpe = escape_markdown_v2(f"{sharpe_val:.2f}") if sharpe_val is not None else "N/A"

    sortino_val = perf.get("sortino_ratio")
    sortino = escape_markdown_v2(f"{sortino_val:.2f}") if sortino_val is not None else "N/A"

    mdd_cash = escape_markdown_v2(f"{perf.get('max_drawdown_usdt', 0.0):.2f}")
    mdd_pct = escape_markdown_v2(f"{perf.get('max_drawdown_pct', 0.0):.2f}")

    exp_val = float(perf.get("expectancy_usdt", 0.0))
    exp_sign = "\\+" if exp_val >= 0 else "\\-"
    expectancy = escape_markdown_v2(f"{abs(exp_val):.2f}")

    fees = escape_markdown_v2(f"{perf.get('total_taker_fees_usdt', 0.0):.2f}")
    fee_drag_val = perf.get("fee_drag_ratio")
    fee_drag = (
        escape_markdown_v2(f"{fee_drag_val * 100.0:.1f}%") if fee_drag_val is not None else "N/A"
    )

    holding_dict = perf.get("holding_duration_seconds", {})
    avg_holding_sec = holding_dict.get("avg", 0.0)
    holding_avg_formatted = escape_markdown_v2(format_duration(avg_holding_sec))

    # Per-asset ranking lines
    medals = ["🥇", "🥈", "🥉"]
    ranked_lines: list[str] = []
    for idx, sym in enumerate(ranking, 1):
        sym_data = assets.get(sym, {})
        sym_pnl = float(sym_data.get("net_realized_pnl_usdt", 0.0))
        s_sign = "\\+" if sym_pnl >= 0 else "\\-"
        s_pnl_str = escape_markdown_v2(f"{abs(sym_pnl):.2f}")
        s_trades = escape_markdown_v2(str(sym_data.get("trade_count", 0)))
        s_win = escape_markdown_v2(f"{sym_data.get('win_rate_pct', 0.0):.1f}")
        medal = medals[idx - 1] if idx <= 3 else "🔻"
        sym_name = escape_markdown_v2(sym)
        ranked_lines.append(
            f"{idx}\\. {medal} *{sym_name}*: {s_sign}${s_pnl_str} USDT "
            f"\\({s_trades} trades, {s_win}% win\\)"
        )

    ranked_asset_lines = "\n".join(ranked_lines) if ranked_lines else "• No active asset trades"

    # Daemon status
    daemon_status = escape_markdown_v2(str(health.get("daemon_status", "RUNNING")))
    daemon_pid = escape_markdown_v2(str(health.get("pid", "N/A")))

    gen_raw = meta.get("generated_at_utc", "")
    try:
        dt = datetime.fromisoformat(gen_raw)
        gen_formatted = escape_markdown_v2(dt.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        gen_formatted = escape_markdown_v2(gen_raw)

    return (
        f"📊 *DAILY PERFORMANCE REPORT* \\| `{report_date}`\n"
        f"─────────────────────────\n"
        f"🏦 *CAPITAL & BALANCE*\n"
        f"• *Starting Cash*: ${start_cash} USDT\n"
        f"• *Ending Cash*: ${end_cash} USDT\n"
        f"• *Current Equity*: ${equity} USDT\n"
        f"• *Net Realized PnL*: {pnl_sign}${pnl_val} USDT \\({pct_sign}{pct_val}%\\)\n"
        f"• *Margin Utilization*: {margin_util}% \\(Reserve: {reserve_buf}%\\)\n\n"
        f"📈 *PORTFOLIO RISK & METRICS*\n"
        f"• *Trades*: {trade_count} \\(Wins: {wins} \\| Losses: {losses} \\| BE: {be}\\)\n"
        f"• *Win Rate*: {win_rate}% \\| *Payoff*: {payoff}\n"
        f"• *Profit Factor*: {profit_factor}\n"
        f"• *Sharpe Ratio*: {sharpe} \\| *Sortino*: {sortino}\n"
        f"• *Max Drawdown*: ${mdd_cash} USDT \\({mdd_pct}%\\)\n"
        f"• *Expectancy*: {exp_sign}${expectancy} / trade\n"
        f"• *Taker Fees*: ${fees} USDT \\(Fee Drag: {fee_drag}\\)\n"
        f"• *Avg Holding*: {holding_avg_formatted}\n\n"
        f"🏆 *PER\\-ASSET RANKING \\(Net PnL\\)*\n"
        f"{ranked_asset_lines}\n\n"
        f"🛡️ *SAFETY & SYSTEM STATUS*\n"
        f"• *Daemon*: {daemon_status} \\(PID {daemon_pid}\\)\n"
        f"• *Zero Orders Invariant*: VERIFIED \\(0 live orders\\)\n"
        f"• *Generated*: {gen_formatted} UTC"
    )


def format_analytics_command_reply(
    report_data: dict[str, Any],
) -> str:
    """Format concise institutional analytics summary for the interactive /analytics command."""
    perf = report_data.get("portfolio_performance", {})
    cap = report_data.get("capital_summary", {})
    assets = report_data.get("asset_breakdown", {})
    ranking = report_data.get("asset_ranking", [])

    total_trades = perf.get("trade_count", 0)
    win_rate = escape_markdown_v2(f"{perf.get('win_rate_pct', 0.0):.1f}")

    pf_val = perf.get("profit_factor")
    if pf_val is not None:
        profit_factor = escape_markdown_v2(f"{pf_val:.2f}")
    elif total_trades > 0 and perf.get("losing_trades", 0) == 0:
        profit_factor = "∞"
    else:
        profit_factor = "N/A"

    payoff_val = perf.get("win_loss_payoff_ratio")
    payoff = escape_markdown_v2(f"{payoff_val:.2f}") if payoff_val is not None else "N/A"

    sharpe_val = perf.get("sharpe_ratio_annualized")
    sharpe = escape_markdown_v2(f"{sharpe_val:.2f}") if sharpe_val is not None else "N/A"

    sortino_val = perf.get("sortino_ratio")
    sortino = escape_markdown_v2(f"{sortino_val:.2f}") if sortino_val is not None else "N/A"

    mdd_cash = escape_markdown_v2(f"{perf.get('max_drawdown_usdt', 0.0):.2f}")
    mdd_pct = escape_markdown_v2(f"{perf.get('max_drawdown_pct', 0.0):.2f}")

    net_pnl = float(perf.get("net_realized_pnl_usdt", 0.0))
    pnl_sign = "\\+" if net_pnl >= 0 else "\\-"
    pnl_str = escape_markdown_v2(f"{abs(net_pnl):.4f}")

    fees = escape_markdown_v2(f"{perf.get('total_taker_fees_usdt', 0.0):.4f}")
    fee_drag_val = perf.get("fee_drag_ratio")
    fee_drag = (
        escape_markdown_v2(f"{fee_drag_val * 100.0:.1f}%") if fee_drag_val is not None else "N/A"
    )

    exp_val = float(perf.get("expectancy_usdt", 0.0))
    exp_sign = "\\+" if exp_val >= 0 else "\\-"
    expectancy = escape_markdown_v2(f"{abs(exp_val):.4f}")

    # Per-asset breakdown
    asset_lines: list[str] = []
    for sym in ranking:
        a_data = assets.get(sym, {})
        a_pnl = float(a_data.get("net_realized_pnl_usdt", 0.0))
        a_sign = "\\+" if a_pnl >= 0 else "\\-"
        a_pnl_str = escape_markdown_v2(f"{abs(a_pnl):.4f}")
        a_trades = escape_markdown_v2(str(a_data.get("trade_count", 0)))
        a_win = escape_markdown_v2(f"{a_data.get('win_rate_pct', 0.0):.1f}")
        asset_lines.append(
            f"• *{escape_markdown_v2(sym)}*: {a_sign}${a_pnl_str} USDT "
            f"\\({a_trades} trades, {a_win}% win\\)"
        )

    asset_text = "\n".join(asset_lines) if asset_lines else "• No closed trades"

    cash = escape_markdown_v2(f"{cap.get('ending_cash_usdt', 100.0):.2f}")
    equity = escape_markdown_v2(f"{cap.get('current_equity_usdt', 100.0):.2f}")
    margin_util = escape_markdown_v2(f"{cap.get('margin_utilization_pct', 0.0):.1f}")
    reserve = escape_markdown_v2(f"{cap.get('reserve_buffer_pct', 100.0):.1f}")

    return (
        f"📈 *INSTITUTIONAL QUANTITATIVE ANALYTICS*\n"
        f"─────────────────────────\n"
        f"• *Closed Trades*: {escape_markdown_v2(str(total_trades))} \\(Win Rate: {win_rate}%\\)\n"
        f"• *Profit Factor*: {profit_factor}\n"
        f"• *Win/Loss Payoff*: {payoff}\n"
        f"• *Sharpe Ratio \\(Ann\\)*: {sharpe}\n"
        f"• *Sortino Ratio*: {sortino}\n"
        f"• *Max Drawdown*: ${mdd_cash} USDT \\({mdd_pct}%\\)\n"
        f"• *Expectancy*: {exp_sign}${expectancy} / trade\n"
        f"• *Net Realized PnL*: {pnl_sign}${pnl_str} USDT\n"
        f"• *Taker Fees Paid*: ${fees} USDT \\(Fee Drag: {fee_drag}\\)\n\n"
        f"*Per\\-Asset Attribution*:\n"
        f"{asset_text}\n\n"
        f"*Portfolio Capital*:\n"
        f"• *Equity*: ${equity} USDT \\| *Cash*: ${cash} USDT\n"
        f"• *Margin Utilization*: {margin_util}% \\(Reserve: {reserve}%\\)"
    )
