"""Chronological recorded-market qualification of the actual ICT core and trade planner.

All executions here are explicitly modeled from observed OHLCV, not exchange fills.
"""

from __future__ import annotations

import bisect
import dataclasses
import json
from collections import deque
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

from autonomous_futures.execution.daily_risk import DailyRisk
from autonomous_futures.execution.trade_plan import (
    IneligibleTrade,
    SymbolFilters,
    TradePlan,
    build_plan,
    ict_plan,
)
from autonomous_futures.research.official_market_data import official_minutes
from autonomous_futures.research.runtime_qualification import (
    RuntimeQualificationPolicy,
    content_hash,
    digest,
    four_hour_bars,
    load_funding,
    repo_relative_source_path,
    source_file_index,
    verified_bars,
)
from autonomous_futures.strategy.ict_mmxm import Candle, IctMmxmEngine, StopLossMode

D = Decimal
EntryMode = Literal["limit_touch", "reclaim_retest"]
InvalidationMode = Literal["entry_close", "stop_only"]
TimeFilterMode = Literal[
    "all_hours",
    "killzones",
    "twins_windows",
    "manipulation_distribution",
]


def has_close_reclaim(bar: Candle, plan: TradePlan) -> bool:
    """Whether a touched CISD line was reclaimed at the completed one-minute close."""
    if plan.side == "BUY":
        touched = bar.low < plan.entry
        reclaimed = bar.close > plan.entry
    else:
        touched = bar.high > plan.entry
        reclaimed = bar.close < plan.entry
    return touched and reclaimed


def has_post_reclaim_limit_fill(bar: Candle, plan: TradePlan) -> bool:
    """Require a future trade-through after a maker limit can actually be resting."""
    if plan.side == "BUY":
        return bar.low < plan.entry < bar.open
    return bar.high > plan.entry > bar.open


@dataclasses.dataclass
class ModeledTrade:
    plan: TradePlan
    window: int
    entry_ms: int | None = None
    reclaim_ms: int | None = None
    remaining: Decimal = D("0")
    tp1_remaining: Decimal = D("0")
    gross: Decimal = D("0")
    fees: Decimal = D("0")
    funding: Decimal = D("0")
    turnover: Decimal = D("0")
    exits: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    def close_quantity(
        self, quantity: Decimal, price: Decimal, when: int, reason: str, fee_rate: Decimal
    ) -> Decimal:
        sign = D("1") if self.plan.side == "BUY" else D("-1")
        gross = sign * quantity * (price - self.plan.entry)
        fee = quantity * price * fee_rate
        self.gross += gross
        self.fees += fee
        self.turnover += quantity * price
        self.remaining -= quantity
        self.exits.append(
            {
                "quantity": str(quantity),
                "price": str(price),
                "modeled_exit_ms": when,
                "reason": reason,
            }
        )
        return gross - fee

    def report(self, policy: RuntimeQualificationPolicy) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "modeled_entry_ms": self.entry_ms,
            "exits": self.exits,
            "gross_pnl": str(self.gross),
            "fees": str(self.fees),
            "funding_payment": str(self.funding),
            "net_pnl": str(self.gross - self.fees - self.funding),
            "stress_net_pnl": str(
                self.gross
                - self.funding
                - self.fees * policy.fee_stress_multiplier
                - self.turnover * policy.stress_slippage
            ),
        }


