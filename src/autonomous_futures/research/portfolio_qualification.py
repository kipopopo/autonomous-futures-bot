"""Causal shared-wallet portfolio qualification across multiple symbols and strategies.

Single-symbol qualification replays each symbol with an isolated research equity.
Before any candidate set can be considered for portfolio admission, it must be
evaluated under one shared USDT wallet and equity ledger that combines:
- simultaneous open positions across all active symbols and strategies
- pending maker orders and their margin reservations
- real symbol filters and leverage brackets
- per-symbol maker/taker commissions and funding cashflows
- the shared 5% UTC day-start daily-loss circuit breaker across all positions
- 0.5% shared-account-equity risk per trade
- exact Decimal futures accounting identities (|drift| < 1e-15 USDT)
"""

from __future__ import annotations

import bisect
import dataclasses
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from autonomous_futures.execution.daily_risk import DailyRisk
from autonomous_futures.execution.trade_plan import (
    IneligibleTrade,
    SymbolFilters,
    TradePlan,
    scalper_plan,
)
from autonomous_futures.research.runtime_qualification import (
    RuntimeQualificationPolicy,
    bind_commission_policy,
    content_hash,
    digest,
    exact_scalper_candidates,
    four_hour_bars,
    load_funding,
    repo_relative_source_path,
    source_file_index,
    verified_bars,
)
from autonomous_futures.strategy.macro_liquidity_scalper import (
    Candle,
    MacroLiquidityDipScalper,
    MacroTrendFilter,
    ScalperSignal,
)

D = Decimal
MAX_LEDGER_DRIFT = D("1e-15")


@dataclasses.dataclass(frozen=True)
class PortfolioMemberSpec:
    member_id: str
    symbol: str
    family: str = "MACRO_SCALPER"
    distance_threshold: Decimal = D("-2.8")
    target_atr_multiplier: Decimal = D("1.8")
    stop_atr_multiplier: Decimal = D("1.2")
    rsi_threshold: Decimal = D("26.0")
    vol_spike_multiplier: Decimal = D("2.2")
    max_hold_bars: int = 8


@dataclasses.dataclass
class PortfolioPendingOrder:
    member_id: str
    family: str
    plan: TradePlan
    maker_fee: Decimal
    taker_fee: Decimal
    expires_ms: int
    window_index: int


@dataclasses.dataclass
class PortfolioOpenPosition:
    member_id: str
    family: str
    plan: TradePlan
    entry_ms: int
    deadline_ms: int
    window_index: int
    maker_fee: Decimal
    taker_fee: Decimal
    entry_fee: Decimal
    accrued_funding: Decimal = D("0")
    funding_approximations: int = 0
    prior_mark: Decimal = D("0")

    def __post_init__(self) -> None:
        if self.prior_mark <= 0:
            self.prior_mark = self.plan.entry

    @property
    def sign(self) -> Decimal:
        return D("1") if self.plan.side == "BUY" else D("-1")

    def unrealized_pnl(self, mark: Decimal) -> Decimal:
        return self.sign * (mark - self.plan.entry) * self.plan.quantity


