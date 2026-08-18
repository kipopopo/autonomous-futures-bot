"""Caller-injected, read-only lifecycle telemetry for an open paper position."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, TypeAdapter, field_validator, model_validator

from ..domain.contracts import DomainModel, StrictPositiveDecimal
from .ledger import PaperLedgerEntry


class PaperLifecycleTelemetry(DomainModel):
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    trade_id: str = Field(pattern=r"^[A-Za-z0-9._-]+$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    side: Literal["LONG", "SHORT"]
    opened_at: datetime
    marked_at: datetime
    entry_price: StrictPositiveDecimal
    mark_price: StrictPositiveDecimal
    quantity: StrictPositiveDecimal
    mark_to_market_pnl: Decimal
    pnl_pct: Decimal
    peak_pnl: Decimal
    holding_seconds: int = Field(ge=0, strict=True)
    stop_loss_price: StrictPositiveDecimal | None = None
    take_profit_price: StrictPositiveDecimal | None = None
    stop_loss_hit: bool
    take_profit_hit: bool
    lifecycle_status: Literal["open", "exit_ready"]
    reason_codes: tuple[str, ...] = Field(min_length=1)
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False

    @field_validator("opened_at", "marked_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("lifecycle timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def marked_after_opened(self) -> PaperLifecycleTelemetry:
        if self.marked_at < self.opened_at:
            raise ValueError("lifecycle mark cannot precede paper open")
        if not self.mark_to_market_pnl.is_finite() or not self.pnl_pct.is_finite():
            raise ValueError("lifecycle P&L must be finite")
        if not self.peak_pnl.is_finite():
            raise ValueError("lifecycle peak P&L must be finite")
        return self


def mark_paper_position(
    open_entry: PaperLedgerEntry,
    *,
    mark_price: Decimal,
    marked_at: datetime,
    previous_peak_pnl: Decimal,
    stop_loss_price: Decimal | None = None,
    take_profit_price: Decimal | None = None,
) -> PaperLifecycleTelemetry:
    """Calculate one explicit mark without changing the ledger or accessing a price source."""
    if open_entry.event != "open":
        raise ValueError("lifecycle telemetry requires an open ledger entry")
    positive = TypeAdapter(StrictPositiveDecimal)
    mark = positive.validate_python(mark_price)
    stop = None if stop_loss_price is None else positive.validate_python(stop_loss_price)
    take_profit = None if take_profit_price is None else positive.validate_python(take_profit_price)
    if not previous_peak_pnl.is_finite():
        raise ValueError("previous peak P&L must be finite")
    if marked_at.tzinfo is None or marked_at.utcoffset() != UTC.utcoffset(marked_at):
        raise ValueError("marked_at must be timezone-aware UTC")
    marked = marked_at.astimezone(UTC)
    if marked < open_entry.occurred_at:
        raise ValueError("lifecycle mark cannot precede paper open")
    if open_entry.side == "LONG":
        if stop is not None and stop >= open_entry.fill_price:
            raise ValueError("long stop loss must be below entry price")
        if take_profit is not None and take_profit <= open_entry.fill_price:
            raise ValueError("long take profit must be above entry price")
        pnl = (mark - open_entry.fill_price) * open_entry.quantity
        stop_hit = stop is not None and mark <= stop
        take_profit_hit = take_profit is not None and mark >= take_profit
    else:
        if stop is not None and stop <= open_entry.fill_price:
            raise ValueError("short stop loss must be above entry price")
        if take_profit is not None and take_profit >= open_entry.fill_price:
            raise ValueError("short take profit must be below entry price")
        pnl = (open_entry.fill_price - mark) * open_entry.quantity
        stop_hit = stop is not None and mark >= stop
        take_profit_hit = take_profit is not None and mark <= take_profit
    notional = open_entry.fill_price * open_entry.quantity
    duration_seconds = int((marked - open_entry.occurred_at).total_seconds())
    if (marked - open_entry.occurred_at).total_seconds() != duration_seconds:
        raise ValueError("lifecycle timestamps must have whole-second precision")
    reasons = tuple(
        reason
        for condition, reason in (
            (stop_hit, "stop_loss_hit"),
            (take_profit_hit, "take_profit_hit"),
        )
        if condition
    )
    return PaperLifecycleTelemetry(
        candidate_id=open_entry.candidate_id,
        candidate_artifact_hash=open_entry.candidate_artifact_hash,
        trade_id=open_entry.trade_id,
        symbol=open_entry.symbol,
        side=open_entry.side,
        opened_at=open_entry.occurred_at,
        marked_at=marked,
        entry_price=open_entry.fill_price,
        mark_price=mark,
        quantity=open_entry.quantity,
        mark_to_market_pnl=pnl,
        pnl_pct=pnl / notional,
        peak_pnl=max(previous_peak_pnl, pnl),
        holding_seconds=duration_seconds,
        stop_loss_price=stop,
        take_profit_price=take_profit,
        stop_loss_hit=stop_hit,
        take_profit_hit=take_profit_hit,
        lifecycle_status="exit_ready" if reasons else "open",
        reason_codes=reasons or ("lifecycle_open",),
    )
