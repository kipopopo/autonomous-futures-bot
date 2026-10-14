"""Build authentic post-trade autopsies and self-learning feedback from verified fills.

Every metric is derived strictly from persisted authenticated userTrades fill summaries
(`fill_summaries`) and closed-candle exit observations (`exit_observation`).
No synthetic fill prices, commissions, or Hawkes numbers are ever invented.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from autonomous_futures.execution.account_evidence import finite_decimal
from autonomous_futures.execution.trade_plan import TradePlan

D = Decimal


def _content_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def build_closed_trade_autopsy(
    plan: TradePlan,
    trade: dict[str, Any],
    *,
    closed_ms: int,
    daily_breached: bool = False,
    external_risk_breach: bool = False,
) -> dict[str, Any]:
    """Summarize a closed owned trade strictly from its authenticated fill summaries."""
    entry_id = str(trade["entry_id"])
    summaries: dict[str, dict[str, Any]] = trade.get("fill_summaries", {})
    entry_summary = summaries.get(entry_id)

    entry_qty = (
        finite_decimal(entry_summary["quantity"])
        if entry_summary is not None and "quantity" in entry_summary
        else D("0")
    )
    if entry_qty <= 0:
        autopsy: dict[str, Any] = {
            "schema": "runtime-trade-autopsy-v1",
            "signal_key": plan.signal_key,
            "family": plan.family,
            "symbol": plan.symbol,
            "side": plan.side,
            "entry_id": entry_id,
            "status": "UNFILLED_OR_CANCELLED",
            "closed_ms": closed_ms,
            "executed_quantity": "0",
            "execution_authority": False,
        }
        autopsy["autopsy_hash"] = _content_hash(autopsy)
        return autopsy

    assert entry_summary is not None
    entry_quote = finite_decimal(entry_summary["quote_quantity"])
    entry_fee = finite_decimal(entry_summary["commission_usdt"])
    entry_avg_price = entry_quote / entry_qty
    first_fill_ms = entry_summary.get("first_fill_ms")

    exit_qty = D("0")
    exit_quote = D("0")
    exit_fee = D("0")
    exchange_realized_pnl = finite_decimal(entry_summary.get("realized_pnl_usdt", "0"))
    last_fill_ms: int | None = entry_summary.get("last_fill_ms")
    filled_exit_roles: list[str] = []

    for cid, summary in sorted(summaries.items()):
        if cid == entry_id:
            continue
        qty = finite_decimal(summary.get("quantity", "0"))
        if qty <= 0:
            continue
        exit_qty += qty
        exit_quote += finite_decimal(summary.get("quote_quantity", "0"))
        exit_fee += finite_decimal(summary.get("commission_usdt", "0"))
        exchange_realized_pnl += finite_decimal(summary.get("realized_pnl_usdt", "0"))
        fill_end = summary.get("last_fill_ms")
        if isinstance(fill_end, int) and (last_fill_ms is None or fill_end > last_fill_ms):
            last_fill_ms = fill_end
        for role_prefix in ("STOP", "TP1", "TP2", "FLATTEN"):
            if role_prefix.lower() in cid.lower() and role_prefix not in filled_exit_roles:
                filled_exit_roles.append(role_prefix)

    sign = D("1") if plan.side == "BUY" else D("-1")
    exit_avg_price = (exit_quote / exit_qty) if exit_qty > 0 else entry_avg_price
    computed_gross_pnl = sign * (exit_avg_price - entry_avg_price) * min(entry_qty, exit_qty)
    gross_pnl = exchange_realized_pnl if exchange_realized_pnl != 0 else computed_gross_pnl
    total_fees = entry_fee + exit_fee
    net_pnl = gross_pnl - total_fees

    # Basis-point attribution from authentic fill prices vs planned entry
    entry_slippage_bps = (
        sign * (entry_avg_price - plan.entry) / plan.entry * D("10000")
        if plan.entry > 0
        else D("0")
    )
    realized_edge_bps = net_pnl / entry_quote * D("10000") if entry_quote > 0 else D("0")
    hold_duration_ms = (
        max(0, last_fill_ms - first_fill_ms)
        if isinstance(first_fill_ms, int) and isinstance(last_fill_ms, int)
        else None
    )

    strategy_invalidated = bool(trade.get("strategy_invalidated", False))
    if net_pnl > 0:
        attribution_cause = "ORGANIC_ALPHA"
    elif daily_breached or external_risk_breach:
        attribution_cause = "RISK_CIRCUIT_FLATTEN"
    elif strategy_invalidated:
        attribution_cause = "STRATEGY_INVALIDATION"
    elif "STOP" in filled_exit_roles:
        attribution_cause = "STOP_LOSS_REGIME_MISMATCH"
    elif entry_slippage_bps > D("5"):
        attribution_cause = "ENTRY_SLIPPAGE_DRAG"
    else:
        attribution_cause = "TIME_DECAY_OR_FEE_DRAG"

    autopsy = {
        "schema": "runtime-trade-autopsy-v1",
        "source": "binance_authenticated_user_trades",
        "signal_key": plan.signal_key,
        "family": plan.family,
        "symbol": plan.symbol,
        "side": plan.side,
        "entry_id": entry_id,
        "status": "FILLED_AND_CLOSED",
        "planned_entry": str(plan.entry),
        "planned_stop": str(plan.stop),
        "planned_tp1": str(plan.tp1),
        "planned_tp2": str(plan.tp2) if plan.tp2 is not None else None,
        "executed_quantity": str(entry_qty),
        "closed_quantity": str(exit_qty),
        "entry_average_price": str(entry_avg_price),
        "exit_average_price": str(exit_avg_price),
        "entry_quote_notional_usdt": str(entry_quote),
        "exit_quote_notional_usdt": str(exit_quote),
        "gross_pnl_usdt": str(gross_pnl),
        "commission_usdt": str(total_fees),
        "net_pnl_usdt": str(net_pnl),
        "entry_slippage_bps": str(entry_slippage_bps),
        "realized_edge_bps": str(realized_edge_bps),
        "first_fill_ms": first_fill_ms,
        "last_fill_ms": last_fill_ms,
        "hold_duration_ms": hold_duration_ms,
        "closed_ms": closed_ms,
        "filled_exit_roles": filled_exit_roles,
        "strategy_invalidated": strategy_invalidated,
        "exit_observation": trade.get("exit_observation"),
        "attribution_cause": attribution_cause,
        "execution_authority": False,
    }
    autopsy["autopsy_hash"] = _content_hash(autopsy)
    return autopsy


_DEFAULT_MIN_PROFIT_FACTOR = D("1.10")


def summarize_autopsy_feedback(
    autopsies: list[dict[str, Any]],
    *,
    symbol: str | None = None,
    min_profit_factor: Decimal = _DEFAULT_MIN_PROFIT_FACTOR,
    min_trades: int = 5,
) -> dict[str, Any]:
    """Aggregate fill-verified trade autopsies into structured self-learning feedback."""
    filled = [
        item
        for item in autopsies
        if item.get("status") == "FILLED_AND_CLOSED"
        and (symbol is None or item.get("symbol") == symbol)
    ]
    profits = sum((max(D(str(item["net_pnl_usdt"])), D("0")) for item in filled), D("0"))
    losses = sum((max(-D(str(item["net_pnl_usdt"])), D("0")) for item in filled), D("0"))
    net_pnl = profits - losses
    wins = sum(1 for item in filled if D(str(item["net_pnl_usdt"])) > 0)
    trade_count = len(filled)
    win_rate_pct = (D(wins) / D(trade_count) * D("100")) if trade_count > 0 else D("0")
    profit_factor = (profits / losses) if losses > 0 else (D("999") if profits > 0 else D("0"))

    causes: dict[str, int] = {}
    for item in filled:
        cause = str(item.get("attribution_cause", "UNKNOWN"))
        causes[cause] = causes.get(cause, 0) + 1

    failure_reason_codes: list[str] = []
    if trade_count < min_trades:
        failure_reason_codes.append("insufficient_closed_trade_sample")
    if net_pnl <= 0:
        failure_reason_codes.append("negative_or_zero_net_pnl")
    if trade_count > 0 and (losses > 0 and profit_factor < min_profit_factor or profits == 0):
        failure_reason_codes.append("profit_factor_below_threshold")
    if causes.get("STOP_LOSS_REGIME_MISMATCH", 0) > wins:
        failure_reason_codes.append("stop_loss_regime_mismatch_cluster")
    if causes.get("TIME_DECAY_OR_FEE_DRAG", 0) > wins:
        failure_reason_codes.append("time_decay_or_fee_drag_cluster")

    summary: dict[str, Any] = {
        "schema": "runtime-autopsy-feedback-summary-v1",
        "symbol": symbol,
        "trade_count": trade_count,
        "win_count": wins,
        "win_rate_pct": str(win_rate_pct),
        "gross_profit_usdt": str(profits),
        "gross_loss_usdt": str(losses),
        "net_pnl_usdt": str(net_pnl),
        "profit_factor": str(profit_factor),
        "attribution_causes": dict(sorted(causes.items())),
        "failure_reason_codes": sorted(set(failure_reason_codes)),
        "needs_revision": any(
            code != "insufficient_closed_trade_sample" for code in failure_reason_codes
        ),
        "execution_authority": False,
    }
    summary["summary_hash"] = _content_hash(summary)
    return summary