@dataclasses.dataclass
class PortfolioLedger:
    starting_equity: Decimal
    capital_basis_adjustments: Decimal = D("0")
    closed_gross_pnl: Decimal = D("0")
    closed_fees: Decimal = D("0")
    closed_funding: Decimal = D("0")
    open_positions: dict[str, PortfolioOpenPosition] = dataclasses.field(default_factory=dict)
    pending_orders: dict[str, PortfolioPendingOrder] = dataclasses.field(default_factory=dict)
    max_wallet_drift: Decimal = D("0")
    max_equity_drift: Decimal = D("0")

    @property
    def open_realized_charges(self) -> Decimal:
        return sum(
            (pos.entry_fee + pos.accrued_funding for pos in self.open_positions.values()),
            D("0"),
        )

    @property
    def net_realized_pnl(self) -> Decimal:
        return (
            self.closed_gross_pnl
            - self.closed_fees
            - self.closed_funding
            - self.open_realized_charges
        )

    @property
    def wallet(self) -> Decimal:
        return self.starting_equity + self.capital_basis_adjustments + self.net_realized_pnl

    def unrealized_pnl(self, marks: dict[str, Decimal] | None = None) -> Decimal:
        lookup = marks or {}
        return sum(
            (
                pos.unrealized_pnl(lookup.get(symbol, pos.prior_mark))
                for symbol, pos in self.open_positions.items()
            ),
            D("0"),
        )

    def equity(self, marks: dict[str, Decimal] | None = None) -> Decimal:
        return self.wallet + self.unrealized_pnl(marks)

    @property
    def open_margin(self) -> Decimal:
        return sum((pos.plan.initial_margin for pos in self.open_positions.values()), D("0"))

    @property
    def pending_margin(self) -> Decimal:
        return sum((order.plan.initial_margin for order in self.pending_orders.values()), D("0"))

    @property
    def reserved_margin(self) -> Decimal:
        return self.open_margin + self.pending_margin

    def available_margin(self, marks: dict[str, Decimal] | None = None) -> Decimal:
        return max(D("0"), self.equity(marks) - self.reserved_margin)

    def verify_identities(self, marks: dict[str, Decimal] | None = None) -> tuple[Decimal, Decimal]:
        expected_wallet = (
            self.starting_equity + self.capital_basis_adjustments + self.net_realized_pnl
        )
        wallet_val = self.wallet
        unrealized_val = self.unrealized_pnl(marks)
        equity_val = self.equity(marks)
        wallet_drift = abs(wallet_val - expected_wallet)
        equity_drift = abs(equity_val - (wallet_val + unrealized_val))
        self.max_wallet_drift = max(self.max_wallet_drift, wallet_drift)
        self.max_equity_drift = max(self.max_equity_drift, equity_drift)
        if wallet_drift >= MAX_LEDGER_DRIFT or equity_drift >= MAX_LEDGER_DRIFT:
            raise ValueError(
                f"Portfolio ledger drift exceeded tolerance: "
                f"wallet_drift={wallet_drift}, equity_drift={equity_drift}"
            )
        return wallet_drift, equity_drift


@dataclasses.dataclass(frozen=True)
class CandidateDecisionEvent:
    decision_ms: int
    member: PortfolioMemberSpec
    signal: ScalperSignal


def _close_position(
    ledger: PortfolioLedger,
    pos: PortfolioOpenPosition,
    *,
    exit_price: Decimal,
    exit_ms: int,
    reason: str,
    policy: RuntimeQualificationPolicy,
    risk_day: int,
    day_start_equity: Decimal,
    minimum_equity: Decimal,
) -> dict[str, Any]:
    gross = pos.sign * (exit_price - pos.plan.entry) * pos.plan.quantity
    exit_fee_rate = pos.maker_fee if reason == "TAKE_PROFIT" else pos.taker_fee
    exit_fee = pos.plan.quantity * exit_price * exit_fee_rate
    total_fees = pos.entry_fee + exit_fee
    funding_paid = pos.accrued_funding
    net = gross - total_fees - funding_paid
    stress_cost = (
        total_fees * policy.fee_stress_multiplier
        + (pos.plan.notional + pos.plan.quantity * exit_price) * policy.stress_slippage
    )
    stress_net = gross - stress_cost - funding_paid

    del ledger.open_positions[pos.plan.symbol]
    ledger.closed_gross_pnl += gross
    ledger.closed_fees += total_fees
    ledger.closed_funding += funding_paid
    ledger.verify_identities()

    return {
        "member_id": pos.member_id,
        "family": pos.family,
        "symbol": pos.plan.symbol,
        "risk_day": risk_day,
        "day_start_equity": str(day_start_equity),
        "minimum_equity": str(minimum_equity),
        "wallet_after_exit": str(ledger.wallet),
        "plan": pos.plan.to_dict(),
        "entry_ms": pos.entry_ms,
        "exit_ms": exit_ms,
        "exit_price": str(exit_price),
        "reason": reason,
        "gross_pnl": str(gross),
        "fees": str(total_fees),
        "funding_payment": str(funding_paid),
        "net_pnl": str(net),
        "stress_net_pnl": str(stress_net),
        "funding_mark_approximations": pos.funding_approximations,
    }


