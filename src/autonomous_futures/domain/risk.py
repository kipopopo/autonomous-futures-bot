from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import PositionState
from .errors import DomainViolation
from .runtime import RuntimeEvent, RuntimeState, transition_runtime_state

StrictPositiveDecimal = Annotated[Decimal, Field(strict=True, gt=Decimal("0"))]
StrictNonNegativeDecimal = Annotated[Decimal, Field(strict=True, ge=Decimal("0"))]


class ResumeEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reconciled: bool
    incident_resolved: bool
    data_fresh: bool
    risk_healthy: bool
    operator_approved: bool

    @property
    def can_resume(self) -> bool:
        return all(
            (
                self.reconciled,
                self.incident_resolved,
                self.data_fresh,
                self.risk_healthy,
                self.operator_approved,
            )
        )


class PositionBook:
    def __init__(self, max_positions: int = 1) -> None:
        if max_positions < 1:
            raise ValueError("max_positions must be positive")
        self._max_positions = max_positions
        self._positions: dict[str, PositionState] = {}

    @property
    def positions(self) -> tuple[PositionState, ...]:
        return tuple(self._positions.values())

    def open(self, position: PositionState) -> None:
        symbol = position.symbol
        if symbol in self._positions:
            raise DomainViolation(f"active position already exists for {symbol}")
        if len(self._positions) >= self._max_positions:
            raise DomainViolation("global position limit reached")
        self._positions[symbol] = position


class RiskPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_selected_leverage: Decimal = Decimal("2")
    absolute_trade_risk_cap: Decimal = Decimal("0.01")
    max_effective_notional_multiplier: Decimal = Decimal("1")
    drawdown_throttle: Decimal = Decimal("0.05")
    drawdown_halt: Decimal = Decimal("0.08")
    catastrophic_drawdown: Decimal = Decimal("0.10")

    @model_validator(mode="after")
    def validate_drawdown_order(self) -> RiskPolicy:
        if not (
            Decimal("0") < self.drawdown_throttle < self.drawdown_halt < self.catastrophic_drawdown
        ):
            raise ValueError("drawdown thresholds must be strictly ordered")
        return self


class RiskSizingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equity_usd: StrictPositiveDecimal
    risk_fraction: StrictPositiveDecimal
    stop_distance_fraction: StrictPositiveDecimal
    estimated_round_trip_cost_usd: StrictNonNegativeDecimal
    minimum_notional_usd: StrictNonNegativeDecimal


class RiskSizingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVE", "REJECT"]
    approved_notional_usd: StrictNonNegativeDecimal
    estimated_loss_at_stop_usd: StrictNonNegativeDecimal
    estimated_round_trip_cost_usd: StrictNonNegativeDecimal
    reason_codes: tuple[str, ...] = Field(min_length=1)


def evaluate_sizing(request: RiskSizingRequest, policy: RiskPolicy) -> RiskSizingResult:
    """Return a deterministic notional decision before any broker command exists."""
    risk_budget = request.equity_usd * request.risk_fraction
    if request.risk_fraction > policy.absolute_trade_risk_cap:
        return RiskSizingResult(
            decision="REJECT",
            approved_notional_usd=Decimal("0"),
            estimated_loss_at_stop_usd=Decimal("0"),
            estimated_round_trip_cost_usd=request.estimated_round_trip_cost_usd,
            reason_codes=("RISK_FRACTION_ABOVE_CAP",),
        )

    if request.estimated_round_trip_cost_usd >= risk_budget:
        return RiskSizingResult(
            decision="REJECT",
            approved_notional_usd=Decimal("0"),
            estimated_loss_at_stop_usd=Decimal("0"),
            estimated_round_trip_cost_usd=request.estimated_round_trip_cost_usd,
            reason_codes=("COST_EXCEEDS_RISK_BUDGET",),
        )

    raw_notional = (risk_budget - request.estimated_round_trip_cost_usd) / (
        request.stop_distance_fraction
    )
    max_notional = request.equity_usd * policy.max_effective_notional_multiplier
    approved = min(raw_notional, max_notional)
    if request.minimum_notional_usd > approved:
        minimum_loss = (
            request.minimum_notional_usd * request.stop_distance_fraction
            + request.estimated_round_trip_cost_usd
        )
        if minimum_loss > risk_budget or request.minimum_notional_usd > max_notional:
            return RiskSizingResult(
                decision="REJECT",
                approved_notional_usd=Decimal("0"),
                estimated_loss_at_stop_usd=Decimal("0"),
                estimated_round_trip_cost_usd=request.estimated_round_trip_cost_usd,
                reason_codes=("MINIMUM_NOTIONAL_BREACHES_RISK",),
            )
        approved = request.minimum_notional_usd

    estimated_loss = approved * request.stop_distance_fraction
    return RiskSizingResult(
        decision="APPROVE",
        approved_notional_usd=approved,
        estimated_loss_at_stop_usd=estimated_loss,
        estimated_round_trip_cost_usd=request.estimated_round_trip_cost_usd,
        reason_codes=("WITHIN_TRADE_RISK",),
    )


__all__ = [
    "PositionBook",
    "ResumeEvidence",
    "RiskPolicy",
    "RiskSizingRequest",
    "RiskSizingResult",
    "RuntimeEvent",
    "RuntimeState",
    "evaluate_sizing",
    "transition_runtime_state",
]
