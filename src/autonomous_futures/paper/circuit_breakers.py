"""Phase 255: Automated Risk Circuit Breakers & Hardened Shared Margin Architecture.

Implements Pydantic v2 schemas and runtime defense mechanisms:
- Single shared 100.00 USDT cash account across BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT.
- Strict 80.00% max margin utilization cap and guaranteed >= 20.00% unencumbered buffer.
- Dynamic leverage de-escalation: clamped to 1.0x on volatility or slippage surge.
- 3-stage Circuit Breakers (NORMAL -> THROTTLED -> HALTED -> EMERGENCY_FLAT). No auto-resume.
- Realistic Adverse Gap Stop Execution: P_fill = min(O_t, P_stop) * (1 - S_stress).
- Emergency Position Close-Out: orderly de-risking preventing deficit balances (Equity > 0).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from autonomous_futures.domain.errors import DomainViolation


class Phase255DomainModel(BaseModel):
    """Base domain model for Phase 255 with strict forbidding of extra fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


StrictPositiveDecimal = Annotated[Decimal, Field(strict=True, gt=Decimal("0"))]
StrictNonNegativeDecimal = Annotated[Decimal, Field(strict=True, ge=Decimal("0"))]


class CircuitBreakerConfig(Phase255DomainModel):
    """Immutable parameters governing automated volatility and slippage circuit breakers."""

    atr_lookback: int = Field(default=14, ge=5, le=50)
    baseline_window_bars: int = Field(default=288, ge=72, le=2016)
    volatility_throttle_ratio: StrictPositiveDecimal = Field(default=Decimal("2.0"))
    volatility_halt_ratio: StrictPositiveDecimal = Field(default=Decimal("3.0"))
    slippage_throttle_bps: StrictPositiveDecimal = Field(default=Decimal("10.0"))
    slippage_halt_bps: StrictPositiveDecimal = Field(default=Decimal("20.0"))
    drawdown_throttle: StrictPositiveDecimal = Field(default=Decimal("0.05"))
    drawdown_halt: StrictPositiveDecimal = Field(default=Decimal("0.08"))
    catastrophic_drawdown: StrictPositiveDecimal = Field(default=Decimal("0.10"))
    emergency_wick_threshold: StrictPositiveDecimal = Field(default=Decimal("0.10"))

    @model_validator(mode="after")
    def validate_threshold_hierarchy(self) -> CircuitBreakerConfig:
        if not (self.volatility_throttle_ratio < self.volatility_halt_ratio):
            raise ValueError("volatility_throttle_ratio must be less than volatility_halt_ratio")
        if not (self.slippage_throttle_bps < self.slippage_halt_bps):
            raise ValueError("slippage_throttle_bps must be less than slippage_halt_bps")
        if not (self.drawdown_throttle < self.drawdown_halt < self.catastrophic_drawdown):
            raise ValueError("drawdown thresholds must be strictly ordered")
        return self