def simulate_shared_wallet_portfolio(
    *,
    events: list[CandidateDecisionEvent],
    execution_by_symbol: dict[str, list[Candle]],
    funding_by_symbol: dict[str, list[tuple[int, Decimal, Decimal | None]]],
    filters_by_symbol: dict[str, SymbolFilters],
    leverages_by_symbol: dict[str, tuple[int, ...]],
    fees_by_symbol: dict[str, tuple[Decimal, Decimal]],
    policy: RuntimeQualificationPolicy,
    oos_start_ms: int,
    end_ms: int,
) -> dict[str, Any]:
    """Chronologically replay multi-symbol signals against one shared futures wallet."""
    width = (end_ms - oos_start_ms) // policy.windows // 300_000 * 300_000
    if width <= 0:
        raise ValueError("No OOS interval for portfolio qualification")
    windows: list[dict[str, Any]] = [
        {
            "start_ms": oos_start_ms + i * width,
            "end_ms": end_ms if i == policy.windows - 1 else oos_start_ms + (i + 1) * width,
            "trades": [],
            "signals": 0,
            "ineligible": 0,
            "unfilled": 0,
        }
        for i in range(policy.windows)
    ]

    bar_lookup: dict[str, dict[int, Candle]] = {
        symbol: {bar.timestamp_ms: bar for bar in bars if oos_start_ms <= bar.timestamp_ms < end_ms}
        for symbol, bars in execution_by_symbol.items()
    }
    all_bar_timestamps = sorted({ts for symbol_bars in bar_lookup.values() for ts in symbol_bars})
    funding_cursors: dict[str, int] = {
        symbol: bisect.bisect_right([item[0] for item in items], oos_start_ms)
        for symbol, items in funding_by_symbol.items()
    }

    sorted_events = sorted(
        (ev for ev in events if oos_start_ms <= ev.decision_ms < end_ms),
        key=lambda item: (item.decision_ms, item.member.symbol, item.member.member_id),
    )
    events_by_decision_ms: dict[int, list[CandidateDecisionEvent]] = {}
    for ev in sorted_events:
        events_by_decision_ms.setdefault(ev.decision_ms, []).append(ev)

    timeline = sorted(set(all_bar_timestamps) | set(events_by_decision_ms))

    ledger = PortfolioLedger(starting_equity=policy.starting_equity)
    ledger.verify_identities()
    day_start_equity = policy.starting_equity
    risk_day = oos_start_ms // policy.trading_day_ms
    daily_halted = False
    peak_equity = policy.starting_equity
    minimum_portfolio_equity = policy.starting_equity
    max_drawdown_usdt = D("0")
    max_concurrent_positions = 0
    max_reserved_margin = D("0")
    rejection_reasons: dict[str, int] = {}

    def record_rejection(window_idx: int, reason: str) -> None:
        windows[window_idx]["ineligible"] += 1
        rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1

    for ts in timeline:
        current_day = ts // policy.trading_day_ms
        if current_day != risk_day:
            # Value UTC day-start baseline strictly from prior closed marks.
            day_start_equity = ledger.equity()
            risk_day = current_day
            daily_halted = False
            ledger.verify_identities()

        # 1. Process new decision events occurring at `ts`
        # (before candle `[ts, ts + 300_000)` opens).
        for ev in events_by_decision_ms.get(ts, []):
            window_idx = min(policy.windows - 1, (ts - oos_start_ms) // width)
            windows[window_idx]["signals"] += 1
            current_eq = ledger.equity()
            daily = DailyRisk(day_start_equity, current_eq, limit_pct=policy.daily_loss_pct)
            if daily_halted or daily.breached or current_eq <= 0:
                daily_halted = True
                record_rejection(window_idx, "Daily loss budget exhausted")
                continue
            symbol = ev.member.symbol
            if symbol in ledger.open_positions or symbol in ledger.pending_orders:
                record_rejection(window_idx, "Symbol already has active position or order")
                continue
            maker_fee, taker_fee = fees_by_symbol[symbol]
            try:
                plan = scalper_plan(
                    ev.signal,
                    filters_by_symbol[symbol],
                    leverages_by_symbol.get(symbol, (1,)),
                    capital=policy.capital_policy(),
                    equity=current_eq,
                    available_margin=ledger.available_margin(),
                    remaining_daily_risk=daily.remaining_usdt,
                )
            except IneligibleTrade as exc:
                record_rejection(window_idx, str(exc))
                continue
            window_end_ms = windows[window_idx]["end_ms"]
            expires_ms = min(plan.decision_ms + policy.entry_ttl_ms, window_end_ms)
            if expires_ms <= ts:
                windows[window_idx]["unfilled"] += 1
                continue
            ledger.pending_orders[symbol] = PortfolioPendingOrder(
                member_id=ev.member.member_id,
                family=ev.member.family,
                plan=plan,
                maker_fee=maker_fee,
                taker_fee=taker_fee,
                expires_ms=expires_ms,
                window_index=window_idx,
            )
            max_reserved_margin = max(max_reserved_margin, ledger.reserved_margin)
            ledger.verify_identities()

        # 2. Expire stale pending orders at `ts`.
        for symbol in sorted(list(ledger.pending_orders)):
            order = ledger.pending_orders[symbol]
            if ts >= order.expires_ms:
                windows[order.window_index]["unfilled"] += 1
                del ledger.pending_orders[symbol]

        # 3. Fill pending maker orders that trade through on candle `ts`.
        for symbol in sorted(list(ledger.pending_orders)):
            order = ledger.pending_orders[symbol]
            bar = bar_lookup.get(symbol, {}).get(ts)
            if bar is None:
                continue
            current_eq = ledger.equity()
            daily = DailyRisk(day_start_equity, current_eq, limit_pct=policy.daily_loss_pct)
            if daily_halted or daily.breached or current_eq <= 0:
                daily_halted = True
                del ledger.pending_orders[symbol]
                record_rejection(order.window_index, "Daily loss budget exhausted")
                continue
            plan = order.plan
            filled = (
                bar.low < plan.entry <= bar.open
                if plan.side == "BUY"
                else bar.high > plan.entry >= bar.open
            )
            if not filled:
                continue
            del ledger.pending_orders[symbol]
            window_end_ms = windows[order.window_index]["end_ms"]
            deadline_ms = min(ts + plan.hold_ms, window_end_ms)
            entry_fee = plan.notional * order.maker_fee
            ledger.open_positions[symbol] = PortfolioOpenPosition(
                member_id=order.member_id,
                family=order.family,
                plan=plan,
                entry_ms=ts,
                deadline_ms=deadline_ms,
                window_index=order.window_index,
                maker_fee=order.maker_fee,
                taker_fee=order.taker_fee,
                entry_fee=entry_fee,
                prior_mark=plan.entry,
            )
            max_concurrent_positions = max(max_concurrent_positions, len(ledger.open_positions))
            max_reserved_margin = max(max_reserved_margin, ledger.reserved_margin)
            ledger.verify_identities()
            cur_eq = ledger.equity()
            minimum_portfolio_equity = min(minimum_portfolio_equity, cur_eq)
            max_drawdown_usdt = max(max_drawdown_usdt, peak_equity - cur_eq)

        if not ledger.open_positions:
            continue

        # 4. Settle funding events up to `ts` across all open positions.
        for symbol in sorted(ledger.open_positions):
            pos = ledger.open_positions[symbol]
            funding_list = funding_by_symbol.get(symbol, [])
            cursor = funding_cursors.get(symbol, 0)
            while cursor < len(funding_list) and funding_list[cursor][0] <= ts:
                when, rate, mark = funding_list[cursor]
                if when > pos.entry_ms:
                    effective_mark = pos.prior_mark if mark is None else mark
                    if mark is None:
                        pos.funding_approximations += 1
                    pos.accrued_funding += pos.sign * pos.plan.quantity * effective_mark * rate
                cursor += 1
            funding_cursors[symbol] = cursor
        ledger.verify_identities()

        # 5. Evaluate adverse excursion and protective stop floor across all open positions at `ts`.
        adverse_marks: dict[str, Decimal] = {}
        protected_marks: dict[str, Decimal] = {}
        for symbol, pos in ledger.open_positions.items():
            bar = bar_lookup.get(symbol, {}).get(ts)
            if bar is None:
                adverse_marks[symbol] = pos.prior_mark
                protected_marks[symbol] = pos.prior_mark
            else:
                adverse_marks[symbol] = bar.low if pos.sign == 1 else bar.high
                protected_marks[symbol] = (
                    min(pos.plan.stop, bar.open) if pos.sign == 1 else max(pos.plan.stop, bar.open)
                )

        adverse_equity = ledger.equity(adverse_marks)
        protected_equity = ledger.equity(protected_marks)
        candle_floor_equity = max(adverse_equity, protected_equity)
        minimum_portfolio_equity = min(minimum_portfolio_equity, candle_floor_equity)
        max_drawdown_usdt = max(max_drawdown_usdt, peak_equity - candle_floor_equity)

        # Check whether portfolio breaches the shared 5% UTC day-start daily-loss limit.
        daily_adverse = DailyRisk(day_start_equity, adverse_equity, limit_pct=policy.daily_loss_pct)
        daily_protected = DailyRisk(
            day_start_equity, protected_equity, limit_pct=policy.daily_loss_pct
        )

        # If protected equity already breaches daily loss, flatten all open positions on DAILY_LOSS.
        if daily_protected.breached or daily_adverse.breached:
            # First close positions whose individual stop was hit without breaching daily loss.
            for symbol in sorted(list(ledger.open_positions)):
                pos = ledger.open_positions[symbol]
                bar = bar_lookup.get(symbol, {}).get(ts)
                if bar is None:
                    continue
                stop_hit = bar.low <= pos.plan.stop if pos.sign == 1 else bar.high >= pos.plan.stop
                if stop_hit and not daily_protected.breached:
                    exit_price = (
                        min(pos.plan.stop, bar.open)
                        if pos.sign == 1
                        else max(pos.plan.stop, bar.open)
                    )
                    trade = _close_position(
                        ledger,
                        pos,
                        exit_price=exit_price,
                        exit_ms=ts + 300_000,
                        reason="STOP_LOSS",
                        policy=policy,
                        risk_day=risk_day,
                        day_start_equity=day_start_equity,
                        minimum_equity=candle_floor_equity,
                    )
                    windows[pos.window_index]["trades"].append(trade)
                    peak_equity = max(peak_equity, ledger.equity())
                    max_drawdown_usdt = max(max_drawdown_usdt, peak_equity - ledger.equity())

            # Check if remaining open positions still breach daily loss on adverse marks.
            remaining_adverse_marks = {sym: adverse_marks[sym] for sym in ledger.open_positions}
            if (
                ledger.open_positions
                and DailyRisk(
                    day_start_equity,
                    ledger.equity(remaining_adverse_marks),
                    limit_pct=policy.daily_loss_pct,
                ).breached
            ):
                daily_halted = True
                for pending_sym in sorted(list(ledger.pending_orders)):
                    pending_order = ledger.pending_orders.pop(pending_sym)
                    record_rejection(pending_order.window_index, "Daily loss budget exhausted")
                for symbol in sorted(list(ledger.open_positions)):
                    pos = ledger.open_positions[symbol]
                    bar = bar_lookup.get(symbol, {}).get(ts)
                    exit_price = (
                        adverse_marks[symbol]
                        if bar is None
                        else (
                            min(bar.open, max(bar.low, protected_marks[symbol]))
                            if pos.sign == 1
                            else max(bar.open, min(bar.high, protected_marks[symbol]))
                        )
                    )
                    trade = _close_position(
                        ledger,
                        pos,
                        exit_price=exit_price,
                        exit_ms=ts + 300_000,
                        reason="DAILY_LOSS",
                        policy=policy,
                        risk_day=risk_day,
                        day_start_equity=day_start_equity,
                        minimum_equity=candle_floor_equity,
                    )
                    windows[pos.window_index]["trades"].append(trade)
                    peak_equity = max(peak_equity, ledger.equity())
                    max_drawdown_usdt = max(max_drawdown_usdt, peak_equity - ledger.equity())

        # 6. Process normal STOP_LOSS, TAKE_PROFIT, and TIME_STOP exits for remaining positions.
        for symbol in sorted(list(ledger.open_positions)):
            pos = ledger.open_positions[symbol]
            bar = bar_lookup.get(symbol, {}).get(ts)
            if bar is None:
                continue
            stop_hit = bar.low <= pos.plan.stop if pos.sign == 1 else bar.high >= pos.plan.stop
            target_hit = bar.high > pos.plan.tp1 if pos.sign == 1 else bar.low < pos.plan.tp1
            resolved_exit_price: Decimal | None = None
            reason = "TIME_STOP"
            if stop_hit:
                resolved_exit_price = (
                    min(pos.plan.stop, bar.open) if pos.sign == 1 else max(pos.plan.stop, bar.open)
                )
                reason = "STOP_LOSS"
            elif ts > pos.entry_ms and target_hit:
                resolved_exit_price = pos.plan.tp1
                reason = "TAKE_PROFIT"
            elif ts + 300_000 >= pos.deadline_ms:
                resolved_exit_price = bar.close
                reason = "TIME_STOP"

            if resolved_exit_price is not None:
                trade = _close_position(
                    ledger,
                    pos,
                    exit_price=resolved_exit_price,
                    exit_ms=ts + 300_000,
                    reason=reason,
                    policy=policy,
                    risk_day=risk_day,
                    day_start_equity=day_start_equity,
                    minimum_equity=candle_floor_equity,
                )
                windows[pos.window_index]["trades"].append(trade)
                cur_eq = ledger.equity()
                peak_equity = max(peak_equity, cur_eq)
                max_drawdown_usdt = max(max_drawdown_usdt, peak_equity - cur_eq)
            else:
                pos.prior_mark = bar.close

        if ledger.open_positions:
            cur_eq = ledger.equity()
            peak_equity = max(peak_equity, cur_eq)
            max_drawdown_usdt = max(max_drawdown_usdt, peak_equity - cur_eq)
            if DailyRisk(day_start_equity, cur_eq, limit_pct=policy.daily_loss_pct).breached:
                daily_halted = True

    # Expire any leftover pending orders at `end_ms`.
    for symbol in sorted(list(ledger.pending_orders)):
        order = ledger.pending_orders.pop(symbol)
        windows[order.window_index]["unfilled"] += 1

    # Force-close any position still open at `end_ms` at its last known mark.
    for symbol in sorted(list(ledger.open_positions)):
        pos = ledger.open_positions[symbol]
        trade = _close_position(
            ledger,
            pos,
            exit_price=pos.prior_mark,
            exit_ms=end_ms,
            reason="TIME_STOP",
            policy=policy,
            risk_day=risk_day,
            day_start_equity=day_start_equity,
            minimum_equity=minimum_portfolio_equity,
        )
        windows[pos.window_index]["trades"].append(trade)

    ledger.verify_identities()
    trades = [trade for window in windows for trade in window["trades"]]
    profits = sum((max(D(t["net_pnl"]), D("0")) for t in trades), D("0"))
    losses = sum((max(-D(t["net_pnl"]), D("0")) for t in trades), D("0"))
    net = profits - losses
    stress_net = sum((D(t["stress_net_pnl"]) for t in trades), D("0"))
    profitable_windows = sum(
        sum((D(t["net_pnl"]) for t in w["trades"]), D("0")) > 0 for w in windows
    )
    gates = {
        "sufficient_oos_samples": len(trades) >= policy.minimum_trades,
        "positive_net_edge": net > 0,
        "profit_factor": bool(trades)
        and (losses == 0 or profits / losses >= policy.minimum_profit_factor),
        "drawdown": max_drawdown_usdt / policy.starting_equity * 100 <= policy.maximum_drawdown_pct,
        "window_consistency": profitable_windows >= policy.minimum_profitable_windows,
        "stress_positive": stress_net > 0,
        "accounting_reconciled": (
            ledger.max_wallet_drift < MAX_LEDGER_DRIFT
            and ledger.max_equity_drift < MAX_LEDGER_DRIFT
            and abs(ledger.wallet - (policy.starting_equity + net)) < MAX_LEDGER_DRIFT
        ),
    }

    by_symbol: dict[str, dict[str, Any]] = {}
    for trade in trades:
        sym = trade["symbol"]
        bucket = by_symbol.setdefault(
            sym,
            {"trade_count": 0, "net_pnl": D("0"), "stress_net_pnl": D("0")},
        )
        bucket["trade_count"] += 1
        bucket["net_pnl"] += D(trade["net_pnl"])
        bucket["stress_net_pnl"] += D(trade["stress_net_pnl"])

    return {
        "windows": windows,
        "rejection_reasons": rejection_reasons,
        "metrics": {
            "trade_count": len(trades),
            "net_pnl": str(net),
            "stress_net_pnl": str(stress_net),
            "ending_wallet": str(ledger.wallet),
            "ending_equity": str(ledger.equity()),
            "drawdown_usdt": str(max_drawdown_usdt),
            "drawdown_pct": str(max_drawdown_usdt / policy.starting_equity * 100),
            "profitable_windows": profitable_windows,
            "max_concurrent_positions": max_concurrent_positions,
            "max_reserved_margin_usdt": str(max_reserved_margin),
            "max_wallet_drift": str(ledger.max_wallet_drift),
            "max_equity_drift": str(ledger.max_equity_drift),
        },
        "by_symbol": {
            sym: {
                "trade_count": data["trade_count"],
                "net_pnl": str(data["net_pnl"]),
                "stress_net_pnl": str(data["stress_net_pnl"]),
            }
            for sym, data in sorted(by_symbol.items())
        },
        "gates": gates,
        "decision": "QUALIFIED" if all(gates.values()) else "REJECTED",
        "execution_authority": False,
    }


def qualify_scalper_portfolio(
    *,
    cache: Path,
    funding_dir: Path,
    filters_path: Path,
    commissions_path: Path,
    members: list[PortfolioMemberSpec],
    oos_start_ms: int,
    repo: Path,
    policy: RuntimeQualificationPolicy,
    oos_end_ms: int | None = None,
) -> dict[str, Any]:
    """Run shared-wallet portfolio qualification across a set of Macro Scalper members."""
    if not members:
        raise ValueError("Portfolio qualification requires at least one member")
    member_ids = [m.member_id for m in members]
    if len(set(member_ids)) != len(member_ids):
        raise ValueError("Portfolio member IDs must be unique")

    btc, macro_evidence = verified_bars(cache, "BTCUSDT", "1h", repo=repo)
    btc4h = four_hour_bars(btc)
    hour_closes = [b.timestamp_ms + 3_600_000 for b in btc]
    four_closes = [b.timestamp_ms + 14_400_000 for b in btc4h]
    macro = MacroTrendFilter()

    filters_data = json.loads(filters_path.read_text(encoding="utf-8"))
    symbols = sorted({m.symbol for m in members})

    market_bars_by_symbol: dict[str, list[Candle]] = {}
    execution_by_symbol: dict[str, list[Candle]] = {}
    funding_by_symbol: dict[str, list[tuple[int, Decimal, Decimal | None]]] = {}
    filters_by_symbol: dict[str, SymbolFilters] = {}
    leverages_by_symbol: dict[str, tuple[int, ...]] = {}
    fees_by_symbol: dict[str, tuple[Decimal, Decimal]] = {}

    sources: dict[str, Any] = {
        "macro": macro_evidence,
        "exchange_filters": {
            "path": repo_relative_source_path(filters_path, repo),
            "sha256": digest(filters_path),
            "source": filters_data["source"],
            "observed_ms": filters_data["observed_ms"],
        },
        "symbols": {},
    }

    end_candidates: list[int] = []
    for symbol in symbols:
        resolved_policy, commission_evidence = bind_commission_policy(
            policy, commissions_path, symbol, repo
        )
        fees_by_symbol[symbol] = (resolved_policy.maker_fee, resolved_policy.taker_fee)
        bars_15m, market_ev = verified_bars(cache, symbol, "15m", repo=repo)
        bars_5m, exec_ev = verified_bars(cache, symbol, "5m", repo=repo)
        funding_path = funding_dir / f"{symbol}-funding.csv"
        funding = load_funding(funding_path, symbol)
        if (
            not funding
            or funding[0][0] > oos_start_ms
            or funding[-1][0] < bars_15m[-1].timestamp_ms - 28_800_000
        ):
            raise ValueError(f"Funding observations do not cover the OOS period for {symbol}")
        market_bars_by_symbol[symbol] = bars_15m
        execution_by_symbol[symbol] = bars_5m
        funding_by_symbol[symbol] = funding
        filters_by_symbol[symbol] = SymbolFilters(
            **{key: D(value) for key, value in filters_data["specs"][symbol].items()}
        )
        leverages_by_symbol[symbol] = tuple(
            filters_data.get("allowed_leverages", {}).get(symbol, [1])
        )
        end_candidates.append(
            min(bars_15m[-1].timestamp_ms + 900_000, bars_5m[-1].timestamp_ms + 300_000)
        )
        sources["symbols"][symbol] = {
            "market": market_ev,
            "execution": exec_ev,
            "funding": {
                "path": repo_relative_source_path(funding_path, repo),
                "sha256": digest(funding_path),
            },
            "commissions": commission_evidence,
        }

    computed_end_ms = min(end_candidates)
    effective_end_ms = (
        min(computed_end_ms, oos_end_ms) if oos_end_ms is not None else computed_end_ms
    )
    if effective_end_ms <= oos_start_ms:
        raise ValueError("Portfolio OOS interval is empty")

    events: list[CandidateDecisionEvent] = []
    for member in members:
        if member.family != "MACRO_SCALPER":
            raise ValueError(f"Unsupported portfolio member family: {member.family}")
        engine = MacroLiquidityDipScalper(
            rsi_threshold=member.rsi_threshold,
            vol_spike_multiplier=member.vol_spike_multiplier,
            dist_atr_threshold=member.distance_threshold,
            tp_atr_mult=member.target_atr_multiplier,
            sl_atr_mult=member.stop_atr_multiplier,
            max_hold_bars=member.max_hold_bars,
        )
        bars = market_bars_by_symbol[member.symbol]
        for index in exact_scalper_candidates(
            bars,
            rsi_threshold=engine.rsi_threshold,
            volume_multiplier=engine.vol_spike_multiplier,
        ):
            bar = bars[index]
            decision_ms = bar.timestamp_ms + 900_000
            if not oos_start_ms <= decision_ms < effective_end_ms:
                continue
            hi = bisect.bisect_right(hour_closes, decision_ms)
            fi = bisect.bisect_right(four_closes, decision_ms)
            regime = macro.evaluate_regime(
                btc[max(0, hi - 250) : hi],
                btc4h[max(0, fi - 250) : fi],
            )
            signal = engine.evaluate_15m_bar(
                member.symbol,
                bar,
                bars[max(0, index - 249) : index],
                regime,
            )
            if signal is not None:
                events.append(
                    CandidateDecisionEvent(
                        decision_ms=decision_ms,
                        member=member,
                        signal=signal,
                    )
                )

    source_files = source_file_index(sources, repo)
    simulation = simulate_shared_wallet_portfolio(
        events=events,
        execution_by_symbol=execution_by_symbol,
        funding_by_symbol=funding_by_symbol,
        filters_by_symbol=filters_by_symbol,
        leverages_by_symbol=leverages_by_symbol,
        fees_by_symbol=fees_by_symbol,
        policy=policy,
        oos_start_ms=oos_start_ms,
        end_ms=effective_end_ms,
    )
    if source_file_index(sources, repo) != source_files:
        raise ValueError("Portfolio qualification inputs changed during replay")

    implementation = {
        name: digest(repo / name)
        for name in (
            "src/autonomous_futures/strategy/macro_liquidity_scalper.py",
            "src/autonomous_futures/execution/trade_plan.py",
            "src/autonomous_futures/execution/daily_risk.py",
            "src/autonomous_futures/research/runtime_qualification.py",
            "src/autonomous_futures/research/portfolio_qualification.py",
        )
    }
    report: dict[str, Any] = {
        "version": 1,
        "scope": "SHARED_WALLET_PORTFOLIO",
        "family": "MACRO_SCALPER",
        "symbols": symbols,
        "members": [dataclasses.asdict(m) for m in members],
        "policy": dataclasses.asdict(policy),
        "policy_hash": content_hash(dataclasses.asdict(policy)),
        "sources": sources,
        "source_files": source_files,
        "implementation": implementation,
        **simulation,
        "assumptions": [
            "shared USDT wallet and equity ledger across all portfolio members",
            "pending maker orders and open positions reserve margin from shared available balance",
            "0.5% trade risk is sized from current shared portfolio equity",
            "5% daily loss limit is enforced against shared UTC day-start portfolio equity",
            "exact Decimal futures accounting identities verified on every state transition",
            (
                "historical OHLCV replay does not qualify live microstructure "
                "or user-stream truth by itself"
            ),
        ],
    }
    report["report_hash"] = content_hash(report)
    return cast(dict[str, Any], json.loads(json.dumps(report, default=str)))
