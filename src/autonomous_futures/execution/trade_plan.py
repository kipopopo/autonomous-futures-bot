"""Shared, pure trade eligibility rules for causal replay and live execution."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal
from typing import Any, Literal, cast

from autonomous_futures.strategy.ict_mmxm import TwinsSetupState
from autonomous_futures.strategy.macro_liquidity_scalper import ScalperSignal

D = Decimal


@dataclasses.dataclass(frozen=True)
class RuntimeCapitalPolicy:
    """User-approved collateral policy, superseding the original notional/reserve caps."""

    daily_loss_pct: Decimal = D("5")
    trade_risk_pct: Decimal = D("0.5")
    max_initial_margin_per_trade: Decimal | None = None
    max_aggregate_notional: Decimal | None = None
    min_cash_reserve_pct: Decimal | None = None

    def __post_init__(self) -> None:
        if (
            not self.daily_loss_pct.is_finite()
            or not 0 < self.daily_loss_pct < 100
            or not self.trade_risk_pct.is_finite()
            or not 0 < self.trade_risk_pct <= self.daily_loss_pct
        ):
            raise ValueError("Risk percentages must be finite and bounded by the daily loss policy")

    def daily_budget(self, day_start_equity: Decimal) -> Decimal:
        if not day_start_equity.is_finite() or day_start_equity <= 0:
            raise ValueError("A genuine positive day-start equity is required")
        return day_start_equity * self.daily_loss_pct / 100


DEFAULT_CAPITAL_POLICY = RuntimeCapitalPolicy()


class IneligibleTrade(ValueError):
    """The actual strategy intention cannot satisfy exchange and capital rules."""


@dataclasses.dataclass(frozen=True)
class SymbolFilters:
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal
    max_qty: Decimal
    min_notional: Decimal

    def __post_init__(self) -> None:
        if not all(v.is_finite() and v > 0 for v in dataclasses.asdict(self).values()):
            raise ValueError("Exchange filters must be finite and positive")
        if self.max_qty < self.min_qty:
            raise ValueError("Invalid quantity envelope")

    @classmethod
    def from_gateway(cls, spec: dict[str, Decimal]) -> SymbolFilters:
        return cls(**{field.name: spec[field.name] for field in dataclasses.fields(cls)})


@dataclasses.dataclass(frozen=True)
class ExitSlice:
    role: Literal["STOP", "TP1", "TP2"]
    quantity: Decimal
    price: Decimal


@dataclasses.dataclass(frozen=True)
class TradePlan:
    family: Literal["MACRO_SCALPER", "ICT_TWINS"]
    symbol: str
    side: Literal["BUY", "SELL"]
    decision_ms: int
    signal_key: str
    entry: Decimal
    quantity: Decimal
    leverage: int
    stop: Decimal
    tp1: Decimal
    tp2: Decimal | None
    hold_ms: int
    exits: tuple[ExitSlice, ...]

    @property
    def notional(self) -> Decimal:
        return self.entry * self.quantity

    @property
    def initial_margin(self) -> Decimal:
        return self.notional / self.leverage

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(json.dumps(dataclasses.asdict(self), default=str)))


def tick_price(price: Decimal, tick: Decimal, *, round_up: bool = False) -> Decimal:
    if not price.is_finite() or price <= 0:
        raise IneligibleTrade("Invalid price")
    rounding = ROUND_CEILING if round_up else ROUND_DOWN
    return (price / tick).to_integral_value(rounding=rounding) * tick


def split_exit(
    quantity: Decimal,
    price: Decimal,
    role: Literal["STOP", "TP1", "TP2"],
    filters: SymbolFilters,
) -> tuple[ExitSlice, ...]:
    """Reduce-only exits follow exchange size limits, not an obsolete notional cap."""
    child = filters.max_qty
    if child < filters.min_qty or quantity % filters.step_size:
        raise IneligibleTrade("Protective exit is incompatible with exchange size limits")
    result = []
    remaining = quantity
    while remaining:
        current = min(child, remaining)
        if current < filters.min_qty:
            raise IneligibleTrade("Protective exit leaves an invalid residual lot")
        result.append(ExitSlice(role, current, price))
        remaining -= current
    return tuple(result)


def build_plan(
    *,
    family: Literal["MACRO_SCALPER", "ICT_TWINS"],
    symbol: str,
    side: Literal["BUY", "SELL"],
    entry: Decimal,
    stop: Decimal,
    tp1: Decimal,
    tp2: Decimal | None,
    decision_ms: int,
    hold_ms: int,
    setup_key: str,
    filters: SymbolFilters,
    allowed_leverages: tuple[int, ...] = (1,),
    capital: RuntimeCapitalPolicy = DEFAULT_CAPITAL_POLICY,
    equity: Decimal | None = None,
    available_margin: Decimal | None = None,
    remaining_daily_risk: Decimal | None = None,
) -> TradePlan:
    """Reject infeasible intentions instead of moving the entry to fit a notional cap."""
    if decision_ms <= 0 or hold_ms <= 0:
        raise IneligibleTrade("Invalid signal timing")
    entry = tick_price(entry, filters.tick_size, round_up=side == "SELL")
    stop = tick_price(stop, filters.tick_size, round_up=side == "SELL")
    tp1 = tick_price(tp1, filters.tick_size, round_up=side == "SELL")
    if tp2 is not None:
        tp2 = tick_price(tp2, filters.tick_size, round_up=side == "SELL")
    if not ((stop < entry < tp1) if side == "BUY" else (tp1 < entry < stop)):
        raise IneligibleTrade("Protective prices do not bracket the entry")
    if tp2 is not None and not (tp2 >= tp1 if side == "BUY" else tp2 <= tp1):
        raise IneligibleTrade("Final target is not beyond the partial target")
    if family == "ICT_TWINS" and abs(tp1 - entry) / abs(entry - stop) < D("1.5"):
        raise IneligibleTrade(
            "ICT first target does not satisfy the canonical 1.5 reward/risk floor"
        )
    if equity is None or available_margin is None:
        raise IneligibleTrade("Observed equity and available margin are required for risk sizing")
    if (
        not equity.is_finite()
        or equity <= 0
        or not available_margin.is_finite()
        or available_margin <= 0
    ):
        raise IneligibleTrade("Equity or exchange available margin is invalid")
    risk_budget = equity * capital.trade_risk_pct / 100
    if remaining_daily_risk is not None:
        risk_budget = min(risk_budget, remaining_daily_risk)
    # Include a stressed fee/slippage allowance rather than sizing on stop distance alone.
    risk_per_unit = abs(entry - stop) + (entry + stop) * D("0.0013")
    minimum = (filters.min_notional / entry / filters.step_size).to_integral_value(
        rounding=ROUND_CEILING
    ) * filters.step_size
    minimum = max(minimum, filters.min_qty)
    quantity = (risk_budget / risk_per_unit / filters.step_size).to_integral_value(
        rounding=ROUND_DOWN
    ) * filters.step_size
    quantity = min(quantity, filters.max_qty)
    if quantity < minimum:
        raise IneligibleTrade("Exchange minimum order size exceeds the percentage risk budget")
    notional = entry * quantity
    feasible = sorted(
        {
            level
            for level in allowed_leverages
            if 1 <= level <= 125
            and notional / level <= available_margin
            and D("1") / level > abs(entry - stop) / entry * 2 + D("0.01")
        }
    )
    if not feasible:
        raise IneligibleTrade("No permitted leverage can fund the position with a stop buffer")
    leverage = feasible[0]
    exits = split_exit(quantity, stop, "STOP", filters)
    if family == "ICT_TWINS":
        if tp2 is None:
            raise IneligibleTrade("ICT requires both partial and final targets")
        partial = (quantity / D("2") / filters.step_size).to_integral_value(rounding=ROUND_DOWN)
        partial *= filters.step_size
        if partial < filters.min_qty or quantity - partial < filters.min_qty:
            raise IneligibleTrade("ICT quantity cannot support two valid target stages")
        exits += split_exit(partial, tp1, "TP1", filters)
        exits += split_exit(quantity - partial, tp2, "TP2", filters)
    else:
        exits += split_exit(quantity, tp1, "TP1", filters)
    identity = hashlib.sha256(
        json.dumps(
            {
                "family": family,
                "symbol": symbol,
                "side": side,
                "setup": setup_key,
                "entry": str(entry),
                "stop": str(stop),
                "tp1": str(tp1),
                "tp2": str(tp2),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return TradePlan(
        family,
        symbol,
        side,
        decision_ms,
        identity,
        entry,
        quantity,
        leverage,
        stop,
        tp1,
        tp2,
        hold_ms,
        exits,
    )


def scalper_plan(
    signal: ScalperSignal,
    filters: SymbolFilters,
    allowed_leverages: tuple[int, ...] = (1,),
    equity: Decimal | None = None,
    available_margin: Decimal | None = None,
    remaining_daily_risk: Decimal | None = None,
    capital: RuntimeCapitalPolicy = DEFAULT_CAPITAL_POLICY,
) -> TradePlan:
    if signal.side not in {"BUY", "SELL"}:
        raise IneligibleTrade("Unsupported Macro Scalper side")
    return build_plan(
        family="MACRO_SCALPER",
        symbol=signal.symbol,
        side=signal.side,
        entry=signal.sweep_price,
        stop=signal.stop_loss,
        tp1=signal.take_profit,
        tp2=None,
        decision_ms=signal.timestamp_ms + 900_000,
        hold_ms=signal.max_hold_bars * 900_000,
        setup_key=str(signal.timestamp_ms),
        filters=filters,
        allowed_leverages=allowed_leverages,
        capital=capital,
        equity=equity,
        available_margin=available_margin,
        remaining_daily_risk=remaining_daily_risk,
    )


def ict_plan(
    setup: TwinsSetupState,
    decision_ms: int,
    filters: SymbolFilters,
    allowed_leverages: tuple[int, ...] = (1,),
    equity: Decimal | None = None,
    available_margin: Decimal | None = None,
    remaining_daily_risk: Decimal | None = None,
    capital: RuntimeCapitalPolicy = DEFAULT_CAPITAL_POLICY,
) -> TradePlan:
    if not setup.step_6_ready or setup.side is None or setup.active_pda is None:
        raise IneligibleTrade("ICT setup is not ready")
    if setup.confirmation_ms is None or not 0 <= decision_ms - setup.confirmation_ms < 60_000:
        raise IneligibleTrade("ICT confirmation is missing or belongs to an earlier closed minute")
    if any(
        value is None
        for value in (
            setup.m1_cisd_price,
            setup.stop_loss,
            setup.take_profit_partial,
            setup.take_profit_final,
        )
    ):
        raise IneligibleTrade("ICT setup has incomplete order parameters")
    assert setup.m1_cisd_price is not None and setup.stop_loss is not None
    assert setup.take_profit_partial is not None and setup.take_profit_final is not None
    return build_plan(
        family="ICT_TWINS",
        symbol=setup.symbol,
        side=setup.side,
        entry=setup.m1_cisd_price,
        stop=setup.stop_loss,
        tp1=setup.take_profit_partial,
        tp2=setup.take_profit_final,
        decision_ms=decision_ms,
        hold_ms=12 * 900_000,
        setup_key=f"{setup.active_pda.creation_ts}:{setup.m5_cisd_price}:{setup.confirmation_ms}",
        filters=filters,
        allowed_leverages=allowed_leverages,
        capital=capital,
        equity=equity,
        available_margin=available_margin,
        remaining_daily_risk=remaining_daily_risk,
    )