class CircuitBreakerEvaluationResult(Phase255DomainModel):
    """Telemetry snapshot evaluating market stress conditions against circuit breaker rules."""

    evaluated_at: datetime
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    rolling_atr: StrictPositiveDecimal
    baseline_atr: StrictPositiveDecimal
    volatility_ratio: StrictPositiveDecimal
    current_slippage_bps: StrictNonNegativeDecimal
    portfolio_drawdown: StrictNonNegativeDecimal
    margin_utilization: StrictNonNegativeDecimal
    recommended_state: Literal["NORMAL", "THROTTLED", "HALTED", "EMERGENCY_FLAT"]
    inhibit_new_entries: bool
    clamped_max_leverage: StrictPositiveDecimal
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @field_validator("evaluated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("evaluated_at must be timezone-aware UTC")
        return value.astimezone(UTC)


class EmergencyLiquidationEvent(Phase255DomainModel):
    """Audit record capturing an orderly emergency position liquidation under distress."""

    trade_id: str = Field(min_length=1)
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    side: Literal["LONG", "SHORT"]
    quantity: StrictPositiveDecimal
    entry_fill_price: StrictPositiveDecimal
    theoretical_stop_price: StrictPositiveDecimal
    gapped_market_price: StrictPositiveDecimal
    executed_fill_price: StrictPositiveDecimal
    effective_slippage_bps: StrictNonNegativeDecimal
    gross_pnl: Decimal
    exit_fee: StrictNonNegativeDecimal
    net_pnl: Decimal
    released_margin: StrictPositiveDecimal
    pre_close_equity: Decimal
    post_close_equity: StrictPositiveDecimal  # Guaranteed > 0
    liquidation_reason: Literal[
        "adverse_gap_wick",
        "margin_buffer_depletion",
        "catastrophic_drawdown",
        "circuit_breaker_emergency_flat",
    ]
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("occurred_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_non_negative_equity(self) -> EmergencyLiquidationEvent:
        if self.post_close_equity <= Decimal("0"):
            raise ValueError("post_close_equity must be strictly positive (deficit forbidden)")
        return self


class StressTestScenarioResult(Phase255DomainModel):
    """Aggregate result of a synthetic shock vector applied to the portfolio margin model."""

    scenario_name: str = Field(min_length=1)
    shock_type: Literal[
        "baseline",
        "flash_crash",
        "flash_crash_wick",
        "slippage_surge",
        "spread_blowout",
        "rapid_whipsaw",
        "volatility_whipsaw",
        "composite_crisis",
    ]
    price_shock_pct: Decimal = Field(le=Decimal("0"))
    slippage_multiplier: int = Field(ge=1)
    starting_equity: StrictPositiveDecimal = Field(default=Decimal("100.00"))
    ending_equity: StrictPositiveDecimal  # Must survive with > 0
    min_observed_equity: StrictPositiveDecimal = Field(default=Decimal("100.00"))
    max_observed_drawdown: StrictNonNegativeDecimal
    max_observed_margin_utilization: StrictNonNegativeDecimal = Field(le=Decimal("0.80"))
    min_observed_equity_buffer: StrictPositiveDecimal = Field(ge=Decimal("0.20"))
    total_trades_closed: int = Field(ge=0)
    emergency_liquidations_count: int = Field(ge=0)
    capital_survived: Literal[True] = True
    account_liquidated: Literal[False] = False  # Zero account liquidation invariant
    deficit_balance: Literal[False] = False  # Zero deficit balance invariant
    zero_balance_drift: Literal[True] = True
    exchange_access: Literal[False] = False
    orders: Literal[0] = 0


# Stage ordering for monotonic downward progression
_CIRCUIT_STATE_ORDER: dict[str, int] = {
    "NORMAL": 0,
    "THROTTLED": 1,
    "HALTED": 2,
    "EMERGENCY_FLAT": 3,
}


def calculate_adverse_gap_fill(
    side: Literal["LONG", "SHORT"],
    bar_open: Decimal,
    stop_price: Decimal,
    slippage_rate: Decimal,
) -> tuple[Decimal, Decimal]:
    """Calculate realistic stop execution under adverse opening gap or wick conditions.

    For LONG:
    If market opened below stop (bar_open < stop_price), fill is based on gapped open:
        P_raw = min(bar_open, stop_price)
        P_fill = P_raw * (1 - slippage_rate)
    For SHORT:
    If market opened above stop (bar_open > stop_price), fill is based on gapped open:
        P_raw = max(bar_open, stop_price)
        P_fill = P_raw * (1 + slippage_rate)

    Returns (raw_exit_price, executed_fill_price).
    """
    if side == "LONG":
        raw_exit = min(bar_open, stop_price)
        fill_price = raw_exit * (Decimal("1.0") - slippage_rate)
    else:
        raw_exit = max(bar_open, stop_price)
        fill_price = raw_exit * (Decimal("1.0") + slippage_rate)

    return raw_exit, fill_price


class HardenedSharedMarginAccount:
    """Hardened shared portfolio margin manager with dynamic leverage de-escalation,

    automated 3-stage circuit breakers, and emergency position liquidation defense.
    """

    def __init__(
        self,
        starting_capital: Decimal = Decimal("100.00"),
        max_utilization: Decimal = Decimal("0.80"),
        base_allocation_fraction: Decimal = Decimal("0.20"),
        min_reserve_buffer: Decimal = Decimal("0.20"),
        config: CircuitBreakerConfig | None = None,
    ) -> None:
        self.starting_capital = starting_capital
        self.max_utilization = max_utilization
        self.base_allocation_fraction = base_allocation_fraction
        self.min_reserve_buffer = min_reserve_buffer
        self.config = config or CircuitBreakerConfig()

        self.cash = starting_capital
        self._locked_margin_by_trade: dict[str, Decimal] = {}
        self._trade_leverage: dict[str, Decimal] = {}
        self.peak_portfolio_equity = starting_capital
        self.max_observed_utilization = Decimal("0.0")
        self.min_observed_buffer = Decimal("1.0")
        self.min_observed_equity = starting_capital

        self.current_state: Literal["NORMAL", "THROTTLED", "HALTED", "EMERGENCY_FLAT"] = "NORMAL"
        self.state_history: list[tuple[datetime, str, str]] = []
        self.emergency_liquidations: list[EmergencyLiquidationEvent] = []

    def total_locked_margin(self) -> Decimal:
        """Return sum of locked margin across all active positions."""
        return sum(self._locked_margin_by_trade.values(), Decimal("0"))

    def current_equity(self, active_unrealized_pnl: Decimal = Decimal("0")) -> Decimal:
        """Calculate total account equity = cash + active unrealized PnL."""
        eq = self.cash + active_unrealized_pnl
        if eq < self.min_observed_equity:
            self.min_observed_equity = eq
        return eq

    def margin_utilization(self, equity: Decimal) -> Decimal:
        """Calculate margin utilization = total_locked / equity. Clamped to 1.0 if equity <= 0."""
        if equity <= Decimal("0"):
            return Decimal("1.0")
        util = self.total_locked_margin() / equity
        if util > self.max_observed_utilization:
            self.max_observed_utilization = util
        return util

    def unencumbered_reserve_buffer(self, equity: Decimal) -> Decimal:
        """Calculate unencumbered reserve buffer = (equity - total_locked) / equity."""
        if equity <= Decimal("0"):
            return Decimal("0.0")
        buf = max(Decimal("0.0"), (equity - self.total_locked_margin()) / equity)
        if buf < self.min_observed_buffer:
            self.min_observed_buffer = buf
        return buf

    def available_margin(self, equity: Decimal) -> Decimal:
        """Calculate available margin under the 80% utilization ceiling."""
        max_allowed = equity * self.max_utilization
        locked = self.total_locked_margin()
        return max(Decimal("0"), max_allowed - locked)

    def calculate_hardened_leverage(
        self,
        confidence: Decimal,
        volatility_ratio: Decimal = Decimal("1.0"),
        slippage_ratio: Decimal = Decimal("1.0"),
    ) -> Decimal:
        """Calculate dynamic leverage scaled by conviction, de-escalated under stress.

        In NORMAL state:
            leverage = 1.0 + 4.0 * (confidence - 0.50), clamped to [1.0, 3.0].
        Under volatility surge (R_vol >= 2.0) or slippage surge (R_slip >= 5.0) or THROTTLED state:
            leverage is clamped to 1.0x.
        In HALTED or EMERGENCY_FLAT state:
            leverage is clamped to 0.0x (no entries permitted).
        """
        if self.current_state in ("HALTED", "EMERGENCY_FLAT"):
            return Decimal("0.0")

        if (
            self.current_state == "THROTTLED"
            or volatility_ratio >= self.config.volatility_throttle_ratio
            or slippage_ratio >= Decimal("5.0")
        ):
            # De-escalate leverage to 1.0x under stress
            return Decimal("1.0")

        # Normal confidence-scaled leverage model: 1.0x to 3.0x
        scaled = Decimal("1.0") + Decimal("4.0") * (confidence - Decimal("0.50"))
        return max(Decimal("1.0"), min(Decimal("3.0"), scaled))

    def evaluate_circuit_breaker(
        self,
        symbol: str,
        current_atr: Decimal,
        baseline_atr: Decimal,
        current_slippage_bps: Decimal,
        current_equity: Decimal,
        peak_equity: Decimal,
        bar_ts: datetime,
        adverse_wick_pct: Decimal = Decimal("0"),
    ) -> CircuitBreakerEvaluationResult:
        """Evaluate circuit breaker rules against rolling market and portfolio metrics.

        Monotonically transitions state downward when stress thresholds are breached:
        NORMAL -> THROTTLED -> HALTED -> EMERGENCY_FLAT.
        Automatic recovery to higher risk states is strictly forbidden.
        """
        vol_ratio = current_atr / baseline_atr if baseline_atr > 0 else Decimal("1.0")
        drawdown = (
            max(Decimal("0.0"), (peak_equity - current_equity) / peak_equity)
            if peak_equity > 0
            else Decimal("1.0")
        )
        utilization = self.margin_utilization(current_equity)

        reason_codes: list[str] = []
        recommended_state: Literal["NORMAL", "THROTTLED", "HALTED", "EMERGENCY_FLAT"] = "NORMAL"

        # Check EMERGENCY_FLAT conditions
        if (
            adverse_wick_pct >= self.config.emergency_wick_threshold
            or utilization > self.max_utilization
            or drawdown >= self.config.catastrophic_drawdown
        ):
            recommended_state = "EMERGENCY_FLAT"
            if adverse_wick_pct >= self.config.emergency_wick_threshold:
                reason_codes.append("ADVERSE_WICK_EMERGENCY")
            if utilization > self.max_utilization:
                reason_codes.append("MARGIN_BUFFER_DEPLETION")
            if drawdown >= self.config.catastrophic_drawdown:
                reason_codes.append("CATASTROPHIC_DRAWDOWN_LIMIT")
        # Check HALTED conditions
        elif (
            vol_ratio >= self.config.volatility_halt_ratio
            or current_slippage_bps >= self.config.slippage_halt_bps
            or drawdown >= self.config.drawdown_halt
        ):
            recommended_state = "HALTED"
            if vol_ratio >= self.config.volatility_halt_ratio:
                reason_codes.append("CIRCUIT_BREAKER_VOLATILITY_HALT")
            if current_slippage_bps >= self.config.slippage_halt_bps:
                reason_codes.append("CIRCUIT_BREAKER_SLIPPAGE_HALT")
            if drawdown >= self.config.drawdown_halt:
                reason_codes.append("DRAWDOWN_HALT_LIMIT")
        # Check THROTTLED conditions
        elif (
            vol_ratio >= self.config.volatility_throttle_ratio
            or current_slippage_bps >= self.config.slippage_throttle_bps
            or drawdown >= self.config.drawdown_throttle
        ):
            recommended_state = "THROTTLED"
            if vol_ratio >= self.config.volatility_throttle_ratio:
                reason_codes.append("CIRCUIT_BREAKER_VOLATILITY_THROTTLE")
            if current_slippage_bps >= self.config.slippage_throttle_bps:
                reason_codes.append("CIRCUIT_BREAKER_SLIPPAGE_THROTTLE")
            if drawdown >= self.config.drawdown_throttle:
                reason_codes.append("DRAWDOWN_THROTTLE_LIMIT")
        else:
            reason_codes.append("MARKET_CONDITIONS_NOMINAL")

        # Enforce monotonic downward state transition (automatic recovery forbidden)
        current_rank = _CIRCUIT_STATE_ORDER[self.current_state]
        recommended_rank = _CIRCUIT_STATE_ORDER[recommended_state]

        if recommended_rank > current_rank:
            # Monotonic downgrade
            old_state = self.current_state
            self.current_state = recommended_state
            self.state_history.append(
                (
                    bar_ts,
                    f"{old_state}->{recommended_state}",
                    ",".join(reason_codes),
                )
            )

        # Active state determines entry inhibition and leverage limits
        inhibit_entries = self.current_state in ("HALTED", "EMERGENCY_FLAT")
        clamped_leverage = (
            Decimal("0.0001")
            if inhibit_entries
            else (Decimal("1.0") if self.current_state == "THROTTLED" else Decimal("3.0"))
        )

        return CircuitBreakerEvaluationResult(
            evaluated_at=bar_ts,
            symbol=symbol,
            rolling_atr=current_atr,
            baseline_atr=baseline_atr,
            volatility_ratio=vol_ratio,
            current_slippage_bps=current_slippage_bps,
            portfolio_drawdown=drawdown,
            margin_utilization=utilization,
            recommended_state=self.current_state,
            inhibit_new_entries=inhibit_entries,
            clamped_max_leverage=clamped_leverage,
            reason_codes=tuple(reason_codes),
        )

    def allocate_order(
        self,
        symbol: str,
        confidence: Decimal,
        mark_price: Decimal,
        current_equity: Decimal,
        volatility_ratio: Decimal = Decimal("1.0"),
        slippage_ratio: Decimal = Decimal("1.0"),
    ) -> tuple[Decimal, Decimal, Decimal] | None:
        """Calculate margin allocation, confidence-scaled leverage, and trade quantity.

        Enforces:
        - Entry inhibition in HALTED or EMERGENCY_FLAT states.
        - Strict 80.00% utilization ceiling (preserving >= 20.00% unencumbered buffer).
        - Dynamic leverage de-escalation (clamped to 1.0x on volatility or slippage surge).
        - Halved allocation fraction (10%) in THROTTLED state.
        Returns (base_margin, leverage, quantity) or None if allocation is rejected.
        """
        if self.current_state in ("HALTED", "EMERGENCY_FLAT"):
            return None

        if current_equity <= Decimal("0"):
            return None

        # Base allocation: 20% normal, throttled to 10% under distress
        fraction = (
            self.base_allocation_fraction / Decimal("2.0")
            if self.current_state == "THROTTLED"
            else self.base_allocation_fraction
        )

        base_margin = current_equity * fraction
        locked_after = self.total_locked_margin() + base_margin
        utilization_after = locked_after / current_equity

        # Strictly enforce utilization ceiling (<= 80%)
        if utilization_after > self.max_utilization:
            return None

        # Strictly preserve >= 20% unencumbered equity buffer
        buffer_after = (current_equity - locked_after) / current_equity
        if buffer_after < self.min_reserve_buffer:
            return None

        # Ensure cash is sufficient for execution fees
        if self.cash < base_margin * Decimal("0.005"):
            return None

        leverage = self.calculate_hardened_leverage(confidence, volatility_ratio, slippage_ratio)
        if leverage <= Decimal("0"):
            return None

        notional = base_margin * leverage
        raw_quantity = notional / mark_price
        quantity = Decimal(f"{raw_quantity:.6f}")
        if quantity <= Decimal("0"):
            return None

        return base_margin, leverage, quantity

    def record_open(
        self,
        trade_id: str,
        margin_allocated: Decimal,
        leverage: Decimal,
        entry_fee: Decimal,
        equity: Decimal,
    ) -> None:
        """Record trade opening: lock margin, debit entry fee, and track peak metrics."""
        self._locked_margin_by_trade[trade_id] = margin_allocated
        self._trade_leverage[trade_id] = leverage
        self.cash -= entry_fee
        current_util = self.margin_utilization(equity)
        if current_util > self.max_observed_utilization:
            self.max_observed_utilization = current_util
        self.unencumbered_reserve_buffer(equity)

    def record_close(self, trade_id: str, gross_pnl: Decimal, exit_fee: Decimal) -> None:
        """Record trade closure: release locked margin and settle cash with exact Decimal math."""
        if trade_id in self._locked_margin_by_trade:
            del self._locked_margin_by_trade[trade_id]
        if trade_id in self._trade_leverage:
            del self._trade_leverage[trade_id]
        self.cash += gross_pnl - exit_fee

    def emergency_liquidate_positions(
        self,
        active_trades: dict[str, dict[str, Any]],
        current_prices: dict[str, Decimal],
        current_opens: dict[str, Decimal],
        slippage_rate: Decimal,
        fee_rate: Decimal,
        occurred_at: datetime,
        reason: Literal[
            "adverse_gap_wick",
            "margin_buffer_depletion",
            "catastrophic_drawdown",
            "circuit_breaker_emergency_flat",
        ],
    ) -> list[EmergencyLiquidationEvent]:
        """Execute orderly emergency market liquidation of open positions to defend equity.

        Prioritizes liquidating positions by largest mark-to-market loss percentage descending.
        Calculates gapped adverse fill price P_fill = min(O_t, P_stop) * (1 - S_stress).
        Releases locked margin, updates cash balance, and verifies non-negative equity.
        """
        if not active_trades:
            return []

        # Calculate mark-to-market unrealized PnL per position
        trade_pnl_list: list[tuple[str, Decimal, Decimal]] = []
        for sym, tinfo in active_trades.items():
            entry = tinfo["open_entry"]
            cur_price = current_prices.get(sym, entry.fill_price)
            if tinfo["side"] == "LONG":
                unrealized = (cur_price - entry.fill_price) * entry.quantity
            else:
                unrealized = (entry.fill_price - cur_price) * entry.quantity
            margin = self._locked_margin_by_trade.get(tinfo["trade_id"], Decimal("1.0"))
            loss_pct = unrealized / margin if margin > 0 else Decimal("-100.0")
            trade_pnl_list.append((sym, loss_pct, unrealized))

        # Sort by largest loss percentage ascending (most negative first)
        trade_pnl_list.sort(key=lambda item: item[1])

        events: list[EmergencyLiquidationEvent] = []

        for sym, _, _ in trade_pnl_list:
            if sym not in active_trades:
                continue

            tinfo = active_trades[sym]
            trade_id = tinfo["trade_id"]
            entry = tinfo["open_entry"]
            side = tinfo["side"]
            stop_price = tinfo.get("stop_price", entry.fill_price)
            bar_open = current_opens.get(sym, current_prices[sym])

            # Compute realistic adverse gap fill
            raw_exit, fill_price = calculate_adverse_gap_fill(
                side=side,
                bar_open=bar_open,
                stop_price=stop_price,
                slippage_rate=slippage_rate,
            )

            # Compute accounting components
            if side == "LONG":
                gross_pnl = (fill_price - entry.fill_price) * entry.quantity
            else:
                gross_pnl = (entry.fill_price - fill_price) * entry.quantity

            exit_fee = entry.quantity * fill_price * fee_rate
            net_pnl = gross_pnl - exit_fee

            pre_close_eq = self.cash
            released_margin = self._locked_margin_by_trade.get(trade_id, Decimal("0"))

            # Settle position
            self.record_close(trade_id=trade_id, gross_pnl=gross_pnl, exit_fee=exit_fee)
            post_close_eq = self.cash

            # Calculate effective slippage in basis points
            effective_slippage_bps = (
                abs(fill_price - raw_exit) / raw_exit * Decimal("10000")
                if raw_exit > 0
                else Decimal("0")
            )

            event = EmergencyLiquidationEvent(
                trade_id=trade_id,
                symbol=sym,
                side=side,
                quantity=entry.quantity,
                entry_fill_price=entry.fill_price,
                theoretical_stop_price=stop_price,
                gapped_market_price=raw_exit,
                executed_fill_price=fill_price,
                effective_slippage_bps=effective_slippage_bps,
                gross_pnl=gross_pnl,
                exit_fee=exit_fee,
                net_pnl=net_pnl,
                released_margin=released_margin,
                pre_close_equity=pre_close_eq,
                post_close_equity=post_close_eq,
                liquidation_reason=reason,
                occurred_at=occurred_at,
            )
            events.append(event)
            self.emergency_liquidations.append(event)
            del active_trades[sym]

        return events

    def request_resume(self, evidence: Any) -> None:
        """Attempt to resume NORMAL state. Automatic resume is strictly forbidden."""
        if not (
            hasattr(evidence, "operator_approved")
            and evidence.operator_approved is True
            and getattr(evidence, "reconciled", False) is True
            and getattr(evidence, "incident_resolved", False) is True
            and getattr(evidence, "data_fresh", False) is True
            and getattr(evidence, "risk_healthy", False) is True
        ):
            raise DomainViolation(
                "automatic resume is forbidden: operator approval and complete evidence required"
            )

        self.current_state = "NORMAL"
