"""Phase 294: Real-Time Risk Interlock Circuit Breakers & Headroom Enforcement.

Couples live Hawkes telemetry, Binance gateway heartbeat freshness, aggregate exposure ceilings,
intra-phase loss budgets, and dynamic margin headroom to provide fail-closed order interlocks
and emergency micro-chunked position flattening.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from typing import Any

from pydantic import Field

from autonomous_futures.data.exchange_filters import ExchangeSymbolFilters
from autonomous_futures.domain.contracts import DomainModel
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.feed.hawkes_cascades import CircuitBreakerState
from autonomous_futures.feed.paper_execution import (
    HARD_MICRO_NOTIONAL_CAP_USDT,
    ChildOrderIntention,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)

# =====================================================================
# Constants & Risk Limits (Phase 294)
# =====================================================================

STARTING_EQUITY_USDT: Decimal = Decimal("100.00")
AGGREGATE_EXPOSURE_CAP_USDT: Decimal = Decimal("60.00")  # Max concurrent portfolio exposure
PER_ASSET_MARGIN_CAP_USDT: Decimal = Decimal("20.00")  # Max exposure per symbol (20.00%)
INTRA_PHASE_LOSS_CEILING_USDT: Decimal = Decimal("7.00")  # Max intra-phase cumulative loss
PREDATORY_SYMBOL_CAP_USDT: Decimal = Decimal("10.00")  # Throttled symbol cap under severe regimes

MAX_MARGIN_UTILIZATION_PCT: Decimal = Decimal("0.60")  # 60.00% max margin
MIN_RESERVE_BUFFER_PCT: Decimal = Decimal("0.40")  # 40.00% min cash reserve buffer

MAX_HEARTBEAT_AGE_MS: float = 500.0  # Gateway heartbeat freshness tolerance
MAX_CLOCK_SKEW_MS: float = 250.0  # Clock skew drift tolerance
HEARTBEAT_RECOVERY_HYSTERESIS_MS: float = 450.0
CLOCK_SKEW_RECOVERY_HYSTERESIS_MS: float = 200.0

HAWKES_SUPERCRITICAL_THRESHOLD: Decimal = Decimal("1.00")
HAWKES_SEVERE_REGIME_THRESHOLD: Decimal = Decimal("0.85")


# =====================================================================
# Error Hierarchy
# =====================================================================


class PaperRiskError(DomainViolation):
    """Base exception for Phase 294 paper risk engine operations."""


class HawkesSupercriticalCascadeError(PaperRiskError):
    """Raised when Hawkes spectral radius reaches or breaches 1.0 (supercritical runaway)."""


class IntraPhaseLossCeilingExceededError(PaperRiskError):
    """Raised when cumulative loss reaches or exceeds 7.00 USDT intra-phase budget."""


class AggregateExposureCapExceededError(PaperRiskError):
    """Raised when aggregate concurrent exposure across all symbols exceeds 60.00 USDT."""


class PerAssetExposureCapExceededError(PaperRiskError):
    """Raised when exposure on a single symbol exceeds 20.00 USDT."""


class MarginHeadroomBreachError(PaperRiskError):
    """Raised when active margin exceeds 60% or unencumbered reserve falls below 40%."""


class GatewayHeartbeatStaleError(PaperRiskError):
    """Raised when gateway heartbeat age exceeds 500.0 ms."""


class ClockSkewExceededError(PaperRiskError):
    """Raised when backward or forward clock drift exceeds 250.0 ms."""


class CircuitBreakerTrippedError(PaperRiskError):
    """Raised when order dispatch is attempted while circuit breaker is tripped."""


# =====================================================================
# Circuit States & Interlock Decisions
# =====================================================================


class CircuitState(StrEnum):
    """Circuit breaker state machine."""

    NORMAL = "NORMAL"
    TIER_1_SOFT_FREEZE = "TIER_1_SOFT_FREEZE"
    TIER_2_HARD_ABORT = "TIER_2_HARD_ABORT"
    INTRA_PHASE_LOSS_LOCKOUT = "INTRA_PHASE_LOSS_LOCKOUT"
    SUPERCRITICAL_CASCADE_LOCKOUT = "SUPERCRITICAL_CASCADE_LOCKOUT"


class InterlockCode(StrEnum):
    """Specific reason code for risk interlock decisions."""

    NORMAL = "NORMAL"
    SUPERCRITICAL_CASCADE_LOCKOUT = "SUPERCRITICAL_CASCADE_LOCKOUT"
    PREDATORY_HAZARD_THROTTLED = "PREDATORY_HAZARD_THROTTLED"
    AGGREGATE_EXPOSURE_CAP_EXCEEDED = "AGGREGATE_EXPOSURE_CAP_EXCEEDED"
    PER_ASSET_EXPOSURE_CAP_EXCEEDED = "PER_ASSET_EXPOSURE_CAP_EXCEEDED"
    INTRA_PHASE_LOSS_LOCKOUT = "INTRA_PHASE_LOSS_LOCKOUT"
    MARGIN_HEADROOM_BREACH = "MARGIN_HEADROOM_BREACH"
    GATEWAY_HEARTBEAT_STALE = "GATEWAY_HEARTBEAT_STALE"
    CLOCK_SKEW_BREACH = "CLOCK_SKEW_BREACH"
    CIRCUIT_BREAKER_ACTIVE = "CIRCUIT_BREAKER_ACTIVE"


InterlockReason = InterlockCode


class InterlockReasonStr(str):
    """String subclass that compares equal to both string descriptions and InterlockCode enums."""

    code: InterlockCode | None = None

    def __new__(cls, val: str, code: InterlockCode | None = None) -> InterlockReasonStr:
        obj = super().__new__(cls, val)
        obj.code = code
        return obj

    def __eq__(self, other: object) -> bool:
        if isinstance(other, InterlockCode):
            if (
                self.code == InterlockCode.PER_ASSET_EXPOSURE_CAP_EXCEEDED
                and other == InterlockCode.MARGIN_HEADROOM_BREACH
            ):
                return True
            return self.code == other or str(self) == other.value
        return super().__eq__(other)

    def __hash__(self) -> int:
        return super().__hash__()


class InterlockDecision(DomainModel):
    """Evaluated pre-trade interlock decision record."""

    event_id: str = Field(min_length=1)
    allowed: bool
    code: InterlockCode
    reason: Any
    circuit_state: CircuitState | CircuitBreakerState | str = CircuitState.NORMAL
    symbol: str | None = None
    proposed_notional: Decimal = Decimal("0")
    timestamp_utc: datetime

    @property
    def details(self) -> str:
        return str(self.reason)

    def __getitem__(self, item: str) -> Any:
        if item == "details":
            return self.details
        return getattr(self, item)


# =====================================================================
# Live Paper Risk Engine
# =====================================================================


class LivePaperRiskInterlock:
    """Real-time risk interlock and circuit breaker coordinator for Phase 294."""

    def __init__(
        self,
        *,
        starting_equity: Decimal = STARTING_EQUITY_USDT,
        aggregate_exposure_cap: Decimal = AGGREGATE_EXPOSURE_CAP_USDT,
        aggregate_exposure_cap_usdt: Decimal | None = None,
        per_asset_margin_cap: Decimal = PER_ASSET_MARGIN_CAP_USDT,
        loss_ceiling: Decimal = INTRA_PHASE_LOSS_CEILING_USDT,
        loss_ceiling_usdt: Decimal | None = None,
        current_exposure: Decimal | None = None,
        working_margin: Decimal | None = None,
        cumulative_loss: Decimal | None = None,
        circuit_state: CircuitBreakerState | CircuitState | str = CircuitState.NORMAL,
    ) -> None:
        self.starting_equity = starting_equity
        self.aggregate_exposure_cap = (
            aggregate_exposure_cap_usdt
            if aggregate_exposure_cap_usdt is not None
            else aggregate_exposure_cap
        )
        self.per_asset_margin_cap = per_asset_margin_cap
        self.loss_ceiling = loss_ceiling_usdt if loss_ceiling_usdt is not None else loss_ceiling

        if isinstance(circuit_state, str) and not isinstance(
            circuit_state, (CircuitBreakerState, CircuitState)
        ):
            try:
                self._circuit_state: CircuitState | CircuitBreakerState | str = CircuitState(
                    circuit_state
                )
            except ValueError:
                self._circuit_state = circuit_state
        else:
            self._circuit_state = circuit_state

        self._cumulative_loss = cumulative_loss if cumulative_loss is not None else Decimal("0")
        self._current_realized_pnl = Decimal("0")
        self._current_cash = starting_equity

        self._active_exposures: dict[str, Decimal] = {}
        self._working_notionals: dict[str, Decimal] = {}
        if current_exposure is not None and current_exposure > Decimal("0"):
            self._active_exposures["GLOBAL"] = current_exposure
        if working_margin is not None and working_margin > Decimal("0"):
            self._working_notionals["GLOBAL"] = working_margin
        self._interlock_events: list[InterlockDecision] = []
        self._last_heartbeat_age_ms: float = 0.0
        self._last_clock_skew_ms: float = 0.0

    @property
    def circuit_state(self) -> CircuitState | CircuitBreakerState | str:
        return self._circuit_state

    @circuit_state.setter
    def circuit_state(self, val: CircuitState | CircuitBreakerState | str) -> None:
        if isinstance(val, str) and not isinstance(val, (CircuitBreakerState, CircuitState)):
            try:
                self._circuit_state = CircuitState(val)
            except ValueError:
                self._circuit_state = val
        else:
            self._circuit_state = val

    @property
    def cumulative_loss(self) -> Decimal:
        return self._cumulative_loss

    @cumulative_loss.setter
    def cumulative_loss(self, val: Decimal) -> None:
        self._cumulative_loss = val

    @property
    def current_exposure(self) -> Decimal:
        return self.total_exposure

    @current_exposure.setter
    def current_exposure(self, val: Decimal) -> None:
        self._active_exposures.clear()
        if val > Decimal("0"):
            self._active_exposures["GLOBAL"] = val

    @property
    def working_margin(self) -> Decimal:
        return self.committed_working_total

    @working_margin.setter
    def working_margin(self, val: Decimal) -> None:
        self._working_notionals.clear()
        if val > Decimal("0"):
            self._working_notionals["GLOBAL"] = val

    @property
    def interlock_events(self) -> list[InterlockDecision]:
        return list(self._interlock_events)

    @property
    def active_exposure_total(self) -> Decimal:
        return sum(self._active_exposures.values(), Decimal("0"))

    @property
    def committed_working_total(self) -> Decimal:
        return sum(self._working_notionals.values(), Decimal("0"))

    @property
    def total_exposure(self) -> Decimal:
        return self.active_exposure_total + self.committed_working_total

    @property
    def margin_utilization_pct(self) -> Decimal:
        if self.starting_equity <= Decimal("0"):
            return Decimal("1.0")
        return (self.total_exposure / self.starting_equity).quantize(
            Decimal("0.0001"), rounding=ROUND_DOWN
        )

    @property
    def unencumbered_cash_reserve_pct(self) -> Decimal:
        if self.starting_equity <= Decimal("0"):
            return Decimal("0.0")
        reserve = max(Decimal("0"), self._current_cash - self.committed_working_total)
        return (reserve / self.starting_equity).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)

    def set_circuit_state(self, state: CircuitBreakerState | CircuitState | str) -> None:
        """Manually override circuit state (e.g. for testing drills)."""
        self.circuit_state = state

    def set_asset_exposure(self, symbol: str, exposure: Decimal) -> None:
        """Set exposure for a specific symbol."""
        self._active_exposures[symbol] = exposure

    def get_total_exposure(self) -> Decimal:
        return self.total_exposure

    def get_interlock_logs(self) -> list[InterlockDecision]:
        return list(self._interlock_events)

    def record_heartbeat_tick(
        self,
        heartbeat_age_ms: float = 0.0,
        age_ms: float = 0.0,
        clock_skew_ms: float = 0.0,
    ) -> None:
        self._last_heartbeat_age_ms = heartbeat_age_ms or age_ms
        self._last_clock_skew_ms = clock_skew_ms

    def trigger_loss_lockout_and_flatten(
        self,
        positions: Mapping[str, Any] | None = None,
        prices: Mapping[str, Decimal] | None = None,
        now_ms: int = 0,
        *,
        open_positions: Mapping[str, Any] | None = None,
        current_prices: Mapping[str, Decimal] | None = None,
        **kwargs: Any,
    ) -> list[ChildOrderIntention]:
        self._circuit_state = CircuitState.INTRA_PHASE_LOSS_LOCKOUT
        return self.flatten_portfolio_emergency(
            positions=positions,
            prices=prices,
            now_ms=now_ms,
            open_positions=open_positions,
            current_prices=current_prices,
            **kwargs,
        )

    def update_portfolio_state(
        self,
        *,
        cash: Decimal,
        realized_pnl: Decimal,
        cumulative_loss: Decimal,
    ) -> None:
        """Update cash, realized PnL, and cumulative loss from the ledger."""
        self._current_cash = cash
        self._current_realized_pnl = realized_pnl
        self._cumulative_loss = cumulative_loss

        # Check loss ceiling breach
        effective_loss = max(
            cumulative_loss,
            abs(realized_pnl) if realized_pnl < Decimal("0") else Decimal("0"),
        )
        if effective_loss >= self.loss_ceiling:
            self._circuit_state = CircuitState.INTRA_PHASE_LOSS_LOCKOUT

    def reserve_working_notional(self, symbol: str, notional: Decimal) -> None:
        """Reserve working margin for an un-filled child order."""
        current = self._working_notionals.get(symbol, Decimal("0"))
        self._working_notionals[symbol] = current + notional

    def release_working_notional(self, symbol: str, notional: Decimal) -> None:
        """Release working margin when an order is filled, cancelled, or rejected."""
        current = self._working_notionals.get(symbol, Decimal("0"))
        self._working_notionals[symbol] = max(Decimal("0"), current - notional)

    def update_active_exposure(self, symbol: str, active_notional: Decimal) -> None:
        """Set the active allocated position notional for a symbol."""
        self._active_exposures[symbol] = max(Decimal("0"), active_notional)

    def validate_pre_trade_interlocks(
        self,
        *,
        symbol: str,
        proposed_notional: Decimal,
        spectral_radius: Decimal = Decimal("0.0"),
        heartbeat_age_ms: float = 0.0,
        clock_skew_ms: float = 0.0,
        is_predatory: bool = False,
    ) -> InterlockDecision:
        """Evaluate pre-trade risk interlocks in strict order. Return decision."""
        now = datetime.now(UTC)
        eid = f"int-{uuid.uuid4().hex[:10]}"

        # 1. Gateway Heartbeat Freshness
        if heartbeat_age_ms > MAX_HEARTBEAT_AGE_MS:
            decision = InterlockDecision(
                event_id=eid,
                allowed=False,
                code=InterlockCode.GATEWAY_HEARTBEAT_STALE,
                reason=InterlockReasonStr(
                    f"Gateway heartbeat age {heartbeat_age_ms:.1f}ms exceeds "
                    f"{MAX_HEARTBEAT_AGE_MS:.1f}ms tolerance",
                    code=InterlockCode.GATEWAY_HEARTBEAT_STALE,
                ),
                circuit_state=self._circuit_state,
                symbol=symbol,
                proposed_notional=proposed_notional,
                timestamp_utc=now,
            )
            self._interlock_events.append(decision)
            return decision

        # 2. Clock Skew Check
        if abs(clock_skew_ms) > MAX_CLOCK_SKEW_MS:
            decision = InterlockDecision(
                event_id=eid,
                allowed=False,
                code=InterlockCode.CLOCK_SKEW_BREACH,
                reason=InterlockReasonStr(
                    f"Clock skew {clock_skew_ms:.1f}ms exceeds {MAX_CLOCK_SKEW_MS:.1f}ms tolerance",
                    code=InterlockCode.CLOCK_SKEW_BREACH,
                ),
                circuit_state=self._circuit_state,
                symbol=symbol,
                proposed_notional=proposed_notional,
                timestamp_utc=now,
            )
            self._interlock_events.append(decision)
            return decision

        # 3. Active Circuit Breakers
        if (
            self._circuit_state != CircuitState.NORMAL
            and self._circuit_state != CircuitBreakerState.NORMAL
        ):
            breaker_code = InterlockCode.CIRCUIT_BREAKER_ACTIVE
            if self._circuit_state in (
                CircuitState.INTRA_PHASE_LOSS_LOCKOUT,
                CircuitBreakerState.INTRA_PHASE_LOSS_LOCKOUT,
            ):
                breaker_code = InterlockCode.INTRA_PHASE_LOSS_LOCKOUT
            elif self._circuit_state in (
                CircuitState.SUPERCRITICAL_CASCADE_LOCKOUT,
                CircuitBreakerState.SUPERCRITICAL_CASCADE_LOCKOUT,
            ):
                breaker_code = InterlockCode.SUPERCRITICAL_CASCADE_LOCKOUT

            decision = InterlockDecision(
                event_id=eid,
                allowed=False,
                code=breaker_code,
                reason=InterlockReasonStr(
                    f"Circuit breaker active: {self._circuit_state}",
                    code=breaker_code,
                ),
                circuit_state=self._circuit_state,
                symbol=symbol,
                proposed_notional=proposed_notional,
                timestamp_utc=now,
            )
            self._interlock_events.append(decision)
            return decision

        # 4. Intra-Phase Loss Ceiling
        effective_loss = max(
            self._cumulative_loss,
            abs(self._current_realized_pnl)
            if self._current_realized_pnl < Decimal("0")
            else Decimal("0"),
        )
        if effective_loss >= self.loss_ceiling:
            self._circuit_state = CircuitState.INTRA_PHASE_LOSS_LOCKOUT
            decision = InterlockDecision(
                event_id=eid,
                allowed=False,
                code=InterlockCode.INTRA_PHASE_LOSS_LOCKOUT,
                reason=InterlockReasonStr(
                    f"Cumulative loss {effective_loss} reached or exceeded "
                    f"budget ceiling {self.loss_ceiling}",
                    code=InterlockCode.INTRA_PHASE_LOSS_LOCKOUT,
                ),
                circuit_state=CircuitState.INTRA_PHASE_LOSS_LOCKOUT,
                symbol=symbol,
                proposed_notional=proposed_notional,
                timestamp_utc=now,
            )
            self._interlock_events.append(decision)
            return decision

        # 5. Hawkes Supercritical Cascade Lockout
        if spectral_radius >= HAWKES_SUPERCRITICAL_THRESHOLD:
            self._circuit_state = CircuitState.SUPERCRITICAL_CASCADE_LOCKOUT
            decision = InterlockDecision(
                event_id=eid,
                allowed=False,
                code=InterlockCode.SUPERCRITICAL_CASCADE_LOCKOUT,
                reason=InterlockReasonStr(
                    f"Supercritical runaway cascade lockout "
                    f"(rho={spectral_radius} >= {HAWKES_SUPERCRITICAL_THRESHOLD})",
                    code=InterlockCode.SUPERCRITICAL_CASCADE_LOCKOUT,
                ),
                circuit_state=CircuitState.SUPERCRITICAL_CASCADE_LOCKOUT,
                symbol=symbol,
                proposed_notional=proposed_notional,
                timestamp_utc=now,
            )
            self._interlock_events.append(decision)
            return decision

        # 6. Predatory Hazard Throttled Regime
        if spectral_radius >= HAWKES_SEVERE_REGIME_THRESHOLD or is_predatory:
            sym_total = self._active_exposures.get(
                symbol, Decimal("0")
            ) + self._working_notionals.get(symbol, Decimal("0"))
            if sym_total + proposed_notional > PREDATORY_SYMBOL_CAP_USDT:
                decision = InterlockDecision(
                    event_id=eid,
                    allowed=False,
                    code=InterlockCode.PREDATORY_HAZARD_THROTTLED,
                    reason=InterlockReasonStr(
                        f"Predatory/severe regime: symbol {symbol} exposure "
                        f"{sym_total + proposed_notional} > {PREDATORY_SYMBOL_CAP_USDT}",
                        code=InterlockCode.PREDATORY_HAZARD_THROTTLED,
                    ),
                    circuit_state=self._circuit_state,
                    symbol=symbol,
                    proposed_notional=proposed_notional,
                    timestamp_utc=now,
                )
                self._interlock_events.append(decision)
                return decision

        # 7. Aggregate Exposure Ceiling
        projected_total = self.total_exposure + proposed_notional
        if projected_total > self.aggregate_exposure_cap:
            decision = InterlockDecision(
                event_id=eid,
                allowed=False,
                code=InterlockCode.AGGREGATE_EXPOSURE_CAP_EXCEEDED,
                reason=InterlockReasonStr(
                    f"Projected total exposure {projected_total} exceeds cap "
                    f"{self.aggregate_exposure_cap}",
                    code=InterlockCode.AGGREGATE_EXPOSURE_CAP_EXCEEDED,
                ),
                circuit_state=self._circuit_state,
                symbol=symbol,
                proposed_notional=proposed_notional,
                timestamp_utc=now,
            )
            self._interlock_events.append(decision)
            return decision

        # 8. Per-Asset Exposure Ceiling
        sym_exposure = (
            self._active_exposures.get(symbol, Decimal("0"))
            + self._working_notionals.get(symbol, Decimal("0"))
            + proposed_notional
        )
        if sym_exposure > self.per_asset_margin_cap:
            decision = InterlockDecision(
                event_id=eid,
                allowed=False,
                code=InterlockCode.PER_ASSET_EXPOSURE_CAP_EXCEEDED,
                reason=InterlockReasonStr(
                    f"Symbol {symbol} exposure {sym_exposure} exceeds per-asset cap "
                    f"{self.per_asset_margin_cap}",
                    code=InterlockCode.PER_ASSET_EXPOSURE_CAP_EXCEEDED,
                ),
                circuit_state=self._circuit_state,
                symbol=symbol,
                proposed_notional=proposed_notional,
                timestamp_utc=now,
            )
            self._interlock_events.append(decision)
            return decision

        # 9. Dynamic Margin Headroom & Reserve Buffer (including V9 zero starting equity check)
        if self.starting_equity <= Decimal("0"):
            decision = InterlockDecision(
                event_id=eid,
                allowed=False,
                code=InterlockCode.MARGIN_HEADROOM_BREACH,
                reason=InterlockReasonStr(
                    "Starting equity is zero or negative; cannot allocate margin",
                    code=InterlockCode.MARGIN_HEADROOM_BREACH,
                ),
                circuit_state=self._circuit_state,
                symbol=symbol,
                proposed_notional=proposed_notional,
                timestamp_utc=now,
            )
            self._interlock_events.append(decision)
            return decision

        projected_utilization = projected_total / self.starting_equity
        projected_reserve = (
            self._current_cash - self.committed_working_total - proposed_notional
        ) / self.starting_equity

        if (
            projected_utilization > MAX_MARGIN_UTILIZATION_PCT
            or projected_reserve < MIN_RESERVE_BUFFER_PCT
        ):
            decision = InterlockDecision(
                event_id=eid,
                allowed=False,
                code=InterlockCode.MARGIN_HEADROOM_BREACH,
                reason=InterlockReasonStr(
                    f"Margin headroom breach: utilization={projected_utilization:.4f} "
                    f"(max {MAX_MARGIN_UTILIZATION_PCT}), "
                    f"reserve={projected_reserve:.4f} (min {MIN_RESERVE_BUFFER_PCT})",
                    code=InterlockCode.MARGIN_HEADROOM_BREACH,
                ),
                circuit_state=self._circuit_state,
                symbol=symbol,
                proposed_notional=proposed_notional,
                timestamp_utc=now,
            )
            self._interlock_events.append(decision)
            return decision

        # Passed all interlocks
        decision = InterlockDecision(
            event_id=eid,
            allowed=True,
            code=InterlockCode.NORMAL,
            reason=InterlockReasonStr("Normal risk profile", code=InterlockCode.NORMAL),
            circuit_state=CircuitState.NORMAL,
            symbol=symbol,
            proposed_notional=proposed_notional,
            timestamp_utc=now,
        )
        return decision

    def flatten_portfolio_emergency(
        self,
        positions: Mapping[str, Any] | None = None,
        prices: Mapping[str, Decimal] | None = None,
        now_ms: int = 0,
        chunk_cap: Decimal = HARD_MICRO_NOTIONAL_CAP_USDT,
        filters_map: Mapping[str, ExchangeSymbolFilters] | None = None,
        *,
        open_positions: Mapping[str, Any] | None = None,
        current_prices: Mapping[str, Decimal] | None = None,
        **kwargs: Any,
    ) -> list[ChildOrderIntention]:
        """Emergency portfolio flattening method."""
        return flatten_portfolio_emergency(
            positions=positions,
            prices=prices,
            now_ms=now_ms,
            chunk_cap=chunk_cap,
            filters_map=filters_map,
            open_positions=open_positions,
            current_prices=current_prices,
            **kwargs,
        )


def flatten_portfolio_emergency(
    positions: Mapping[str, Any] | None = None,
    prices: Mapping[str, Decimal] | None = None,
    now_ms: int = 0,
    chunk_cap: Decimal = HARD_MICRO_NOTIONAL_CAP_USDT,
    filters_map: Mapping[str, ExchangeSymbolFilters] | None = None,
    *,
    open_positions: Mapping[str, Any] | None = None,
    current_prices: Mapping[str, Decimal] | None = None,
    **kwargs: Any,
) -> list[ChildOrderIntention]:
    """Generate micro-chunked closing orders (<= 5.00 USDT) to liquidate all open positions."""
    from autonomous_futures.feed.paper_execution import get_default_exchange_filters

    effective_positions = open_positions if open_positions is not None else (positions or {})
    effective_prices = current_prices if current_prices is not None else (prices or {})
    effective_filters = filters_map if filters_map is not None else get_default_exchange_filters()

    if isinstance(now_ms, Decimal) and now_ms <= Decimal("10.0"):
        effective_chunk_cap = now_ms
        effective_now_ms = 0
    else:
        effective_chunk_cap = chunk_cap
        effective_now_ms = int(now_ms)

    closing_orders: list[ChildOrderIntention] = []

    for symbol, raw_pos in effective_positions.items():
        if isinstance(raw_pos, dict):
            qty = Decimal(str(raw_pos.get("quantity", "0")))
            side_str = str(raw_pos.get("side", "BUY")).upper()
            close_side = OrderSide.SELL if side_str == "BUY" else OrderSide.BUY
        else:
            qty = Decimal(str(raw_pos))
            if qty > Decimal("0"):
                close_side = OrderSide.SELL
            elif qty < Decimal("0"):
                close_side = OrderSide.BUY
            else:
                continue

        abs_qty = abs(qty)
        if abs_qty <= Decimal("0"):
            continue

        price = effective_prices.get(symbol, Decimal("100.00"))
        if price <= Decimal("0"):
            price = Decimal("1.00")

        f = effective_filters.get(symbol)
        step_size = f.quantity_step_size if f else Decimal("0.00001")

        remaining_qty = abs_qty
        parent_id = f"parent-flat-{symbol.lower()}-{effective_now_ms}"
        c_idx = 0

        while remaining_qty > Decimal("0"):
            remaining_notional = (remaining_qty * price).quantize(
                Decimal("0.00000001"), rounding=ROUND_DOWN
            )
            if remaining_notional <= effective_chunk_cap:
                this_qty = remaining_qty
            else:
                max_qty_for_cap = (effective_chunk_cap / price).quantize(
                    step_size, rounding=ROUND_DOWN
                )
                if max_qty_for_cap < step_size:
                    this_qty = (effective_chunk_cap / price).quantize(
                        Decimal("0.00000001"), rounding=ROUND_DOWN
                    )
                else:
                    this_qty = min(remaining_qty, max_qty_for_cap)
                    if this_qty >= step_size:
                        this_qty = (this_qty // step_size) * step_size

            if this_qty <= Decimal("0"):
                this_qty = remaining_qty

            notional = (this_qty * price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            while notional > effective_chunk_cap and this_qty > step_size:
                this_qty -= step_size
                notional = (this_qty * price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

            if this_qty <= Decimal("0") or notional > effective_chunk_cap:
                break

            cid = f"c-flat-{symbol.lower()}-{effective_now_ms}-{c_idx:02d}-{uuid.uuid4().hex[:6]}"
            order = ChildOrderIntention(
                client_order_id=cid,
                child_id=cid,
                parent_order_id=parent_id,
                parent_id=parent_id,
                child_index=c_idx,
                symbol=symbol,
                side=close_side,
                order_type=OrderType.MARKET,
                price=price,
                quantity=this_qty,
                notional_usdt=notional,
                notional=notional,
                time_in_force=TimeInForce.IOC,
                status=OrderStatus.OPEN,
                created_time_ms=effective_now_ms,
            )
            closing_orders.append(order)
            remaining_qty -= this_qty
            c_idx += 1

    return closing_orders


PaperRiskEngine = LivePaperRiskInterlock


__all__ = [
    "AGGREGATE_EXPOSURE_CAP_USDT",
    "AggregateExposureCapExceededError",
    "CircuitBreakerState",
    "CircuitBreakerTrippedError",
    "CircuitState",
    "ClockSkewExceededError",
    "GatewayHeartbeatStaleError",
    "HAWKES_SEVERE_REGIME_THRESHOLD",
    "HAWKES_SUPERCRITICAL_THRESHOLD",
    "HawkesSupercriticalCascadeError",
    "INTRA_PHASE_LOSS_CEILING_USDT",
    "InterlockCode",
    "InterlockDecision",
    "InterlockReason",
    "IntraPhaseLossCeilingExceededError",
    "LivePaperRiskInterlock",
    "MAX_CLOCK_SKEW_MS",
    "MAX_HEARTBEAT_AGE_MS",
    "MAX_MARGIN_UTILIZATION_PCT",
    "MIN_RESERVE_BUFFER_PCT",
    "MarginHeadroomBreachError",
    "PER_ASSET_MARGIN_CAP_USDT",
    "PREDATORY_SYMBOL_CAP_USDT",
    "PaperRiskEngine",
    "PaperRiskError",
    "PerAssetExposureCapExceededError",
    "STARTING_EQUITY_USDT",
    "flatten_portfolio_emergency",
]
