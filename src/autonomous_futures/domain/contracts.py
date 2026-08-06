from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

StrictPositiveDecimal = Annotated[Decimal, Field(strict=True, gt=Decimal("0"))]
StrictNonNegativeDecimal = Annotated[Decimal, Field(strict=True, ge=Decimal("0"))]


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OrderAction(StrEnum):
    OPEN_LONG = "OPEN_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    CLOSE = "CLOSE"


class OrderIntent(DomainModel):
    """LLM-free venue-neutral intent; final size and leverage belong to risk."""

    intent_id: UUID
    candidate_manifest_hash: str = Field(min_length=1)
    symbol: str = Field(min_length=1, pattern=r"^[A-Z0-9]+$")
    action: OrderAction
    signal_time: datetime
    valid_until: datetime
    reference_price: StrictPositiveDecimal
    requested_stop_price: StrictPositiveDecimal
    requested_take_profit: StrictPositiveDecimal | None = None
    reason_codes: tuple[str, ...] = Field(min_length=1)
    feature_snapshot_hash: str = Field(min_length=1)
    requested_quantity: None = None
    requested_leverage: None = None

    @field_validator("signal_time", "valid_until")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("timezone-aware UTC timestamp required")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_window(self) -> OrderIntent:
        if self.valid_until <= self.signal_time:
            raise ValueError("valid_until must be after signal_time")
        return self


class RiskDecision(DomainModel):
    decision: Literal["APPROVE", "REJECT", "REDUCE", "HALT_AND_FLATTEN"]
    intent_id: UUID
    normalized_quantity: StrictNonNegativeDecimal
    selected_leverage: StrictNonNegativeDecimal
    estimated_loss_at_stop_usd: StrictNonNegativeDecimal
    estimated_round_trip_cost_usd: StrictNonNegativeDecimal
    stop_required: bool
    reduce_only_exit: bool
    policy_version: str = Field(min_length=1)
    reason_codes: tuple[str, ...] = Field(min_length=1)
    input_state_hash: str = Field(min_length=1)


class PositionState(DomainModel):
    symbol: str = Field(min_length=1, pattern=r"^[A-Z0-9]+$")
    quantity: StrictPositiveDecimal
    side: Literal["LONG", "SHORT"]


class StrategyUniverse(DomainModel):
    symbols: tuple[str, ...] = Field(min_length=1)
    timeframe: Literal["5m"]
    regime_context_timeframe: Literal["15m"]

    @field_validator("symbols")
    @classmethod
    def symbols_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or value != value.upper() for value in values):
            raise ValueError("symbols must be uppercase")
        return values


ALLOWED_FEATURES = frozenset(
    {
        "returns",
        "atr",
        "normalized_atr",
        "realized_volatility",
        "donchian_high",
        "donchian_low",
        "ema_slope",
        "ema_distance",
        "adx",
        "bollinger_zscore",
        "bollinger_width",
        "rsi",
        "volume",
        "relative_volume",
        "funding_rate",
        "spread_proxy",
        "regime_trend",
    }
)


class FeatureRef(DomainModel):
    name: str = Field(min_length=1)
    lookback: Annotated[int, Field(gt=0)]
    shift: Annotated[int, Field(ge=1)]

    @field_validator("name")
    @classmethod
    def feature_is_approved(cls, value: str) -> str:
        if value not in ALLOWED_FEATURES:
            raise ValueError(f"unknown feature: {value}")
        return value


class EntryExit(DomainModel):
    long: str = Field(min_length=1)
    short: str = Field(min_length=1)

    @field_validator("long", "short")
    @classmethod
    def expression_is_bounded(cls, value: str) -> str:
        if any(token in value.lower() for token in ("__", "import", "exec", "eval", "system")):
            raise ValueError("unsafe expression")
        if not all(character.isalnum() or character in "_ .<>=()+-*/" for character in value):
            raise ValueError("unsafe expression")
        return value


class StrategySpec(DomainModel):
    dsl_version: Literal[1]
    strategy_id: str = Field(min_length=1)
    family: Literal["regime_gated_breakout", "range_mean_reversion", "experimental"]
    universe: StrategyUniverse
    features: tuple[FeatureRef, ...] = Field(min_length=1)
    entry: EntryExit
    exit: EntryExit
    vetoes: tuple[str, ...] = Field(min_length=1)


def parse_strategy_spec(payload: Mapping[str, object]) -> StrategySpec:
    """Validate untrusted model output without executing or compiling code."""
    return StrategySpec.model_validate(payload)