def qualify_ict(
    *,
    repo: Path,
    cache: Path,
    minutes: Path,
    symbol: str,
    filters_path: Path,
    commissions_path: Path,
    oos_start_ms: int,
    policy: RuntimeQualificationPolicy,
    progress: Callable[[dict[str, Any]], None],
    entry_mode: EntryMode = "limit_touch",
    invalidation_mode: InvalidationMode = "entry_close",
    stop_loss_mode: StopLossMode | str = StopLossMode.SWING_EXTREME,
    time_filter_mode: TimeFilterMode = "all_hours",
) -> dict[str, Any]:
    if entry_mode not in {"limit_touch", "reclaim_retest"}:
        raise ValueError("Unsupported ICT qualification entry mode")
    if invalidation_mode not in {"entry_close", "stop_only"}:
        raise ValueError("Unsupported ICT qualification invalidation mode")
    normalized_stop_loss_mode = str(stop_loss_mode).lower()
    if normalized_stop_loss_mode not in {
        StopLossMode.SWING_EXTREME.value,
        StopLossMode.OTE_79_ADAPTIVE.value,
    }:
        raise ValueError("Unsupported ICT qualification stop loss mode")
    if time_filter_mode not in {
        "all_hours",
        "killzones",
        "twins_windows",
        "manipulation_distribution",
    }:
        raise ValueError("Unsupported ICT qualification time filter mode")
    names = (
        "src/autonomous_futures/strategy/ict_mmxm.py",
        "src/autonomous_futures/strategy/pd_array_touch_index.py",
        "src/autonomous_futures/execution/trade_plan.py",
        "src/autonomous_futures/execution/daily_risk.py",
        "src/autonomous_futures/research/ict_runtime_qualification.py",
        "src/autonomous_futures/research/official_market_data.py",
        "src/autonomous_futures/research/runtime_qualification.py",
        "scripts/qualify_runtime_ict.py",
    )
    implementation = {name: digest(repo / name) for name in names}
    five_raw, five_source = verified_bars(cache, symbol, "5m", repo=repo)
    hourly_raw, hour_source = verified_bars(cache, symbol, "1h", repo=repo)
    four_raw = four_hour_bars(hourly_raw)
    five = [Candle(*dataclasses.astuple(bar)) for bar in five_raw]
    hourly = [Candle(*dataclasses.astuple(bar)) for bar in hourly_raw]
    four = [Candle(*dataclasses.astuple(bar)) for bar in four_raw]
    filters_data = json.loads(filters_path.read_text(encoding="utf-8"))
    filters = SymbolFilters(
        **{key: D(value) for key, value in filters_data["specs"][symbol].items()}
    )
    rates = json.loads(commissions_path.read_text(encoding="utf-8"))
    rate = next(item for item in rates["rates"] if item["symbol"] == symbol)
    if D(rate["maker"]) != policy.maker_fee or D(rate["taker"]) != policy.taker_fee:
        raise ValueError("Frozen fee assumptions do not match authenticated commissions")
    funding_path = cache / "funding" / f"{symbol}-funding.csv"
    funding_manifest_path = funding_path.with_suffix(".manifest.json")
    funding_manifest = json.loads(funding_manifest_path.read_text(encoding="utf-8"))
    if digest(funding_path) != funding_manifest["sha256"]:
        raise ValueError("Funding cache integrity mismatch")
    funding = load_funding(funding_path, symbol)
    end_ms = min(five[-1].timestamp_ms + 300000, hourly[-1].timestamp_ms + 3600000)
    if not funding or funding[0][0] > oos_start_ms or funding[-1][0] < end_ms - 28800000:
        raise ValueError("Funding does not cover the qualification interval")
    width = (end_ms - oos_start_ms) // policy.windows // 60000 * 60000
    if width <= 0:
        raise ValueError("No complete OOS interval")
    windows: list[dict[str, Any]] = [
        {
            "start_ms": oos_start_ms + i * width,
            "end_ms": end_ms if i == policy.windows - 1 else oos_start_ms + (i + 1) * width,
            "signals": 0,
            "unfilled": 0,
            "trades": [],
        }
        for i in range(policy.windows)
    ]
    engine = IctMmxmEngine()
    sources = {
        "five": five_source,
        "hourly": hour_source,
        "filters": {
            "path": repo_relative_source_path(filters_path, repo),
            "sha256": digest(filters_path),
        },
        "funding": {
            "file": {
                "path": repo_relative_source_path(funding_path, repo),
                "sha256": digest(funding_path),
            },
            "manifest": {
                "path": repo_relative_source_path(funding_manifest_path, repo),
                "sha256": digest(funding_manifest_path),
            },
        },
        "commissions": {
            "path": repo_relative_source_path(commissions_path, repo),
            "sha256": digest(commissions_path),
        },
        "minute_manifests": [
            {
                "path": repo_relative_source_path(path, repo),
                "sha256": digest(path),
            }
            for path in sorted((minutes / symbol).glob("*.zip.manifest.json"))
        ],
    }
    source_files = source_file_index(sources, repo)
    closes = [
        [bar.timestamp_ms + duration for bar in series]
        for series, duration in ((five, 300000), (hourly, 3600000), (four, 14400000))
    ]
    minute_history: deque[Candle] = deque(maxlen=250)
    wallet = baseline = peak = policy.starting_equity
    drawdown = D("0")
    day = oos_start_ms // 86400000
    active: ModeledTrade | None = None
    rejected: dict[str, int] = {}
    counts: dict[str, int] = {}
    funding_cursor = bisect.bisect_left([row[0] for row in funding], oos_start_ms)
    prior_mark: Decimal | None = None
    last_progress = oos_start_ms
    for bar in official_minutes(minutes, symbol):
        minute_history.append(bar)
        decision = bar.timestamp_ms + 60000
        if decision <= oos_start_ms:
            prior_mark = bar.close
            continue
        if bar.timestamp_ms >= end_ms:
            break
        before_trade = active if active is not None and active.entry_ms is not None else None
        before_quantity = before_trade.remaining if before_trade is not None else D("0")
        touched_trade: ModeledTrade | None = before_trade
        if bar.timestamp_ms // 86400000 != day:
            upnl = D("0")
            if active is not None and active.entry_ms is not None:
                assert prior_mark is not None
                upnl = (
                    (D("1") if active.plan.side == "BUY" else D("-1"))
                    * active.remaining
                    * (prior_mark - active.plan.entry)
                )
            baseline, day = wallet + upnl, bar.timestamp_ms // 86400000
        current_window = min(policy.windows - 1, (decision - oos_start_ms) // width)
        if active is not None:
            plan = active.plan
            sign = D("1") if plan.side == "BUY" else D("-1")
            if active.entry_ms is None:
                if bar.timestamp_ms >= min(
                    plan.decision_ms + policy.entry_ttl_ms, windows[active.window]["end_ms"]
                ):
                    windows[active.window]["unfilled"] += 1
                    active = None
                elif (
                    entry_mode == "limit_touch"
                    and (
                        bar.low < plan.entry <= bar.open
                        if sign == 1
                        else bar.high > plan.entry >= bar.open
                    )
                    and bar.volume >= plan.quantity
                ):
                    active.entry_ms, active.remaining = bar.timestamp_ms, plan.quantity
                    active.tp1_remaining = sum(
                        (part.quantity for part in plan.exits if part.role == "TP1"), D("0")
                    )
                    touched_trade = active
                    active.fees = plan.notional * policy.maker_fee
                    active.turnover = plan.notional
                    wallet -= active.fees
                elif entry_mode == "reclaim_retest":
                    if active.reclaim_ms is None and has_close_reclaim(bar, plan):
                        active.reclaim_ms = decision
                    elif (
                        active.reclaim_ms is not None
                        and bar.timestamp_ms >= active.reclaim_ms
                        and has_post_reclaim_limit_fill(bar, plan)
                    ):
                        try:
                            filled_plan = build_plan(
                                family="ICT_TWINS",
                                symbol=plan.symbol,
                                side=plan.side,
                                entry=plan.entry,
                                stop=plan.stop,
                                tp1=plan.tp1,
                                tp2=plan.tp2,
                                decision_ms=plan.decision_ms,
                                hold_ms=plan.hold_ms,
                                setup_key=plan.signal_key,
                                filters=filters,
                                allowed_leverages=(plan.leverage,),
                                capital=policy.capital_policy(),
                                equity=wallet,
                                available_margin=wallet,
                                remaining_daily_risk=DailyRisk(
                                    baseline, wallet, limit_pct=policy.daily_loss_pct
                                ).remaining_usdt,
                            )
                        except IneligibleTrade as exc:
                            rejected[str(exc)] = rejected.get(str(exc), 0) + 1
                            active = None
                        else:
                            if bar.volume >= filled_plan.quantity:
                                active.plan = filled_plan
                                active.entry_ms = bar.timestamp_ms
                                active.reclaim_ms = None
                                active.remaining = filled_plan.quantity
                                active.tp1_remaining = sum(
                                    (
                                        part.quantity
                                        for part in filled_plan.exits
                                        if part.role == "TP1"
                                    ),
                                    D("0"),
                                )
                                touched_trade = active
                                active.fees = filled_plan.notional * policy.maker_fee
                                active.turnover = filled_plan.notional
                                wallet -= active.fees
            if (
                active is not None
                and active.entry_ms is None
                and decision >= windows[active.window]["end_ms"]
            ):
                windows[active.window]["unfilled"] += 1
                active = None
            if active is not None and active.entry_ms is not None and active.entry_ms < decision:
                plan = active.plan
                sign = D("1") if plan.side == "BUY" else D("-1")
                adverse = bar.low if sign == 1 else bar.high
                equity_at_adverse = wallet + sign * active.remaining * (adverse - plan.entry)
                stop_hit = bar.low <= plan.stop if sign == 1 else bar.high >= plan.stop
                stop_price = min(plan.stop, bar.open) if sign == 1 else max(plan.stop, bar.open)
                protected_equity = wallet + sign * active.remaining * (stop_price - plan.entry)
                drawdown = max(drawdown, peak - max(equity_at_adverse, protected_equity))
                daily = DailyRisk(baseline, equity_at_adverse, limit_pct=policy.daily_loss_pct)
                daily_before_stop = DailyRisk(
                    baseline, protected_equity, limit_pct=policy.daily_loss_pct
                ).breached
                if stop_hit and not daily_before_stop:
                    wallet += active.close_quantity(
                        active.remaining, stop_price, decision, "STOP", policy.taker_fee
                    )
                elif daily.breached:
                    threshold = (
                        plan.entry
                        + sign
                        * (baseline * (1 - policy.daily_loss_pct / 100) - wallet)
                        / active.remaining
                    )
                    price = min(threshold, bar.open) if sign == 1 else max(threshold, bar.open)
                    wallet += active.close_quantity(
                        active.remaining, price, decision, "DAILY_LOSS", policy.taker_fee
                    )
                elif invalidation_mode == "entry_close" and (
                    bar.close <= plan.entry if sign == 1 else bar.close >= plan.entry
                ):
                    wallet += active.close_quantity(
                        active.remaining, bar.close, decision, "CISD_INVALIDATION", policy.taker_fee
                    )
                elif decision >= min(
                    active.entry_ms + plan.hold_ms, windows[active.window]["end_ms"]
                ):
                    wallet += active.close_quantity(
                        active.remaining, bar.close, decision, "TIME_OR_WINDOW", policy.taker_fee
                    )
                elif (
                    bar.timestamp_ms > active.entry_ms
                    if entry_mode == "limit_touch"
                    else bar.timestamp_ms >= active.entry_ms
                ):
                    target1 = bar.high > plan.tp1 if sign == 1 else bar.low < plan.tp1
                    target2 = plan.tp2 is not None and (
                        bar.high > plan.tp2 if sign == 1 else bar.low < plan.tp2
                    )
                    if target1 and active.tp1_remaining:
                        quantity = min(active.remaining, active.tp1_remaining)
                        wallet += active.close_quantity(
                            quantity, plan.tp1, decision, "TP1", policy.maker_fee
                        )
                        active.tp1_remaining -= quantity
                    if target2 and active.remaining:
                        assert plan.tp2 is not None
                        wallet += active.close_quantity(
                            active.remaining, plan.tp2, decision, "TP2", policy.maker_fee
                        )
                touched_trade = active
            # Use an adverse bound when funding and fills/closures share a minute.
            while funding_cursor < len(funding) and funding[funding_cursor][0] < decision:
                when, rate_, mark = funding[funding_cursor]
                if (
                    touched_trade is not None
                    and touched_trade.entry_ms is not None
                    and when >= touched_trade.entry_ms
                ):
                    if mark is None and prior_mark is None:
                        raise ValueError("No observed funding mark proxy")
                    value = mark if mark is not None else prior_mark
                    assert value is not None
                    direction = D("1") if touched_trade.plan.side == "BUY" else D("-1")
                    signed_rate = direction * rate_
                    entering_quantity = (
                        touched_trade.plan.quantity
                        if touched_trade.entry_ms == bar.timestamp_ms
                        else before_quantity
                    )
                    quantity = (
                        max(before_quantity, entering_quantity, touched_trade.remaining)
                        if signed_rate >= 0
                        else min(before_quantity, touched_trade.remaining)
                    )
                    payment = quantity * value * signed_rate
                    touched_trade.funding += payment
                    wallet -= payment
                funding_cursor += 1
            if active is not None and active.entry_ms is not None:
                marked = wallet + sign * active.remaining * (bar.close - active.plan.entry)
                if (
                    active.remaining
                    and DailyRisk(baseline, marked, limit_pct=policy.daily_loss_pct).breached
                ):
                    wallet += active.close_quantity(
                        active.remaining,
                        bar.close,
                        decision,
                        "FUNDING_DAILY_LOSS",
                        policy.taker_fee,
                    )
                if active.remaining == 0:
                    windows[active.window]["trades"].append(active.report(policy))
                    active = None
            if active is not None:
                marked = (
                    wallet
                    if active.entry_ms is None
                    else wallet + sign * active.remaining * (bar.close - active.plan.entry)
                )
                peak = max(peak, marked)
                drawdown = max(drawdown, peak - marked)
                prior_mark = bar.close
                continue
        while funding_cursor < len(funding) and funding[funding_cursor][0] < decision:
            funding_cursor += 1
        if decision >= end_ms or wallet <= 0 or len(minute_history) < 250:
            prior_mark = bar.close
            continue
        daily = DailyRisk(baseline, wallet, limit_pct=policy.daily_loss_pct)
        if not daily.breached:
            in_time_window = True
            if time_filter_mode != "all_hours":
                q_cycle = engine.evaluate_quarterly_time_window(decision)
                if time_filter_mode == "killzones":
                    in_time_window = q_cycle.active_killzone != "NONE"
                elif time_filter_mode == "twins_windows":
                    in_time_window = q_cycle.in_twins_am_window or q_cycle.in_twins_pm_window
                elif time_filter_mode == "manipulation_distribution":
                    in_time_window = (
                        q_cycle.in_manipulation_window or q_cycle.in_distribution_window
                    )
            if not in_time_window:
                counts["OUTSIDE_TIME_WINDOW"] = counts.get("OUTSIDE_TIME_WINDOW", 0) + 1
            else:
                positions = [bisect.bisect_right(series, decision) for series in closes]
                hi5, hi1, hi4 = positions
                setup = engine.evaluate_twins_setup(
                    symbol,
                    four[max(0, hi4 - 250) : hi4],
                    hourly[max(0, hi1 - 250) : hi1],
                    [],
                    five[max(0, hi5 - 250) : hi5],
                    list(minute_history),
                    filters.tick_size,
                    stop_loss_mode=stop_loss_mode,
                )
                counts[setup.step.value] = counts.get(setup.step.value, 0) + 1
                if setup.step_6_ready:
                    windows[current_window]["signals"] += 1
                    try:
                        plan = ict_plan(
                            setup,
                            decision,
                            filters,
                            capital=policy.capital_policy(),
                            equity=wallet,
                            available_margin=wallet,
                            remaining_daily_risk=daily.remaining_usdt,
                        )
                        active = ModeledTrade(plan, current_window)
                    except IneligibleTrade as exc:
                        rejected[str(exc)] = rejected.get(str(exc), 0) + 1
        marked = (
            wallet
            if active is None or active.entry_ms is None
            else wallet + sign * active.remaining * (bar.close - active.plan.entry)
        )
        peak = max(peak, marked)
        drawdown = max(drawdown, peak - marked)
        prior_mark = bar.close
        if decision - last_progress >= 2592000000:
            progress(
                {"symbol": symbol, "through_ms": decision, "wallet": str(wallet), "steps": counts}
            )
            last_progress = decision
    trades = [trade for window in windows for trade in window["trades"]]
    wins = sum((max(D(trade["net_pnl"]), D("0")) for trade in trades), D("0"))
    losses = sum((max(-D(trade["net_pnl"]), D("0")) for trade in trades), D("0"))
    stress = sum((D(trade["stress_net_pnl"]) for trade in trades), D("0"))
    profitable = sum(
        sum((D(trade["net_pnl"]) for trade in window["trades"]), D("0")) > 0 for window in windows
    )
    gates = {
        "samples": len(trades) >= policy.minimum_trades,
        "net_edge": wins > losses,
        "stress": stress > 0,
        "profit_factor": bool(trades)
        and (losses == 0 or wins / losses >= policy.minimum_profit_factor),
        "drawdown": drawdown / policy.starting_equity * 100 <= policy.maximum_drawdown_pct,
        "windows": profitable >= policy.minimum_profitable_windows,
        "closed_at_end": active is None,
    }
    if implementation != {name: digest(repo / name) for name in names}:
        raise ValueError("Qualification implementation changed during replay")
    if source_file_index(sources, repo) != source_files:
        raise ValueError("Qualification inputs changed during replay")
    report = {
        "family": "ICT_TWINS",
        "symbol": symbol,
        "policy": dataclasses.asdict(policy),
        "sources": sources,
        "source_files": source_files,
        "implementation": implementation,
        "configuration": {
            "entry_mode": entry_mode,
            "invalidation_mode": invalidation_mode,
            "stop_loss_mode": normalized_stop_loss_mode,
            "time_filter_mode": time_filter_mode,
            "history_bars": 250,
            "htf_pda_timeframes": ["4h", "1h"],
            **{key: str(value) for key, value in vars(engine).items()},
        },
        "windows": windows,
        "step_counts": counts,
        "rejections": rejected,
        "metrics": {
            "trades": len(trades),
            "net_pnl": str(wins - losses),
            "stress_net_pnl": str(stress),
            "drawdown_usdt": str(drawdown),
            "profitable_windows": profitable,
        },
        "gates": gates,
        "decision": "QUALIFIED" if all(gates.values()) else "REJECTED",
        "execution_authority": False,
        "assumptions": [
            "single-symbol 100 USDT declared research account, not an authenticated balance",
            "1x leverage, observed exchange filters, current authenticated fees",
            "modeled full maker fill requires later trade-through and sufficient minute volume",
            "entry-bar profit is disallowed; adverse ambiguity resolves before targets",
            "funding uses published rates and the last closed observed price as mark proxy",
            "intraminute funding debits use maximum touched exposure; credits use minimum exposure",
            "OHLCV qualification does not qualify live microstructure or protective lifecycle",
            (
                "reclaim_retest waits for a completed one-minute touch-and-reclaim candle, "
                "then places a maker limit at the CISD line and requires a later price "
                "trade-through with sufficient recorded volume; the initial touch cannot "
                "fill the later order"
                if entry_mode == "reclaim_retest"
                else "limit_touch retains the original price-through modeled maker fill"
            ),
        ],
    }
    report["report_hash"] = content_hash(report)
    return cast(dict[str, Any], json.loads(json.dumps(report, default=str)))
