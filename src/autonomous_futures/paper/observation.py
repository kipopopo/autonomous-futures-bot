"""Read-only paper observations from durable-ledger state and explicit marks."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import Field, TypeAdapter, field_validator

from ..domain.contracts import DomainModel, StrictNonNegativeDecimal, StrictPositiveDecimal
from .ledger import PaperLedger, PaperLedgerEntry


class PaperObservation(DomainModel):
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime
    equity: StrictNonNegativeDecimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    peak_equity: StrictPositiveDecimal
    drawdown_pct: Decimal
    open_position_count: int = Field(ge=0, strict=True)
    quote_exposure: StrictNonNegativeDecimal
    cumulative_fees: StrictNonNegativeDecimal
    cumulative_slippage: StrictNonNegativeDecimal
    accounting_complete: bool
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("paper observation timestamp must be timezone-aware UTC")
        return value.astimezone(UTC)


class PaperObservationBinding(DomainModel):
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def _sum(values: tuple[Decimal, ...]) -> Decimal:
    with localcontext() as context:
        context.prec = max(context.prec, 80)
        return +sum(values, Decimal("0"))


def _matching(entry: PaperLedgerEntry, candidate_id: str, candidate_artifact_hash: str) -> bool:
    return (
        entry.candidate_id == candidate_id
        and entry.candidate_artifact_hash == candidate_artifact_hash
    )


def observe_paper_ledger(
    ledger: PaperLedger,
    *,
    candidate_id: str,
    candidate_artifact_hash: str,
    starting_equity: Decimal,
    previous_peak_equity: Decimal,
    mark_prices: Mapping[str, Decimal],
    observed_at: datetime,
) -> PaperObservation:
    """Derive a non-authoritative paper snapshot without mutating the ledger."""
    positive = TypeAdapter(StrictPositiveDecimal)
    starting = positive.validate_python(starting_equity)
    previous_peak = positive.validate_python(previous_peak_equity)
    closed = tuple(
        entry
        for entry in ledger.entries
        if entry.event == "close" and _matching(entry, candidate_id, candidate_artifact_hash)
    )
    opens = tuple(
        entry
        for entry in ledger.open_positions()
        if _matching(entry, candidate_id, candidate_artifact_hash)
    )
    realized = _sum(tuple(entry.net_pnl for entry in closed if entry.net_pnl is not None))
    fees = _sum(
        tuple(
            entry.entry_fee + entry.exit_fee
            for entry in closed
            if entry.entry_fee is not None and entry.exit_fee is not None
        )
    )
    slippage = _sum(
        tuple(entry.slippage_cost for entry in closed if entry.slippage_cost is not None)
    )
    marks: dict[str, Decimal] = {}
    for entry in opens:
        if entry.symbol not in mark_prices:
            raise ValueError(f"missing explicit mark for paper symbol: {entry.symbol}")
        marks[entry.symbol] = positive.validate_python(mark_prices[entry.symbol])
    unrealized = _sum(
        tuple(
            (marks[entry.symbol] - entry.fill_price) * entry.quantity
            if entry.side == "LONG"
            else (entry.fill_price - marks[entry.symbol]) * entry.quantity
            for entry in opens
        )
    )
    exposure = _sum(tuple(marks[entry.symbol] * entry.quantity for entry in opens))
    open_fees = _sum(tuple(entry.entry_fee for entry in opens if entry.entry_fee is not None))
    open_slippage = _sum(
        tuple(entry.slippage_cost for entry in opens if entry.slippage_cost is not None)
    )
    equity = starting + realized + unrealized - open_fees
    peak = max(starting, previous_peak, equity)
    with localcontext() as context:
        context.prec = max(context.prec, 80)
        drawdown = min(Decimal("0"), (equity - peak) / peak)
    complete = all(
        entry.entry_fee is not None and entry.slippage_cost is not None for entry in opens
    )
    return PaperObservation(
        candidate_id=candidate_id,
        candidate_artifact_hash=candidate_artifact_hash,
        observed_at=observed_at,
        equity=equity,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        peak_equity=peak,
        drawdown_pct=drawdown,
        open_position_count=len(opens),
        quote_exposure=exposure,
        cumulative_fees=fees + open_fees,
        cumulative_slippage=slippage + open_slippage,
        accounting_complete=complete,
        reason_codes=(
            ("paper_observation_complete",)
            if complete
            else ("open_position_entry_accounting_unavailable",)
        ),
    )
